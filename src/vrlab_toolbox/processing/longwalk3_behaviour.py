from dataclasses import dataclass, field

import pandera.pandas as pa

from vrlab_toolbox.processing.behaviour import RawBehaviourData
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.longwalk3_bids import (
    build_longwalkv3_raw_session_events_behav_file_schema,
)
from vrlab_toolbox.processing.output_data import PipelineOutputData


def build_longwalkv3_behaviour_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


class RawLongWalkV3BehaviourData(RawBehaviourData):
    """Raw data for LongWalkV3 is based off BIDS events schema"""

    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_longwalkv3_raw_session_events_behav_file_schema
    )


@dataclass
class LongWalkV3BehaviourOutputData(PipelineOutputData):
    """
    Returns the one line output data which the Pipeline can concatenate for the final
    group level output.
    """

    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_longwalkv3_behaviour_output_schema
    )


class ImportLongWalkV3BehaviourDataStrategyStep:
    behaviour_output_type: type[RawLongWalkV3BehaviourData] = RawLongWalkV3BehaviourData

    def run(self, config_in: ParticipantConfig) -> RawLongWalkV3BehaviourData:

        return RawLongWalkV3BehaviourData.load_from_behaviour_type(
            config_in, self.behaviour_output_type
        )


class ProcessLongWalkV3BehaviourDataStrategyStep:
    input_data_type: type[RawLongWalkV3BehaviourData] = RawLongWalkV3BehaviourData

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: RawLongWalkV3BehaviourData,
    ) -> LongWalkV3BehaviourOutputData:

        return LongWalkV3BehaviourOutputData(config_in.subject_id)
