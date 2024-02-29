import pypsa
from pypsa.plot import plt
import cartopy.crs as ccrs
import cartopy


def draw_map_cartopy(ax, geomap=True, color_geomap=None):
    resolution = "50m" if isinstance(geomap, bool) else geomap
    assert resolution in [
        "10m",
        "50m",
        "110m",
    ], "Resolution has to be one of '10m', '50m', '110m'"

    if not color_geomap:
        color_geomap = {}
    elif not isinstance(color_geomap, dict):
        color_geomap = {
            "ocean": "lightblue",
            "land": "whitesmoke",
            "border": "darkgray",
            "state": "lightgray",
            "coastline": "black",
        }

    if "land" in color_geomap:
        ax.add_feature(
            cartopy.feature.LAND.with_scale(resolution), facecolor=color_geomap["land"]
        )

    if "ocean" in color_geomap:
        ax.add_feature(
            cartopy.feature.OCEAN.with_scale(resolution),
            facecolor=color_geomap["ocean"],
        )

    ax.add_feature(
        cartopy.feature.BORDERS.with_scale(resolution),
        linewidth=0.3,
        color=color_geomap.get("border", "k"),
    )

    ax.add_feature(
        cartopy.feature.STATES.with_scale(resolution),
        linewidth=0.2,
        edgecolor=color_geomap.get("state", "k"),
    )

    ax.add_feature(
        cartopy.feature.COASTLINE.with_scale(resolution),
        linewidth=0.3,
        color=color_geomap.get("coastline", "k"),
    )


fig, ax = plt.subplots(subplot_kw={"projection": ccrs.PlateCarree()})
draw_map_cartopy(ax, True, True)

network = pypsa.Network()
network.import_from_netcdf(path="network.nc")
network.plot(
    geomap=False,
    margin=0.5,
)
plt.show()
