import pypsa
from pypsa.plot import plt

network = pypsa.Network()
network.import_from_netcdf(path="network.nc")
network.plot()
plt.show()
