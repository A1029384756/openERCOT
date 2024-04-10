from os.path import isfile
import toml
import matplotlib.pyplot as plt
from pypsa.components import os
from scenario import Scenario
from typing import Any, NotRequired


def render_graph(scenario: Scenario, name: str):
    out_dir = scenario.get("out_dir")
    if out_dir is None:
        return

    if scenario["io_params"]["graphs_to_file"]:
        plt.savefig(f"{out_dir}{name}", dpi=300)
        plt.clf()
    else:
        plt.show()


def validate_dict(
    data: Any, type_annotation: type, required_fields: frozenset[str]
) -> None:
    if not isinstance(data, dict):
        raise ValueError("data is not dict")

    missing_fields = required_fields - set(data.keys())
    if missing_fields:
        raise ValueError(f"data missing fields: {missing_fields}")

    unexpected_fields = set(data.keys()) - required_fields
    if unexpected_fields:
        raise ValueError(f"data unexpected fields: {unexpected_fields}")

    for field_name, field_type in type_annotation.__annotations__.items():
        if not isinstance(data.get(field_name), dict):
            if (
                field_type != NotRequired[str]
                and type(data.get(field_name)) != field_type
            ):
                raise ValueError(
                    f"data type mismatch, expected {field_type} but got {type(data.get(field_name))}"
                )
        else:
            validate_dict(
                data.get(field_name), field_type, field_type.__required_keys__
            )


def load_scenario(path: str) -> Scenario:
    if not isfile(path):
        print("Invalid scenario path")
        exit(os.EX_NOINPUT)
    scenario: Scenario = toml.load(path)  # type:ignore
    validate_dict(scenario, Scenario, Scenario.__required_keys__)
    return scenario
