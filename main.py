import datetime
import math
import os
from os.path import isfile
from typing import Optional

import pypsa
import pandas as pd
import requests
from dotenv import load_dotenv
from matplotlib import pyplot as plt

from eia_data import get_eia_unit_generation, get_eia_unit_data, get_fuel_costs, get_battery_efficiency
from ercot_data import get_all_ercot_data

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")
CEMS_API_KEY = os.getenv("CEMS_API_KEY")

NETWORK_START = "2021-01"
NETWORK_END = "2023-12"
ROUND_TRIP_EFFICIENCY = .8


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


def build_heatrates_plant(start, end, plant_ids) -> pd.Series:
    gen = get_eia_unit_generation(start, end, plant_ids)
    gen["plantCode"] = gen["plantCode"].astype(pd.Int32Dtype())
    gen[["total-consumption-btu", "generation"]] = gen[
        ["total-consumption-btu", "generation"]
    ].astype(float)
    grouped = gen.groupby("plantCode")[["total-consumption-btu", "generation"]].sum()
    heat_rate = grouped["total-consumption-btu"] / grouped["generation"]
    heat_rate.name = "heatRate"
    return heat_rate


def build_generators(start, end) -> pd.DataFrame:
    units = get_eia_unit_data(start, end)
    units["period"] = pd.to_datetime(units["period"])

    # filter units to just operating units
    units = units[units["statusDescription"] == "Operating"]
    units = units.loc[units.groupby(["plantid", "generatorid"])["period"].idxmax()]
    try:
        county_to_zone = pd.read_csv("zone_to_county.csv", index_col="county")
    except FileNotFoundError:
        raise RuntimeError(
            "Cannot run without zone_to_county.csv, please make sure it is available on the path"
        )
    units = units.merge(county_to_zone, how="left", on="county")
    units["nameplate-capacity-mw"] = pd.to_numeric(
        units["nameplate-capacity-mw"], errors="coerce"
    )

    units["last_op_month"] = pd.to_datetime(units["period"])
    units["first_op_month"] = pd.to_datetime(units["operating-year-month"])

    heatrates = build_heatrates_plant(start, end, units["plantid"].unique().astype(str))
    units = units.merge(
        heatrates,
        left_on="plantid",
        right_on="plantCode",
        how="left",
    )
    return units


def td(date):
    return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def build_network(start: str, end: str) -> pypsa.Network:
    # load local CSV files
    try:
        assumptions = pd.read_csv("technology_assumptions.csv", index_col="technology")
        lines = pd.read_csv("transmission_lines.csv")
        zones = pd.read_csv("weather_zones.csv", index_col="ZONE")
    except FileNotFoundError:
        raise RuntimeError(
            "Cannot run without technology_assumptions.csv, transmission_lines.csv, and weather_zones.csv please make sure it is available on the path"
        )

    network = pypsa.Network()
    generators = build_generators(start, end)

    load_data, renewable_caps = get_all_ercot_data()

    network.snapshots = load_data.index

    default_heat_rates = generators.groupby("technology")["heatRate"].mean().dropna()
    # https://www.eia.gov/electricity/annual/html/epa_08_02.html
    default_heat_rates["Natural Gas Internal Combustion Engine"] = 8.894
    default_heat_rates["Landfill Gas"] = 11.030
    default_heat_rates["Other Waste Biomass"] = 11.030
    default_heat_rates["Petroleum Coke"] = 10.026
    # mostly waste heat
    default_heat_rates["All Other"] = 11.030

    fuel_prices = get_fuel_costs(network.snapshots.min(), network.snapshots.max())

    for zone, (lat, lon) in zones.iterrows():
        network.add("Bus", x=lon, y=lat, v_nom=345000, name=zone)

    for load in zones.index:
        network.add(
            "Load",
            name=load + "L",
            bus=load,
            p_set=load_data[load].values,
        )

    for _, (START, END, TTC) in lines.iterrows():
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
                carrier=assumptions.loc[unit["technology"], "carrier"],
                # assumes round trip should be around .81
                efficiency_store=math.sqrt(ROUND_TRIP_EFFICIENCY),
                efficiency_dispatch=math.sqrt(ROUND_TRIP_EFFICIENCY),
                marginal_cost=assumptions.loc[unit["technology"], "default_bid"],
            )
        else:
            if unit["technology"] in (
                "Solar Photovoltaic",
                "Onshore Wind Turbine",
                "Conventional Hydroelectric",
            ):
                all_caps.append(
                    pd.Series(
                        renewable_caps[unit["technology"]],
                        name=unit_name,
                        index=network.snapshots,
                    )
                )
                all_bids.append(
                    pd.Series(
                        assumptions.loc[unit["technology"], "default_bid"],
                        name=unit_name,
                        index=network.snapshots,
                    )
                )
                network.add(
                    "Generator",
                    name=unit_name,
                    bus=unit["weather_zone"],
                    p_nom=unit["nameplate-capacity-mw"],
                    carrier=assumptions.loc[unit["technology"], "carrier"],
                    type=unit["technology"],
                )
            else:
                if "Nuclear" in unit["technology"]:
                    # we consider nuclear to be base load, and will always run
                    all_bids.append(
                        pd.Series(
                            assumptions.loc[unit["technology"], "default_bid"],
                            name=unit_name,
                            index=network.snapshots,
                        )
                    )
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier=assumptions.loc[unit["technology"], "carrier"],
                        type=unit["technology"],
                    )
                elif "Landfill Gas" in unit["technology"]:
                    all_bids.append(
                        pd.Series(
                            assumptions.loc[unit["technology"], "default_bid"],
                            name=unit_name,
                            index=network.snapshots,
                        )
                    )
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier=assumptions.loc[unit["technology"], "carrier"],
                        type=unit["technology"],
                    )
                else:
                    network.add(
                        "Generator",
                        name=unit_name,
                        bus=unit["weather_zone"],
                        p_nom=unit["nameplate-capacity-mw"],
                        carrier=assumptions.loc[unit["technology"], "carrier"],
                        type=unit["technology"],
                        ramp_limit_up=float(
                            assumptions.loc[unit["technology"], "ramp_up_limit"]
                        ),
                        ramp_limit_down=float(
                            assumptions.loc[unit["technology"], "ramp_down_limit"]
                        ),
                        start_up_cost=float(
                            assumptions.loc[unit["technology"], "start_up_cost"]
                        ),
                        min_up_time=float(
                            assumptions.loc[unit["technology"], "min_up_time"]
                        ),
                        committable=True,
                    )

                    heat_rate = (
                        default_heat_rates[unit["technology"]]
                        if math.isnan(unit["heatRate"])
                        else unit["heatRate"]
                    )

                    bids = []
                    caps = []

                    for month, snapshot_chunk in network.snapshots.to_series().groupby(
                        pd.Grouper(freq="M")
                    ):
                        fuel_index = f"{month.year}-{month.month:02}"

                        if (
                            td(unit["first_op_month"])
                            <= td(month)
                            <= td(unit["last_op_month"])
                        ):
                            operating = 1
                            try:
                                bid = (
                                    fuel_prices.loc[
                                        fuel_index, unit["energy_source_code"]
                                    ]
                                    * heat_rate
                                ) + float(assumptions.loc[unit["technology"], "vom"])

                            except KeyError:
                                print(
                                    f"No Fuel Price For {unit['energy_source_code']} in {fuel_index} using default"
                                )
                                bid = assumptions.loc[unit["technology"], "default_bid"]
                        else:
                            print(f"Unit {unit_name} not operating in {fuel_index}")
                            bid = 0
                            operating = 0

                        caps.extend([operating] * snapshot_chunk.size)
                        bids.extend([bid] * snapshot_chunk.size)

                    all_bids.append(
                        pd.Series(bids, name=unit_name, index=network.snapshots)
                    )
                    all_caps.append(
                        pd.Series(caps, name=unit_name, index=network.snapshots)
                    )

    network.import_series_from_dataframe(
        pd.concat(all_bids, axis=1), "Generator", "marginal_cost"
    )

    network.import_series_from_dataframe(
        pd.concat(all_caps, axis=1), "Generator", "p_max_pu"
    )
    network.consistency_check()
    return network


def analyze_network(
    start: str,
    end: str,
    network_path: Optional[str] = None,
    committable: bool = False,
    set_size: int = 7 * 24,
    overlap: int = 2,
):
    """
    Analyzes a network
    :param network_path: path to reference for network loading
    :param start: date to start simulation format: YEAR-MONTH-DAY ex: '2021-05-02'
    :param end: date to start simulation format: YEAR-MONTH-DAY ex: '2021-05-02'
    :param committable: whether to allow generators to be committable
    :param set_size: integer size of chunk to simulate, set to zero for no chunking
    :param overlap: integer size of chunk overlap, set to zero for no overlap
    """
    if network_path is not None and isfile(network_path):
        network = pypsa.Network()
        network.import_from_netcdf(path=network_path)
    else:
        print(
            f"Failed to import network, building from scratch from {NETWORK_START} to {NETWORK_END}"
        )
        network = build_network(NETWORK_START, NETWORK_END)
        print("Built network, exporting as network.nc")
        network.export_to_netcdf("network.nc")

    if not committable:
        network.generators.committable = False
        print("Generators are not committable for this simulation")
    else:
        print(
            "Generators are committable, this will slow down simulation significantly"
        )

    start_sim = datetime.datetime.strptime(start, "%Y-%m-%d")
    end_sim = datetime.datetime.strptime(end, "%Y-%m-%d").replace(hour=23)
    simulation_snapshots = network.snapshots[
        network.snapshots.to_series().between(start_sim, end_sim)
    ]

    if set_size > 0:
        # simulate the chunks
        for i in range(len(simulation_snapshots) // set_size):
            chunk = simulation_snapshots[i * set_size : (i + 1) * set_size + overlap]
            print(f"Simulating {chunk[0]} to {chunk[-1]} with length {len(chunk)}")
            network.optimize(chunk, solver_name="highs")

        # simulate any extra snapshots not caught in chunks
        if len(simulation_snapshots) % set_size != 0:
            chunk = simulation_snapshots[-(len(simulation_snapshots) % set_size) :]
            print(
                f"Simulating extra chunk from {chunk[0]} to {chunk[-1]} with length {len(chunk)}"
            )
            network.optimize(chunk, solver_name="highs")
    else:
        network.optimize(simulation_snapshots, solver_name="highs")

    generation = network.generators_t.p.loc[simulation_snapshots]

    grouped = generation.T.groupby(by=network.generators["carrier"]).sum().T
    grouped["storage"] = network.storage_units_t.p.sum(axis=1).clip(lower=0)
    grouped.plot.area(
        xlabel="Hour",
        ylabel="Load (MW)",
        title=f"ERCOT Dispatch from {network.snapshots.min():%H:00 %m-%d-%Y} to {network.snapshots.max():%H:00 %m-%d-%Y}",
    )

    plt.legend(title="Fuel Type")
    plt.show()

    battery_gen = network.storage_units_t.p.loc[simulation_snapshots]
    battery_gen.sum(axis=1).head(24 * 7).plot(
        title="Net Battery Charge", ylabel="Net Charge MWs"
    )
    plt.show()

    if not committable:
        prices = network.buses_t.marginal_price.loc[simulation_snapshots]
        prices.plot(
            xlabel="Date",
            ylabel="Price ($/MWH)",
            title="Zonal Price for ERCOT Dispatch",
        )
        plt.show()
    else:
        print("No price output when the network has committable elements")


def compare_fuel_mix():
    actual = pd.read_csv("2022_fuel_mix.csv", index_col="hour_ending").head(3 * 24)
    simulated = pd.read_csv("2022_jan_sim_plants.csv", index_col="snapshot")
    sum_merged = pd.concat(
        [actual.sum(axis=1), simulated.sum(axis=1)], join="inner", axis=1
    )
    sum_merged.plot()
    plt.show()
    actual.sub(simulated).dropna(axis=1).head(72).plot()
    plt.show()


if __name__ == "__main__":
    analyze_network(
        network_path="network.nc",
        start="2022-01-01",
        end="2022-01-07",
        committable=False,
        set_size=48,
        overlap=2,
    )
