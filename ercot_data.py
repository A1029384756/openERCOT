import datetime
from io import BytesIO
from typing import List, Optional
from zipfile import ZipFile

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


def get_mis_doc_ids(report_type_id: int) -> List[int]:
    url = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS"
    r = requests.get(url, params={"reportTypeId": report_type_id})
    docs = r.json()["ListDocsByRptTypeRes"]["DocumentList"]
    doc_ids = [int(doc["Document"]["DocID"]) for doc in docs]
    return doc_ids


def get_fuel_mix_data() -> DataFrame[ERCOTFuelMixData]:
    # check this for hour ending / hour beginning
    # should be hour ending
    # change how this points to certain files depending on the year
    fuel_mix = pd.read_excel(
        io="https://www.ercot.com/files/docs/2022/02/08/IntGenbyFuel2022.xlsx",
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


def download_all_ercot_renewable_data():
    # make this id referenced in some file
    docs = get_mis_doc_ids(13424)
    for renew_id in docs:
        print(get_ercot_renewable_data(renew_id))


def get_eroct_load_data(year):
    url = requests.get(
        "https://www.ercot.com/files/docs/2022/02/08/Native_Load_2022.zip"
    )
    load_data = pd.read_excel(
        ZipFile(BytesIO(url.content)).open("Native_Load_2022.xlsx")
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
    load_data = load_data.resample("H").mean().interpolate()
    return load_data


def get_ercot_renewable_data(snapshots) -> DataFrame[ERCOTRenewableData]:
    renewable_gen = pd.read_excel(
        "https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId=890277261",
        sheet_name=["Wind Data", "Solar Data"],
    )
    wind = renewable_gen["Wind Data"]
    wind = wind.drop_duplicates("Time (Hour-Ending)").set_index("Time (Hour-Ending)")
    wind.index = pd.to_datetime(wind.index)

    solar = renewable_gen["Solar Data"]
    solar = solar.drop_duplicates(subset="Time (Hour-Ending)").set_index(
        "Time (Hour-Ending)"
    )
    solar.index = pd.to_datetime(solar.index)

    renew_df = pd.DataFrame(index=snapshots)
    renew_df["Solar Photovoltaic"] = solar["Solar Output, % of Installed"] / 100
    renew_df["Onshore Wind Turbine"] = wind["Wind Output, % of Installed"] / 100

    hydro_gen = get_fuel_mix_data()
    hydro_gen.index = pd.to_datetime(hydro_gen.index)
    renew_df["Conventional Hydroelectric"] = hydro_gen["hydro"] / hydro_gen["hydro"].max()
    final_df: DataFrame[ERCOTRenewableData] = renew_df

    # if we are missing any values, interpolate
    if final_df.isnull().values.any():
        final_df = final_df.interpolate()
    return final_df


if __name__ == "__main__":
    df = get_eroct_load_data(2022)
