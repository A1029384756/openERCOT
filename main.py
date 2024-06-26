import datetime
import math
import argparse
import os
import errno
from os.path import isfile

import pypsa
import pandas as pd
from dotenv import load_dotenv
from matplotlib import pyplot as plt
import mplcatppuccin

from eia_data import get_eia_unit_generation, get_eia_unit_data, get_fuel_costs

from ercot_data import get_all_ercot_data
from network_map import plot_network, plot_year
from scenario import Scenario
from utils import render_graph, load_scenario

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")

NETWORK_START = "2021-01"
NETWORK_END = "2023-12"
ROUND_TRIP_EFFICIENCY = 0.8


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


def analyze_network(scenario: Scenario):
    """
    Analyzes a network
    :param scenario: a scenario object that holds important simulation info
    """
    network_path = scenario["io_params"]["network_path"]
    if network_path is not None and isfile(network_path):
        network = pypsa.Network()
        network.import_from_netcdf(path=network_path)
    else:
        print(
            f"Failed to import network, building from scratch from {NETWORK_START} to {NETWORK_END}"
        )
        network = build_network(NETWORK_START, NETWORK_END)
        print(f"Built network, exporting as {network_path}")
        network.export_to_netcdf(network_path)

    plot_network(scenario, network)

    if not scenario["simulation_params"]["committable"]:
        network.generators.committable = False
        print("Generators are not committable for this simulation")
    else:
        print(
            "Generators are committable, this will slow down simulation significantly"
        )

    start_sim = datetime.datetime.strptime(
        scenario["simulation_params"]["start_date"], "%Y-%m-%d"
    )
    end_sim = datetime.datetime.strptime(
        scenario["simulation_params"]["end_date"], "%Y-%m-%d"
    ).replace(hour=23)
    simulation_snapshots = network.snapshots[
        network.snapshots.to_series().between(start_sim, end_sim)
    ]

    set_size = scenario["simulation_params"]["set_size"]
    overlap = scenario["simulation_params"]["overlap"]
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

    out_dir = scenario.get("out_dir")
    if out_dir is not None:
        network.export_to_netcdf(f"{out_dir}output-network.nc")

    generation = network.generators_t.p.loc[simulation_snapshots]

    grouped = generation.T.groupby(by=network.generators["carrier"]).sum().T
    grouped["storage"] = network.storage_units_t.p.sum(axis=1).clip(lower=0)
    grouped.plot.area(
        xlabel="Hour",
        ylabel="Load (MW)",
        title=f"ERCOT Dispatch from {network.snapshots.min():%H:00 %m-%d-%Y} to {network.snapshots.max():%H:00 %m-%d-%Y}",
    )

    plt.legend(title="Fuel Type")
    render_graph(
        scenario,
        f"ERCOT Dispatch from {network.snapshots.min():%H:00 %m-%d-%Y} to {network.snapshots.max():%H:00 %m-%d-%Y}",
    )

    battery_gen = network.storage_units_t.p.loc[simulation_snapshots]
    battery_gen.sum(axis=1).head(24 * 7).plot(
        title="Net Battery Charge", ylabel="Net Charge MWs"
    )
    render_graph(scenario, "Net Battery Charge")

    if not scenario["simulation_params"]["committable"]:
        prices = network.buses_t.marginal_price.loc[simulation_snapshots]
        prices.plot(
            xlabel="Date",
            ylabel="Price ($/MWH)",
            title="Zonal Price for ERCOT Dispatch",
        )
        render_graph(scenario, "Zonal Price for ERCOT Dispatch")
    else:
        print("No price output when the network has committable elements")


def compare_fuel_mix(scenario: Scenario):
    actual = pd.read_csv("2022_fuel_mix.csv", index_col="hour_ending").head(3 * 24)
    simulated = pd.read_csv("2022_jan_sim_plants.csv", index_col="snapshot")
    sum_merged = pd.concat(
        [actual.sum(axis=1), simulated.sum(axis=1)], join="inner", axis=1
    )
    sum_merged.plot()
    render_graph(scenario, "Sub Merged 2022 Fuel Mix")
    actual.sub(simulated).dropna(axis=1).head(72).plot()
    render_graph(scenario, "Actual 2022 Fuel Mix")


if __name__ == "__main__":
    plt.style.use("mocha")
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario")
    args, leftovers = parser.parse_known_args()

    if args.scenario is None:
        print("Please provide a scenario to simulate like so:")
        print("python ./main.py --scenario <path to scenario toml>")
        exit(os.EX_NOINPUT)

    scenario = load_scenario(args.scenario)

    out_dir = f"{os.getcwd()}/outputs-{scenario['simulation_params']['start_date']}-{scenario['simulation_params']['end_date']}/"
    try:
        os.makedirs(out_dir)
    except OSError as e:
        if e.errno == errno.EEXIST and os.path.isdir(out_dir):
            pass
        else:
            raise
    scenario["out_dir"] = out_dir

    analyze_network(scenario)
    exit(os.EX_OK)
