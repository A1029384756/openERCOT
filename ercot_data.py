import datetime
from typing import List, Optional

import pandas as pd
import pandera as pa
from pandera.typing import Series, DataFrame, Index
import requests


class ERCOTRenewableData(pa.DataFrameModel):
    wind_utilization: Series[float] = pa.Field(ge=0, le=1)
    solar_utilization: Series[float] = pa.Field(ge=0, le=1)


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


def get_mis_doc_ids(report_type_id: int) -> List[int]:
    url = "https://www.ercot.com/misapp/servlets/IceDocListJsonWS"
    r = requests.get(url, params={"reportTypeId": report_type_id})
    docs = r.json()["ListDocsByRptTypeRes"]["DocumentList"]
    doc_ids = [int(doc["Document"]["DocID"]) for doc in docs]
    return doc_ids


def get_ercot_renewable_data(doc_id: int) -> Optional[DataFrame[ERCOTRenewableData]]:
    try:
        renewable_gen = pd.read_excel(
            io=f"https://www.ercot.com/misdownload/servlets/mirDownload?doclookupId={doc_id}",
            sheet_name=["Wind Data", "Solar Data"], usecols="A,G", names=["datetime", "utilization"], index_col=0
        )
    except ValueError:
        return None
    wind = renewable_gen["Wind Data"].add_prefix("wind_")
    solar = renewable_gen["Solar Data"].add_prefix("solar_")
    df: DataFrame[ERCOTRenewableData] = pd.concat([wind, solar], axis=1) / 100
    return df


def get_fuel_mix_data() -> DataFrame[ERCOTFuelMixData]:
    # check this for hour ending / hour beginning
    # should be hour ending
    # change how this points to certain files depending on the year
    fuel_mix = pd.read_excel(io="https://www.ercot.com/files/docs/2022/02/08/IntGenbyFuel2022.xlsx", sheet_name=None)
    total_data = []
    for month in list(fuel_mix.values())[-12:]:
        for date in month["Date"].unique():
            day_data = month[month["Date"] == date]
            filtered_day_data = day_data.loc[:, ~day_data.columns.isin(["Date", "Settlement Type", "Total"])]
            filtered_day_data = filtered_day_data.set_index("Fuel").T.reset_index(drop=True)
            filtered_day_data = filtered_day_data.groupby(filtered_day_data.index // 4).sum()
            filtered_day_data.index = date + pd.to_timedelta(filtered_day_data.index + 1, unit="H")
            total_data.append(filtered_day_data.head(24))
    complete_data = pd.concat(total_data)
    complete_data.index.names = ['hour_ending']
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


if __name__ == "__main__":
    data = get_fuel_mix_data()
    data.to_csv("2022_fuel_mix.csv")
