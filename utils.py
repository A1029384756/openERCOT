from os import makedirs
import errno
import matplotlib.pyplot as plt
from pypsa.components import os
from scenario import Scenario


def render_graph(scenario: Scenario, name: str):
    if scenario["io_params"]["graphs_to_file"]:
        out_path = f"{os.getcwd()}/graphs/"
        try:
            makedirs(out_path)
        except OSError as e:
            if e.errno == errno.EEXIST and os.path.isdir(out_path):
                pass
            else:
                raise
        plt.savefig(f"{out_path}{name}")
        plt.clf()
    else:
        plt.show()
