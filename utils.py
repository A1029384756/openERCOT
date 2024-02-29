from os import makedirs
import errno
import matplotlib.pyplot as plt
from pypsa.components import os
from scenario import Scenario
from typing import TypeVar, Any


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


def validate_dict(
    data: Any, type_annotation: type, required_fields: frozenset[str]
) -> None:
    if not isinstance(data, dict):
        raise ValueError()

    missing_fields = required_fields - set(data.keys())
    if missing_fields:
        raise ValueError()

    unexpected_fields = set(data.keys()) - required_fields
    if unexpected_fields:
        raise ValueError()

    for field_name, field_type in type_annotation.__annotations__.items():
        if not isinstance(data.get(field_name), dict):
            if type(data.get(field_name)) != field_type:
                raise ValueError()
        else:
            validate_dict(
                data.get(field_name), field_type, field_type.__required_keys__
            )
