import math
import os

import pypsa
import pandas as pd
import requests
from dotenv import load_dotenv
from matplotlib import pyplot as plt

from eia_data import get_eia_unit_generation, get_eia_unit_data, get_fuel_costs
from ercot_data import get_fuel_mix_data, get_eroct_load_data

load_dotenv()

EIA_API_KEY = os.getenv("EIA_API_KEY")
CEMS_API_KEY = os.getenv("CEMS_API_KEY")


def get_renewable_gen(n_shots: pd.Series) -> dict[str, pd.Series]:
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

    # refactor this to be less brittle
    # cache this
    # only works for 2022
    hydro_gen = get_fuel_mix_data()
    hydro_gen.index = pd.to_datetime(hydro_gen.index)
    hydro_gen = hydro_gen[hydro_gen.index.isin(n_shots)]

    caps = {
        "Solar Photovoltaic": solar["Solar Output, % of Installed"] / 100,
        "Onshore Wind Turbine": wind["Wind Output, % of Installed"] / 100,
        "Conventional Hydroelectric": hydro_gen["hydro"] / hydro_gen["hydro"].max(),
    }

    return caps


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


def build_heatrates_plant(year, plant_ids) -> pd.DataFrame:
    gen = get_eia_unit_generation(year, plant_ids)
    gen["heatRate"] = gen["total-consumption-btu"].astype(float) / gen[
        "generation"
    ].astype(float)
    gen["plantCode"] = gen["plantCode"].astype(pd.Int32Dtype())
    return gen


def build_generators(year) -> pd.DataFrame:
    units = get_eia_unit_data(year, last=True)
    try:
        county_to_zone = pd.read_csv("zone_to_county.csv", index_col="county")
    except FileNotFoundError:
        raise RuntimeError(
            "Cannot run without zone_to_county.csv, please make sure it is available on the path"
        )
    units = units.merge(county_to_zone, how="left", on="county")
    heatrates = build_heatrates_plant(year, units["plantid"].unique().astype(str))
    units = units.merge(
        heatrates,
        left_on="plantid",
        right_on="plantCode",
        how="left",
    )
    return units


def build_network(year: int, n_shots: int, committable: bool = False) -> pypsa.Network:
    # load local CSV files
    try:
        assumptions = pd.read_csv("technology_assumptions.csv", index_col="technology")
    except FileNotFoundError:
        raise RuntimeError(
            "Cannot run without technology_assumptions.csv, please make sure it is available on the path"
        )

    try:
        lines = pd.read_csv("transmission_lines.csv")
    except FileNotFoundError:
        raise RuntimeError(
            "Cannot run without transmission_lines.csv, please make sure it is available on the path"
        )

    try:
        zones = pd.read_csv("weather_zones.csv", index_col="ZONE")
    except FileNotFoundError:
        raise RuntimeError(
            "Cannot run without weather_zones.csv, please make sure it is available on the path"
        )

    network = pypsa.Network()
    # this needs to be cached
    generators = build_generators(year)
    generators.to_csv("gen.csv")
    generators["nameplate-capacity-mw"] = pd.to_numeric(
        generators["nameplate-capacity-mw"], errors="coerce"
    )

    load_data = get_eroct_load_data(year)

    network.snapshots = load_data.head(n_shots).index
    renewable_caps = get_renewable_gen(network.snapshots)

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

    for zone, (lat, lon) in zones.iterrows():
        network.add("Bus", x=lon, y=lat, v_nom=345000, name=zone)

    for load in zones.index:
        network.add(
            "Load",
            name=load + "L",
            bus=load,
            p_set=load_data[load].head(n_shots).values,
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
                efficiency_store=0.9,
                efficiency_dispatch=0.9,
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
                all_bids.append(pd.Series(-20, name=unit_name, index=network.snapshots))
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
                        pd.Series(0, name=unit_name, index=network.snapshots)
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
                    # we currently consider landfill gas to be base load and will always run
                    all_bids.append(
                        pd.Series(0, name=unit_name, index=network.snapshots)
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
                        committable=committable,
                    )

                    heat_rate = (
                        default_heat_rates[unit["technology"]]
                        if math.isnan(unit["heatRate"])
                        else unit["heatRate"]
                    )

                    bids = []

                    for month, snapshot_chunk in network.snapshots.to_series().groupby(
                        pd.Grouper(freq="M")
                    ):
                        fuel_index = f"{month.year}-{month.month:02}"
                        try:
                            bid = (
                                fuel_prices.loc[fuel_index, unit["energy_source_code"]]
                                * heat_rate
                            ) + float(assumptions.loc[unit["technology"], "vom"])
                        except KeyError:
                            print(
                                f"No Fuel Price For {unit['energy_source_code']} in {fuel_index}"
                            )
                            bid = 0
                        bids.extend([bid] * snapshot_chunk.size)

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


def analyze_network(
    year: int,
    n_shots: int,
    committable: bool = False,
    set_size: int = 7 * 24,
    overlap: int = 2,
):
    network = build_network(year, n_shots, committable)
    # simulate the chunks
    for i in range(n_shots // set_size):
        chunk = network.snapshots[i * set_size : (i + 1) * set_size + overlap]
        print(f"Simulating {chunk[0]} to {chunk[-1]}")
        network.optimize(chunk, solver_name="highs")

    # simulate any extra snapshots not caught in chunks
    if n_shots % set_size != 0:
        chunk = network.snapshots[n_shots % set_size :]
        print(f"Simulating {chunk[0]} to {chunk[-1]}")
        network.optimize(chunk, solver_name="highs")

    grouped = network.generators_t.p.T.groupby(by=network.generators["carrier"]).sum().T
    grouped["storage"] = network.storage_units_t.p.sum(axis=1).clip(lower=0)
    grouped.plot.area(
        xlabel="Hour",
        ylabel="Load (MW)",
        title=f"ERCOT Dispatch from {network.snapshots.min():%H:00 %m-%d-%Y} to {network.snapshots.max():%H:00 %m-%d-%Y}",
    )

    grouped.to_csv("2022_jan_sim_plants.csv")
    plt.legend(title="Fuel Type")
    plt.show()

    network.storage_units_t.p.sum(axis=1).head(24 * 7).plot(
        title="Net Battery Charge", ylabel="Net Charge MWs"
    )
    plt.show()

    if not committable:
        network.buses_t.marginal_price.plot(
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
    # compare_fuel_mix()
    analyze_network(2022, 3 * 24, committable=False, set_size=3 * 24, overlap=0)
