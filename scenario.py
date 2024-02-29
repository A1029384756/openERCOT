from typing import TypedDict


class SimulationParams(TypedDict, total=True):
    """
    start: date to start simulation format: YEAR-MONTH-DAY ex: '2021-05-02'
    end: date to end simulation format: YEAR-MONTH-DAY ex: '2021-05-02'
    committable: whether to allow generators to be committable
    set_size: integer size of chunk to simulate, set to zero for no chunking
    overlap: integer size of chunk overlap, set to zero for no overlap
    """

    start_date: str
    end_date: str
    committable: bool
    set_size: int
    overlap: int


class IOParams(TypedDict, total=True):
    """
    network_path: path to reference for network loading
    graphs_to_file: whether to output any graphs to a file or to the screen
    """

    network_path: str
    graphs_to_file: bool


class Scenario(TypedDict, total=True):
    """
    simulation_params: parameters to do with the actual network simulation
    io_params: parameters that specify where to read and write files
    """

    simulation_params: SimulationParams
    io_params: IOParams
