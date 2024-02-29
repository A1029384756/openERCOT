import datetime
import os
from time import sleep
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")


def build_params_units(start: str, end: str, offset: int) -> str:
    """
    builds x-params for eia api units api call
    :param start: year-month start as a string with a '-' separating them
    :param end: year-month end as a string with a '-' separating them
    :param offset: integer offset for pagination
    :return: x-params as a string
    """
    return (
        '{"frequency":"monthly","data":["county"],"facets":{"balancing_authority_code":["ERCO"]},"start":"'
        + start
        + '","end":"'
        + end
        + '","sort":[{"column":"period","direction":"desc"}],"offset":'
        + str(offset)
        + ',"length":5000, "data": [ "county", "nameplate-capacity-mw", "net-summer-capacity-mw", "net-winter-capacity-mw", "operating-year-month" ]}'
    )


def build_params_fuels(start: str, end: str, offset: int) -> str:
    """
    builds x-params for eia fuels api call
    :param start: start of interval as year-month zero padded
    :param end: end of interval as year-month zero padded
    :param offset: integer offset for pagination
    :return: x-params as a string
    """
    return (
        '{ "frequency": "monthly", "data": [ "cost-per-btu" ], "facets": { "location": [ "TX" ] }, "start": "'
        + start
        + '", "end": "'
        + end
        + '", "sort": [ { "column": "period", "direction": "desc" } ], "offset": '
        + str(offset)
        + ', "length": 5000 }'
    )


def build_params_generations(
    start: str, end: str, plant_ids: List[str], offset: int
) -> str:
    """
    builds x-params for eia fuels api call
    :param start: year-month to start
    :param end: year-month to end
    :param plant_ids: EIA plant IDs to retrieve data for
    :param offset: integer offset for pagination
    :return: x-params as a string
    """
    return (
        '{ "frequency": "annual", "data": [ "total-consumption-btu", "generation" ], "facets": { "primeMover": ["ALL"], "fuel2002": ["ALL"], "plantCode": [ "'
        + '", "'.join(plant_ids)
        + '" ] }, "start": "'
        + start
        + '", "end": "'
        + end
        + '", "sort": [ { "column": "period", "direction": "desc" } ], "offset": '
        + str(offset)
        + ', "length": 5000 }'
    )


def get_eia_units_status(year: int) -> pd.DataFrame:
    """
    gets eia statuses for units in a specific year
    :param year: year to get unit statuses
    :return: pivoted dataframe with plantid, generatorid and status for each given period in a year
    """
    data = get_eia_unit_data(year, last=False)
    units = pd.DataFrame(data).drop_duplicates(ignore_index=True)
    return units.pivot(
        index=["plantid", "generatorid"], columns="period", values="status"
    )


def get_eia_unit_capacity_bounds() -> Tuple[int, str]:
    """
    retrieves EIA API bounds for operating generator capacity
    :return: year, year-month as int, string
    """
    url = "https://api.eia.gov/v2/electricity/operating-generator-capacity/"
    r = requests.get(url, params={"api_key": EIA_API_KEY})
    end = r.json()["response"]["endPeriod"]
    return int(end[0:4]), end


def get_eia_unit_data(start: str, end: str) -> pd.DataFrame:
    data = []
    url = "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
    offset: int = 0
    total: int = 0

    while offset == 0 or offset < total:
        r = requests.get(
            url,
            headers={"x-params": build_params_units(start, end, offset)},
            params={"api_key": EIA_API_KEY},
        )
        if r.status_code == 200:
            total = int(r.json()["response"]["total"])
            data.extend(r.json()["response"]["data"])
            offset += 5000
        elif r.status_code == 409:
            print("Waiting 5 Seconds Before Next Request", r.json())
            sleep(5)
        else:
            raise ConnectionError("Issue with request", r.json())
    total_data = pd.DataFrame(data)
    return total_data.astype({"plantid": pd.Int32Dtype()})


def get_fuel_costs_month(year_month) -> List:
    url = "https://api.eia.gov/v2/electricity/electric-power-operational-data/data/"

    r = requests.get(
        url,
        headers={"x-params": build_params_fuels(year_month, year_month, 0)},
        params={"api_key": EIA_API_KEY},
    )
    if r.json()["response"].get("warning"):
        print(r.json()["response"]["warning"])
    return r.json()["response"]["data"]


def get_fuel_costs(start: datetime.datetime, end: datetime.datetime) -> pd.DataFrame:
    month_range = [f"{month:%Y-%m}" for month in pd.date_range(start, end, freq="M")]
    total_data = []
    for month in month_range:
        total_data.extend(get_fuel_costs_month(month))
    df = pd.DataFrame(total_data)
    df["cost-per-btu"] = pd.to_numeric(df["cost-per-btu"]).replace(0, np.nan)
    df.dropna(subset="cost-per-btu", inplace=True)
    pivot = pd.pivot_table(
        df, index="period", values="cost-per-btu", columns="fueltypeid"
    )
    pivot = (
        pd.DataFrame(index=month_range)
        .merge(pivot, how="left", left_index=True, right_index=True)
        .interpolate()
    )
    return pivot


def get_eia_unit_generation(start: str, end: str, plant_ids) -> pd.DataFrame:
    data = []
    url = "https://api.eia.gov/v2/electricity/facility-fuel/data/"
    offset: int = 0
    total: int = 0

    while offset == 0 or offset < total:
        r = requests.get(
            url,
            headers={
                "x-params": build_params_generations(
                    start=start, end=end, plant_ids=plant_ids, offset=offset
                )
            },
            params={"api_key": EIA_API_KEY},
        )
        if r.status_code == 200:
            total = int(r.json()["response"]["total"])
            data.extend(r.json()["response"]["data"])
            offset += 5000
        elif r.status_code == 409:
            print("Waiting 5 Seconds Before Next Request", r.json())
            sleep(5)
        else:
            raise ConnectionError("Issue with request", r.json())
    return pd.DataFrame(data)


def get_battery_efficiency(start: str, end: str):
    url = f"https://api.eia.gov/v2/electricity/facility-fuel/data/?facets[primeMover][]=BA&frequency=monthly&data[0]=consumption-for-eg&data[1]=gross-generation&facets[state][]=TX&facets[fuel2002][]=MWH&start={start}&end={end}&sort[0][column]=period&sort[0][direction]=desc&offset=0&length=5000"
    r = requests.get(url, params={"api_key": EIA_API_KEY})
    df = pd.DataFrame(r.json()["response"]["data"])
    df["gross-generation"] = pd.to_numeric(df["gross-generation"])
    df["consumption-for-eg"] = pd.to_numeric(df["consumption-for-eg"])
    summed = df.groupby("period")[["gross-generation", "consumption-for-eg"]].sum()
    summed["efficiency"] = (
        summed["gross-generation"] / summed["consumption-for-eg"]
    ) * 100
    return summed
