import math
import os
from typing import Tuple, List

import numpy as np
import pandas
import pypsa
import pandas as pd
import requests
from dotenv import load_dotenv
from matplotlib import pyplot as plt
from io import BytesIO
from zipfile import ZipFile

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")
CEMS_API_KEY = os.getenv("CEMS_API_KEY")

WEATHER_ZONES = {
    "FAR WEST": (32.000507, -102.077408),
    "NORTH": (33.930828, -98.484879),
    "WEST": (32.448734, -99.733147),
    "NORTH CENTRAL": (32.897480, -97.040443),
    "EAST": (32.349998, -95.300003),
    "SOUTH CENTRAL": (29.424349, -98.491142),
    "SOUTH": (27.80058, -97.39638),
    "COAST": (29.749907, -95.358421),
}

ZONE_NAME_MAP = {
    "FWEST": "FAR WEST",
    "NCENT": "NORTH CENTRAL",
    "SCENT": "SOUTH CENTRAL",
}

TRANSMISSION_LINES = [
    ("SOUTH", "SOUTH CENTRAL", 2000),
    ("SOUTH", "COAST", 700),
    ("SOUTH CENTRAL", "COAST", 2000),
    ("EAST", "COAST", 2000),
    ("SOUTH CENTRAL", "NORTH CENTRAL", 3000),
    ("NORTH CENTRAL", "EAST", 4000),
    ("NORTH", "NORTH CENTRAL", 3000),
    ("NORTH", "WEST", 3000),
    ("FAR WEST", "WEST", 2000),
    ("FAR WEST", "SOUTH CENTRAL", 1500),
    ("SOUTH CENTRAL", "WEST", 1000),
    ("EAST", "SOUTH CENTRAL", 2000),
    ("NORTH CENTRAL", "WEST", 3000),
]

# allows the comparison of ERCOT fuel mix and simulation output
TECHNOLOGY_MAP = {
    "Wood/Wood Waste Biomass": "biomass",
    "Petroleum Liquids": "other",
    "Petroleum Coke": "coal",
    "Other Waste Biomass": "other",
    "Natural Gas Fired Combined Cycle": "gascc",
    "Natural Gas Fired Combustion Turbine": "gas",
    "Natural Gas Internal Combustion Engine": "gas",
    "Natural Gas Steam Turbine": "gas",
    "Landfill Gas": "gas",
    "Conventional Steam Coal": "coal",
    "All Other": "other",
    "WIND": "wind",
    "NUCLEAR": "nuclear",
    "LANDFILL GAS": "other",
    "SOLAR": "solar"
}


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
    return '{ "frequency": "annual", "data": [ "total-consumption-btu", "generation" ], "facets": { "primeMover": ["ALL"], "fuel2002": ["ALL"], "plantCode": [ "' + '", "'.join(
        plant_ids) + '" ] }, "start": "' + year + '-01", "end": "' + year + '-12", "sort": [ { "column": "period", "direction": "desc" } ], "offset": ' + str(
        offset) + ', "length": 5000 }'


def get_eia_units_status(year: int) -> pandas.DataFrame:
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


def get_eia_unit_bounds() -> Tuple[int, str]:
    url = "https://api.eia.gov/v2/electricity/operating-generator-capacity/"
    r = requests.get(url, params={"api_key": EIA_API_KEY})
    end = r.json()["response"]["endPeriod"]
    return int(end[0:4]), end


def get_eia_unit_data(year: int, last=False):
    data = []
    url = "https://api.eia.gov/v2/electricity/operating-generator-capacity/data/"
    offset: int = 0
    total: int = 0
    year_month = str(year) + "-12"
    latest_year, end = get_eia_unit_bounds()
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
        total = int(r.json()["response"]["total"])
        data.extend(r.json()["response"]["data"])
        offset += 5000
    total_data = pd.DataFrame(data)
    return total_data.astype({"plantid": pd.Int32Dtype()})


def get_renewable_gen(n_shots: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """
    finds the renewable generation for ERCOT in a percentage of installed capacity
    :param n_shots: takes a series of snapshots to find generation for
    :return: returns a tuple with the solar and wind percentage generation
    """
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
    solar = solar[solar.index.isin(n_shots)]
    wind = wind[wind.index.isin(n_shots)]
    return solar["Solar Output, % of Installed"] / 100, wind[
        "Wind Output, % of Installed"
    ] / 100


def build_crosswalk() -> pd.DataFrame:
    cross_url = "https://raw.githubusercontent.com/USEPA/camd-eia-crosswalk/master/epa_eia_crosswalk.csv"
    crosswalk = pd.read_csv(
        cross_url,
        dtype={"EIA_PLANT_ID": pd.Int32Dtype(), "CAMD_PLANT_ID": pd.Int32Dtype()},
    )
    crosswalk = crosswalk[crosswalk["CAMD_STATE"] == "TX"]
    crosswalk = crosswalk[
        ["EIA_PLANT_ID", "EIA_GENERATOR_ID", "CAMD_PLANT_ID", "CAMD_UNIT_ID"]
    ]
    crosswalk.dropna(inplace=True)
    return crosswalk


def get_cems_data(year: int) -> pd.DataFrame:
    headers = {
        "accept": "application/json",
        "x-api-key": CEMS_API_KEY,
    }

    params = {
        "stateCode": "TX",
        "year": year,
        "page": "1",
        "perPage": "500",
    }

    response = requests.get(
        "https://api.epa.gov/easey/emissions-mgmt/emissions/apportioned/annual",
        params=params,
        headers=headers,
    )

    df = pd.DataFrame(response.json())
    return df


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
        total = int(r.json()["response"]["total"])
        data.extend(r.json()["response"]["data"])
        offset += 5000
    costs = pd.DataFrame(data).replace(to_replace=0, value=np.nan).dropna().astype({"cost-per-btu": float})
    return costs.pivot_table(
        index="period", columns="fueltypeid", values="cost-per-btu", aggfunc="mean"
    )


def build_heatrates_unit(year) -> pd.DataFrame:
    cross = build_crosswalk()
    cems = get_cems_data(year)
    merged = cems.merge(
        cross,
        left_on=["facilityId", "unitId"],
        right_on=["CAMD_PLANT_ID", "CAMD_UNIT_ID"],
        how="inner",
    )
    merged["heatRate"] = merged["heatInput"] / merged["grossLoad"]
    merged = merged[~merged["heatRate"].isna()]
    merged.drop_duplicates(subset=["EIA_PLANT_ID", "EIA_GENERATOR_ID"], inplace=True)
    return merged[["EIA_PLANT_ID", "EIA_GENERATOR_ID", "heatRate"]]


def get_eia_unit_generation(year: int, plant_ids) -> pd.DataFrame:
    data = []
    url = "https://api.eia.gov/v2/electricity/facility-fuel/data/"
    offset: int = 0
    total: int = 0

    while offset == 0 or offset < total:
        r = requests.get(
            url,
            headers={"x-params": build_params_generations(year=str(year), plant_ids=plant_ids, offset=offset)},
            params={"api_key": EIA_API_KEY},
        )
        total = int(r.json()["response"]["total"])
        data.extend(r.json()["response"]["data"])
        offset += 5000
    return pd.DataFrame(data)


def build_heatrates_plant(year, plant_ids) -> pd.DataFrame:
    gen = get_eia_unit_generation(year, plant_ids)
    gen["heatRate"] = gen["total-consumption-btu"].astype(float) / gen["generation"].astype(float)
    gen["plantCode"] = gen["plantCode"].astype(pd.Int32Dtype())
    return gen


def build_generators(year) -> pd.DataFrame:
    units = get_eia_unit_data(year, last=True)
    county_to_zone = pd.read_csv("zone_to_county.csv", index_col="county")
    units = units.merge(county_to_zone, how="left", on="county")
    heatrates = build_heatrates_plant(year, units["plantid"].unique().astype(str))
    units = units.merge(
        heatrates,
        left_on="plantid", right_on="plantCode",
        how="left",
    )
    return units


def build_network(year: int, n_shots: int) -> pypsa.Network:
    network = pypsa.Network()
    # this needs to be cached
    generators = build_generators(year)
    generators.to_csv("gen.csv")
    generators["nameplate-capacity-mw"] = pd.to_numeric(
        generators["nameplate-capacity-mw"], errors="coerce"
    )
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
    load_data.index = load_data.index.map(lambda x: x + pd.Timedelta(1, 'D') if x.hour == 0 else x)

    network.snapshots = load_data.head(n_shots).index
    solar_cap, wind_cap = get_renewable_gen(network.snapshots)

    default_heat_rates = generators.groupby("technology")["heatRate"].mean().dropna()
    # https://www.eia.gov/electricity/annual/html/epa_08_02.html
    default_heat_rates["Natural Gas Internal Combustion Engine"] = 8.894
    default_heat_rates["Landfill Gas"] = 11.030
    default_heat_rates["Other Waste Biomass"] = 11.030
    default_heat_rates["Petroleum Coke"] = 10.026
    # mostly waste heat
    default_heat_rates["All Other"] = 11.030

    # this is fast to generate but can be cached
    fuel_prices = get_fuel_costs(year)

    for zone, coord in WEATHER_ZONES.items():
        network.add("Bus", x=coord[1], y=coord[0], v_nom=345000, name=zone)

    for load in WEATHER_ZONES.keys():
        network.add(
            "Load", name=load + "L", bus=load, p_set=load_data[load].head(n_shots).values
        )

    for START, END, TTC in TRANSMISSION_LINES:
        network.add(
            "Link", name=START + "-" + END, bus0=START, bus1=END, p_min_pu=-1, p_nom=TTC
        )

    all_bids = []
    all_caps = []

    for index, unit in generators.iterrows():
        unit_name = str(unit["plantid"]) + "-" + str(unit["generatorid"])

        if unit["technology"] == "Batteries" or unit["technology"] == "Flywheels":
            network.add(
                "StorageUnit",
                name=unit_name,
                bus=unit["weather_zone"],
                type="Battery",
                p_nom=unit["nameplate-capacity-mw"],
                marginal_cost=500,
            )
        else:
            if unit["technology"] in (
                    "Solar Photovoltaic",
                    "Onshore Wind Turbine",
                    "Conventional Hydroelectric",
            ):
                # refactor to add this to add wind
                if "Solar" in unit["technology"]:
                    all_caps.append(
                        pd.Series(solar_cap, name=unit_name, index=network.snapshots)
                    )
                    all_bids.append(
                        pd.Series(-20, name=unit_name, index=network.snapshots)
                    )
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier="SOLAR",
                        type=unit["technology"],
                    )

                elif "Wind" in unit["technology"]:
                    all_caps.append(
                        pd.Series(wind_cap, name=unit_name, index=network.snapshots)
                    )
                    all_bids.append(
                        pd.Series(-20, name=unit_name, index=network.snapshots)
                    )
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier="WIND",
                        type=unit["technology"],
                    )
            else:
                if "Nuclear" in unit["technology"]:
                    all_bids.append(
                        pd.Series(5, name=unit_name, index=network.snapshots)
                    )
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier="NUCLEAR",
                        type=unit["technology"],
                    )
                elif "Landfill Gas" in unit["technology"]:
                    # we currently consider landfill gas to be baseload and will always run
                    all_bids.append(
                        pd.Series(0, name=unit_name, index=network.snapshots)
                    )
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier="LANDFILL GAS",
                        type=unit["technology"],
                    )
                else:
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier=TECHNOLOGY_MAP[unit["technology"]],
                        # p_min_pu=min_output,
                        type=unit["technology"],
                        # ramp_limit_up=ramp_rate,
                        # committable=True
                    )

                    heat_rate = (
                        default_heat_rates[unit["technology"]]
                        if math.isnan(unit["heatRate"])
                        else unit["heatRate"]
                    )

                    bids = []

                    # refactor to just do each month as a chunk
                    for snapshot in network.snapshots:
                        fuel_index = f"{snapshot.year}-{snapshot.month:02}"
                        try:
                            bid = (
                                    fuel_prices.loc[fuel_index, unit["energy_source_code"]]
                                    * heat_rate
                            )
                        except KeyError:
                            bid = 0
                        bids.append(bid)

                    all_bids.append(
                        pd.Series(bids, name=unit_name, index=network.snapshots)
                    )

    network.import_series_from_dataframe(
        pd.concat(all_bids, axis=1), "Generator", "marginal_cost"
    )
    network.import_series_from_dataframe(
        pd.concat(all_caps, axis=1), "Generator", "p_max_pu"
    )
    network.consistency_check()
    return network


def analyze_network(year: int, n_shots: int):
    network = build_network(year, n_shots)
    network.optimize(solver_name="highs")
    grouped = network.generators_t.p.T.groupby(by=network.generators["carrier"]).sum()
    grouped.plot.area(
        xlabel="Hour", ylabel="Load (MW)", title="ERCOT Dispatch on January 1st 2022"
    )
    grouped.T.to_csv("2022_jan_sim_plants.csv")
    plt.legend(title="Fuel Type")
    plt.show()

    network.buses_t.marginal_price.plot(xlabel="Date", ylabel="Price ($/MWH)", title="Zonal Price for ERCOT Dispatch")
    plt.show()


def compare_fuel_mix():
    actual = pd.read_csv("2022_fuel_mix.csv", index_col="hour_ending").head(31 * 24)
    simulated = pd.read_csv("2022_jan_sim.csv", index_col="snapshot")
    sum_merged = pd.concat([actual.sum(axis=1), simulated.sum(axis=1)], join="inner", axis=1)
    sum_merged.plot()
    plt.show()
    actual.sub(simulated).dropna(axis=1).head(72).plot()
    plt.show()


if __name__ == "__main__":
    compare_fuel_mix()
    # analyze_network(2022, 31 * 24)
