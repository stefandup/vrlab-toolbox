import pandera.pandas as pa

from vrlab_toolbox.processing.behaviour import RawBehaviourData


def build_long_walk_v3_raw_behav_file_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


class RawLongWalkV3BehaviourData(RawBehaviourData):
    pass


class ImportLongWalkV3BehaviourDataStrategyStep:
    pass


class ProcessLongWalkV3BehaviourDataStrategyStep:
    pass
