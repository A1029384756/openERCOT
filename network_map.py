import datetime
import io
import os

import pandas as pd
import pypsa
import requests
from dotenv import load_dotenv
from pypsa.plot import plt
import cartopy.crs as ccrs
import cartopy
import matplotlib.patches as mpatches
from dataclasses import dataclass

from scenario import Scenario
from utils import render_graph
from PIL import Image

load_dotenv()

CEMS_API_KEY = os.getenv("CEMS_API_KEY")


@dataclass
class CatppuccinLatte:
    rosewater: str = "#dc8a78"
    flamingo: str = "#dd7878"
    pink: str = "#ea76cb"
    mauve: str = "#8839ef"
    red: str = "#d20f39"
    maroon: str = "#e64553"
    peach: str = "#fe640b"
    yellow: str = "#df8e1d"
    green: str = "#40a02b"
    teal: str = "#179299"
    sky: str = "#04a5e5"
    sapphire: str = "#209fb5"
    blue: str = "#1e66f5"
    lavender: str = "#7287fd"
    text: str = "#4c4f69"
    subtext1: str = "#5c5f77"
    subtext0: str = "#6c6f85"
    overlay2: str = "#7c7f93"
    overlay1: str = "#8c8fa1"
    overlay0: str = "#9ca0b0"
    surface2: str = "#acb0be"
    surface1: str = "#bcc0cc"
    surface0: str = "#ccd0da"
    base: str = "#eff1f5"
    mantle: str = "#e6e9ef"
    crust: str = "#dce0e8"


@dataclass
class CatppuccinMocha:
    rosewater: str = "#f5e0dc"
    flamingo: str = "#f2cdcd"
    pink: str = "#f5c2e7"
    mauve: str = "#cba6f7"
    red: str = "#f38ba8"
    maroon: str = "#eba0ac"
    peach: str = "#fab387"
    yellow: str = "#f9e2af"
    green: str = "#a6e3a1"
    teal: str = "#94e2d5"
    sky: str = "#89dceb"
    sapphire: str = "#74c7ec"
    blue: str = "#89b4fa"
    lavender: str = "#b4befe"
    text: str = "#cdd6f4"
    subtext1: str = "#bac2de"
    subtext0: str = "#a6adc8"
    overlay2: str = "#9399b2"
    overlay1: str = "#7f849c"
    overlay0: str = "#6c7086"
    surface2: str = "#585b70"
    surface1: str = "#45475a"
    surface0: str = "#313244"
    base: str = "#1e1e2e"
    mantle: str = "#181825"
    crust: str = "#11111b"


def draw_map_cartopy(ax):
    resolution = "50m"

    ax.add_feature(
        cartopy.feature.LAND.with_scale(resolution),
        facecolor=CatppuccinMocha.base,
    )

    ax.add_feature(
        cartopy.feature.OCEAN.with_scale(resolution),
        facecolor=CatppuccinMocha.blue,
    )

    ax.add_feature(
        cartopy.feature.STATES.with_scale(resolution),
        linewidth=0.5,
        edgecolor=CatppuccinMocha.overlay0,
    )

    ax.add_feature(
        cartopy.feature.BORDERS.with_scale(resolution),
        linewidth=0.7,
        color=CatppuccinMocha.overlay1,
    )

    ax.add_feature(
        cartopy.feature.COASTLINE.with_scale(resolution),
        linewidth=0.9,
        color=CatppuccinMocha.overlay2,
    )


def plot_network(scenario: Scenario, network: pypsa.Network):
    _, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    draw_map_cartopy(ax)

    network = pypsa.Network()
    network.import_from_netcdf(path="network.nc")
    gen = network.generators.groupby(["bus", "carrier"]).p_nom.sum()

    bus_colors = {
        "dfo": CatppuccinLatte.rosewater,
        "coal": CatppuccinLatte.flamingo,
        "gas": CatppuccinLatte.pink,
        "nuclear": CatppuccinLatte.mauve,
        "biomass": CatppuccinLatte.red,
        "solar": CatppuccinLatte.maroon,
        "wind": CatppuccinLatte.peach,
        "other": CatppuccinLatte.yellow,
        "hydro": CatppuccinLatte.green,
    }

    network.plot(
        title="openERCOT Total Nodal Generation Capacity",
        geomap=False,
        bus_sizes=gen / 5e4,
        bus_colors=bus_colors,  # type: ignore
        link_widths=1.0,
        margin=0.2,
        link_colors=CatppuccinLatte.text,
        color_geomap=False,
    )

    handles = []
    for k, v in bus_colors.items():
        lab = "DFO" if k == "dfo" else k.title()
        handles.append(mpatches.Patch(color=v, label=lab))

    ax.legend(handles=handles, loc="lower left")

    plt.tight_layout()
    render_graph(scenario, "openERCOT Total Nodal Generation Capacity")


def plot_hour(network: pypsa.Network, snapshot: datetime.datetime):
    _, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
    draw_map_cartopy(ax)

    gen = (
        network.generators.assign(g=network.generators_t.p.loc[snapshot])
        .groupby(["bus", "carrier"])
        .g.sum()
    )

    bus_colors = {
        "dfo": CatppuccinMocha.rosewater,
        "coal": CatppuccinMocha.flamingo,
        "gas": CatppuccinMocha.pink,
        "nuclear": CatppuccinMocha.mauve,
        "biomass": CatppuccinMocha.red,
        "solar": CatppuccinMocha.maroon,
        "wind": CatppuccinMocha.peach,
        "other": CatppuccinMocha.yellow,
        "hydro": CatppuccinMocha.green,
    }

    links_color = [
        CatppuccinMocha.red if link_max == abs(link) else CatppuccinMocha.text
        for link_max, link in zip(network.links.p_nom, network.links_t.p0.loc[snapshot])
    ]

    link_flow = pd.Series(
        network.links_t.p0.loc[snapshot].values, index=network.branches().index
    )

    network.plot(
        title=f"OpenERCOT Dispatch by Generator Type for {snapshot}",
        geomap=False,
        bus_sizes=gen / 5e4,
        bus_colors=bus_colors,  # type: ignore
        link_widths=1,
        margin=0.2,
        link_colors=pd.Series(index=network.links.index, data=links_color),
        color_geomap=False,
        flow=link_flow / 150,
    )

    handles = []
    for k, v in bus_colors.items():
        lab = "DFO" if k == "dfo" else k.title()
        handles.append(mpatches.Patch(color=v, label=lab))

    ax.legend(handles=handles, loc="lower left")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=300)
    buf.seek(0)
    return Image.open(buf)


def plot_day(scenario: Scenario, network: pypsa.Network, day):
    start_sim = datetime.datetime.strptime(day, "%Y-%m-%d")
    end_sim = datetime.datetime.strptime(day, "%Y-%m-%d").replace(hour=23)

    simulation_snapshots = network.snapshots[
        network.snapshots.to_series().between(start_sim, end_sim)
    ]

    img, *imgs = [plot_hour(network, s) for s in simulation_snapshots]
    out_dir = scenario.get("out_dir")
    img.save(
        fp=f"{out_dir}OpenERCOT_Dispatch_{day}.gif",
        format="GIF",
        append_images=imgs,
        save_all=True,
        duration=200,
        loop=0,
    )


def plot_year(scenario: Scenario, network: pypsa.Network, year: int):
    start_year = datetime.datetime.strptime(f"{year}-01-01", "%Y-%m-%d")
    end_year = datetime.datetime.strptime(f"{year}-12-31", "%Y-%m-%d").replace(hour=23)

    simulation_snapshots = network.snapshots[
        network.snapshots.to_series().between(start_year, end_year)
    ]

    generation = network.generators_t.p.loc[simulation_snapshots]

    monthly_gen = (
        pd.concat(
            [network.generators, generation.groupby(pd.Grouper(freq="M")).sum().T],
            axis=1,
        )
        .groupby("carrier")
        .sum()
        .iloc[:, -12:]
        .T
    )
    monthly_gen.index = pd.to_datetime(monthly_gen.index).month_name()
    monthly_gen.columns = [
        "DFO" if gen == "dfo" else gen.title() for gen in monthly_gen.columns
    ]
    monthly_gen.plot.bar(
        stacked=True,
        title=f"Monthly Generation in ERCOT by Fuel Type in {year}",
        ylabel="Generation(MWHs)",
    )
    plt.tight_layout()
    plt.legend(loc="upper left")
    render_graph(scenario, f"OpenERCOT_Monthly_Gen_{year}")

    gen_share = (monthly_gen.T / monthly_gen.sum(axis=1)).T * 100
    gen_share.plot.bar(
        stacked=True,
        title=f"Monthly Generation Share in ERCOT by Fuel Type in {year}",
        ylabel="Percentage of Generation",
    )
    plt.tight_layout()
    render_graph(scenario, f"OpenERCOT_Monthly_Gen_Share_{year}")

    weekly_average_price = (
        network.buses_t.marginal_price.loc[simulation_snapshots].resample("W").mean()
    )

    weekly_average_price.plot(
        title=f"Weekly Average Marginal Cost per Buses in {year}",
        xlabel="Date",
        ylabel="Marginal Cost(Dollars)",
    )

    plt.tight_layout()
    render_graph(scenario, f"OpenERCOT_Weekly_Average_Price_{year}")

    weekly_total_storage = (
        network.storage_units_t.p.loc[simulation_snapshots]
        .clip(0)
        .sum(axis=1)
        .resample("W")
        .sum()
    )

    weekly_total_storage.plot(
        title=f"Weekly Total Storage Dispatch in {year}",
        xlabel="Date",
        ylabel="Dispatch(MWHs)",
    )

    plt.tight_layout()
    render_graph(scenario, f"OpenERCOT_Weekly_Total_Storage_Dispatch_{year}")

    plot_emissions(scenario, network, year)


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


def build_emissions_data(year):
    cross = build_crosswalk()
    cems = get_cems_data(year)[
        ["facilityId", "unitId", "so2Rate", "co2Rate", "noxRate"]
    ]
    cross["PYPSA_ID"] = (
        cross["EIA_PLANT_ID"].astype(str) + "-" + cross["EIA_GENERATOR_ID"].astype(str)
    )
    cross.drop(["EIA_PLANT_ID", "EIA_GENERATOR_ID"], inplace=True, axis=1)
    merged = cross.merge(
        cems,
        left_on=["CAMD_PLANT_ID", "CAMD_UNIT_ID"],
        right_on=["facilityId", "unitId"],
    )
    merged.drop(
        ["CAMD_PLANT_ID", "CAMD_UNIT_ID", "facilityId", "unitId"], inplace=True, axis=1
    )
    merged = merged.groupby("PYPSA_ID").mean()
    return merged


def plot_emissions(scenario: Scenario, network: pypsa.Network, year: int):
    # collect emissions data for the year
    emissions = build_emissions_data(year)

    # build dataframe with emissions data
    gen_ems = pd.concat([network.generators, emissions], axis=1)

    # fild mean rates for missing data
    default_rates = (
        gen_ems.groupby("type")[["so2Rate", "co2Rate", "noxRate"]].mean().dropna()
    )

    # calculate unique technologies
    em_techs = default_rates.index.unique()

    # filter to just technologies we have coverage over
    gen_ems = gen_ems[gen_ems["type"].isin(em_techs)]

    # filter to the year under question
    start_year = datetime.datetime.strptime(f"{year}-01-01", "%Y-%m-%d")
    end_year = datetime.datetime.strptime(f"{year}-12-31", "%Y-%m-%d").replace(hour=23)

    simulation_snapshots = network.snapshots[
        network.snapshots.to_series().between(start_year, end_year)
    ]

    # find the generation
    generation = network.generators_t.p.loc[simulation_snapshots]

    # resample to monthly generation
    monthly_gen = generation.groupby(pd.Grouper(freq="M")).sum()

    # fix naming of the indexes
    monthly_gen.index = pd.to_datetime(monthly_gen.index).month_name()

    # merge monthly gen with the rates
    merged = pd.concat([gen_ems, monthly_gen.T], axis=1, join="inner")

    # fill in missing rows
    for row in default_rates.iterrows():
        merged.loc[merged["type"] == row[0]] = merged.loc[
            merged["type"] == row[0]
        ].fillna(row[1].to_dict())

    so2 = merged.iloc[:, -12:].mul(merged["so2Rate"], axis="index").sum()
    nox = merged.iloc[:, -12:].mul(merged["noxRate"], axis="index").sum()
    co2 = merged.iloc[:, -12:].mul(merged["co2Rate"], axis="index").sum()
    emissions = pd.concat([nox, co2, so2], axis=1)
    emissions.columns = ["NOX", "CO2", "SO2"]
    emissions.plot.bar(
        title=f"Monthly Estimated Emissions for {year}",
        ylabel="Emissions Mass(Short Tons)",
    )
    plt.tight_layout()
    render_graph(scenario, f"OpenERCOT_Monthly_Emissions_{year}")

    so2_rate = so2 / merged.iloc[:, -12:].sum()
    nox_rate = nox / merged.iloc[:, -12:].sum()
    co2_rate = co2 / merged.iloc[:, -12:].sum()
    emissions_rate = pd.concat([nox_rate, co2_rate, so2_rate], axis=1)
    emissions_rate.columns = ["NOX", "CO2", "SO2"]
    emissions_rate.plot.bar(
        title=f"Monthly Estimated Emissions Rate for {year}",
        ylabel="Emissions Rate(Short Tons/MWH)",
    )
    plt.tight_layout()
    render_graph(scenario, f"OpenERCOT_Monthly_Emissions_Rate_{year}")
