import datetime
import io

import pandas as pd
import pypsa
from pypsa.plot import plt
import cartopy.crs as ccrs
import cartopy
import matplotlib.patches as mpatches
from dataclasses import dataclass

from scenario import Scenario
from utils import render_graph
from PIL import Image


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


def draw_map_cartopy(ax):
    resolution = "50m"

    ax.add_feature(
        cartopy.feature.LAND.with_scale(resolution),
        facecolor=CatppuccinLatte.base,
    )

    ax.add_feature(
        cartopy.feature.OCEAN.with_scale(resolution),
        facecolor=CatppuccinLatte.sky,
    )

    ax.add_feature(
        cartopy.feature.STATES.with_scale(resolution),
        linewidth=0.5,
        edgecolor=CatppuccinLatte.overlay0,
    )

    ax.add_feature(
        cartopy.feature.BORDERS.with_scale(resolution),
        linewidth=0.7,
        color=CatppuccinLatte.overlay1,
    )

    ax.add_feature(
        cartopy.feature.COASTLINE.with_scale(resolution),
        linewidth=0.9,
        color=CatppuccinLatte.overlay2,
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
        title=f"OpenERCOT Dispatch by Generator Type for {snapshot}",
        geomap=False,
        bus_sizes=gen / 5e4,
        bus_colors=bus_colors,  # type: ignore
        link_widths=0.01,
        margin=0.2,
        link_colors=CatppuccinLatte.text,
        color_geomap=False,
        flow=snapshot,
    )

    handles = []
    for k, v in bus_colors.items():
        lab = "DFO" if k == "dfo" else k.title()
        handles.append(mpatches.Patch(color=v, label=lab))

    ax.legend(handles=handles, loc="lower left")

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
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

    monthly_gen = pd.concat([network.generators, generation.groupby(pd.Grouper(freq="M")).sum().T], axis=1).groupby(
        "carrier").sum().iloc[:, -12:].T
    monthly_gen.index = pd.to_datetime(monthly_gen.index).month_name()
    monthly_gen.columns = ["DFO" if gen == "dfo" else gen.title() for gen in monthly_gen.columns]
    monthly_gen.plot.bar(stacked=True, title=f"Monthly Generation in ERCOT by Fuel Type in {year}",
                         ylabel="Generation(MWHs)")
    plt.tight_layout()
    plt.legend(loc='upper left')
    render_graph(scenario, f"OpenERCOT_Monthly_Gen_{year}")
