import os
from time import sleep
from typing import List, Tuple

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


def build_params_fuels(year: str, offset: int) -> str:
    """
    builds x-params for eia fuels api call
    :param year: year to get data
    :param offset: integer offset for pagination
    :return: x-params as a string
    """
    return (
        '{ "frequency": "monthly", "data": [ "cost-per-btu" ], "facets": { "location": [ "TX" ] }, "start": "'
        + year
        + '-01", "end": "'
        + year
        + '-12", "sort": [ { "column": "period", "direction": "desc" } ], "offset": '
        + str(offset)
        + ', "length": 5000 }'
    )


def build_params_generations(year: str, plant_ids: List[str], offset: int) -> str:
    """
    builds x-params for eia fuels api call
    :param year: year to get data
    :param plant_ids: EIA plant IDs to retrieve data for
    :param offset: integer offset for pagination
    :return: x-params as a string
    """
    return (
        '{ "frequency": "annual", "data": [ "total-consumption-btu", "generation" ], "facets": { "primeMover": ["ALL"], "fuel2002": ["ALL"], "plantCode": [ "'
        + '", "'.join(plant_ids)
        + '" ] }, "start": "'
        + year
        + '-01", "end": "'
        + year
        + '-12", "sort": [ { "column": "period", "direction": "desc" } ], "offset": '
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


def get_eia_unit_data(year: int, last=False) -> pd.DataFrame:
    data = []
    url = "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
    offset: int = 0
    total: int = 0
    year_month = str(year) + "-12"
    latest_year, end = get_eia_unit_capacity_bounds()
    if latest_year == year:
        year_month = end
    elif year > latest_year:
        raise ValueError(f"EIA API has no data for {year}")

    while offset == 0 or offset < total:
        r = requests.get(
            url,
            headers={
                "x-params": build_params_units(
                    year_month if last else f"{year}-01", year_month, offset
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
    total_data = pd.DataFrame(data)
    return total_data.astype({"plantid": pd.Int32Dtype()})


def get_fuel_costs(year: int) -> pd.DataFrame:
    data = []
    url = "https://api.eia.gov/v2/electricity/electric-power-operational-data/data/"
    offset: int = 0
    total: int = 0

    while offset == 0 or offset < total:
        r = requests.get(
            url,
            headers={"x-params": build_params_fuels(str(year), offset)},
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
    costs = (
        pd.DataFrame(data)
        .replace(to_replace=0, value=np.nan)
        .dropna()
        .astype({"cost-per-btu": float})
    )
    return costs.pivot_table(
        index="period", columns="fueltypeid", values="cost-per-btu", aggfunc="mean"
    )


def get_eia_unit_generation(year: int, plant_ids) -> pd.DataFrame:
    data = []
    url = "https://api.eia.gov/v2/electricity/facility-fuel/data/"
    offset: int = 0
    total: int = 0

    while offset == 0 or offset < total:
        r = requests.get(
            url,
            headers={
                "x-params": build_params_generations(
                    year=str(year), plant_ids=plant_ids, offset=offset
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
