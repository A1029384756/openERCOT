import datetime
from io import BytesIO
from typing import List, Optional, Tuple
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pandera as pa
from pandera.typing import Series, DataFrame, Index
import requests

ZONE_NAME_MAP = {
    "FWEST": "FAR WEST",
    "NCENT": "NORTH CENTRAL",
    "SCENT": "SOUTH CENTRAL",
}


class ERCOTFuelMixData(pa.DataFrameModel):
    hour_ending: Index[datetime.datetime]
    biomass: float
    coal: float
    gas: float
    hydro: float
    nuclear: float
    other: float
    solar: float
    wsl: float
    wind: float


class ERCOTRenewableData(pa.DataFrameModel):
    snapshot: Index[datetime.datetime]
    solar: Series[float] = pa.Field(ge=0, le=1, alias="Solar Photovoltaic")
    wind: Series[float] = pa.Field(ge=0, le=1, alias="Onshore Wind Turbine")
    hydro: Series[float] = pa.Field(ge=0, le=1, alias="Conventional Hydroelectric")


class ERCOTLoadData(pa.DataFrameModel):
    snapshot: Index[datetime.datetime] = pa.Field(unique=True, alias="Hour Ending")
    coast: Series[float] = pa.Field(alias="COAST")
    east: Series[float] = pa.Field(alias="EAST")
    far_west: Series[float] = pa.Field(alias="FAR WEST")
    north: Series[float] = pa.Field(alias="NORTH")
    north_central: Series[float] = pa.Field(alias="NORTH CENTRAL")
    south: Series[float] = pa.Field(alias="SOUTH")
    south_central: Series[float] = pa.Field(alias="SOUTH CENTRAL")
    west: Series[float] = pa.Field(alias="WEST")
    ercot: Series[float] = pa.Field(alias="ERCOT")


def get_mis_doc_ids(report_type_id: int) -> List[int]:
    url = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS"
    r = requests.get(url, params={"reportTypeId": report_type_id})
    docs = r.json()["ListDocsByRptTypeRes"]["DocumentList"]
    doc_ids = [int(doc["Document"]["DocID"]) for doc in docs]
    return doc_ids


def get_ercot_fuel_mix_data_annual(file_url: str) -> DataFrame[ERCOTFuelMixData]:
    # check this for hour ending / hour beginning
    # should be hour ending
    # change how this points to certain files depending on the year
    fuel_mix = pd.read_excel(
        io=file_url,
        sheet_name=None,
    )
    total_data = []
    for month in list(fuel_mix.values())[-12:]:
        for date in month["Date"].unique():
            day_data = month[month["Date"] == date]
            filtered_day_data = day_data.loc[
                                :, ~day_data.columns.isin(["Date", "Settlement Type", "Total"])
                                ]
            filtered_day_data = filtered_day_data.set_index("Fuel").T.reset_index(
                drop=True
            )
            filtered_day_data = filtered_day_data.groupby(
                filtered_day_data.index // 4
            ).sum()
            filtered_day_data.index = date + pd.to_timedelta(
                filtered_day_data.index + 1, unit="H"
            )
            total_data.append(filtered_day_data.head(24))
    complete_data = pd.concat(total_data)
    complete_data.index.names = ["hour_ending"]
    complete_data.columns = map(str.lower, complete_data.columns)
    complete_data.columns = complete_data.columns.str.replace("-", "", regex=True)
    # merge combined cycle and regular gas turbines
    complete_data["gas"] = complete_data["gas"] + complete_data["gascc"]
    complete_data.drop(columns="gascc")
    final_data: DataFrame[ERCOTFuelMixData] = complete_data
    return final_data


def get_ercot_fuel_mix_data(files: np.ndarray[str], years: np.ndarray[int]) -> DataFrame[ERCOTFuelMixData]:
    total_data = []
    for file in files:
        total_data.append(get_ercot_fuel_mix_data_annual(file))
    total_df = pd.concat(total_data)
    total_df.sort_index(inplace=True)
    total_df.fillna(0, inplace=True)
    total_df = total_df.resample("H").interpolate()
    final_df: DataFrame[ERCOTFuelMixData] = total_df[total_df.index.year.isin(years)]
    return final_df


def get_ercot_solar_wind_data(doc_ids, years):
    solar_total = []
    wind_total = []
    for renew_id in doc_ids:
        solar, wind = get_ercot_solar_wind_data_annual(renew_id)
        solar_total.append(solar)
        wind_total.append(wind)
    solar = pd.concat(solar_total)
    wind = pd.concat(wind_total)
    combined = pd.concat([solar, wind], axis=1)
    combined.sort_index(inplace=True)
    combined = combined.resample("H").interpolate()
    combined = combined[combined.index.year.isin(years)]
    return combined.iloc[1:]


def get_eroct_load_data_annual(zip_url: str) -> DataFrame[ERCOTLoadData]:
    url = requests.get(
        zip_url
    )
    zip_file = ZipFile(BytesIO(url.content))

    load_data = pd.read_excel(
        zip_file.open(zip_file.namelist()[0])
    )
    load_data.rename(mapper=ZONE_NAME_MAP, axis=1, inplace=True)
    # drop daylight savings hour
    load_data = load_data[~load_data["Hour Ending"].str.contains("DST", na=False)]
    # shift HE 24 to HE 0 the next day
    load_data["Hour Ending"] = load_data["Hour Ending"].str.replace("24:00", "00:00")
    load_data["Hour Ending"] = pd.to_datetime(load_data["Hour Ending"])
    load_data.set_index("Hour Ending", inplace=True)
    load_data.index = load_data.index.map(
        lambda x: x + pd.Timedelta(1, "D") if x.hour == 0 else x
    )
    # fix any missing holes
    load_data: DataFrame[ERCOTLoadData] = load_data.resample("H").interpolate()
    return load_data


def get_ercot_load(load_urls: np.ndarray[str], years: np.ndarray[int]) -> DataFrame[ERCOTLoadData]:
    total_data = []
    for url in load_urls:
        total_data.append(get_eroct_load_data_annual(url))
    final_data = pd.concat(total_data)
    final_data.sort_index(inplace=True)
    filtered_data: DataFrame[ERCOTLoadData] = final_data[final_data.index.year.isin(years)]
    return filtered_data


def get_ercot_solar_wind_data_annual(doc_id) -> Tuple[pd.Series, pd.Series]:
    renewable_gen = pd.read_excel(
        f"https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={doc_id}",
        sheet_name=["Wind Data", "Solar Data"], usecols="A, G", index_col=0
    )

    wind = renewable_gen["Wind Data"]
    wind.index = pd.to_datetime(wind.index)
    wind_scaled = wind["Wind Output, % of Installed"] / 100
    wind_scaled.name = "Onshore Wind Turbine"
    wind_scaled = wind_scaled[~wind_scaled.index.duplicated()]

    solar = renewable_gen["Solar Data"]
    solar.index = pd.to_datetime(solar.index)
    solar_scaled = solar["Solar Output, % of Installed"] / 100
    solar_scaled.name = "Solar Photovoltaic"
    solar_scaled = solar_scaled[~solar_scaled.index.duplicated()]

    return solar_scaled, wind_scaled


def get_all_ercot_data():
    ercot_files = pd.read_csv("ercot_files.csv", index_col="year")
    fuel_mix = get_ercot_fuel_mix_data(ercot_files["fuel_mix"].values, ercot_files.index.values)
    load = get_ercot_load(ercot_files["load"].values, ercot_files.index.values)
    renewable = get_ercot_solar_wind_data(ercot_files["renewable_gen"].values, ercot_files.index.values)
    renewable["Conventional Hydroelectric"] = fuel_mix["hydro"] / fuel_mix["hydro"].max()
    return load, renewable


if __name__ == "__main__":
    get_all_ercot_data()
