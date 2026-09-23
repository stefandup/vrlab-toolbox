import logging
from dataclasses import dataclass, field

import pandera.pandas as pa

from vrlab_toolbox.processing.behaviour import RawBehaviourData
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.output_data import PipelineOutputData

logger = logging.getLogger(__name__)


def build_longwalkv3_raw_debrief_file_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


class RawLongWalkV3DebriefBehaviourData(RawBehaviourData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_longwalkv3_raw_debrief_file_schema
    )
    filename_glob = "sub-{participant_id}_*acq-debrief*.tsv"


class ImportLongWalkV3DebriefDataProcessStrategyStep:
    behaviour_output_type = RawLongWalkV3DebriefBehaviourData

    def run(self, config_in: ParticipantConfig) -> RawLongWalkV3DebriefBehaviourData:
        single_subject_data = RawLongWalkV3DebriefBehaviourData.load_from_bids_behaviour_type(
            config_in, self.behaviour_output_type
        )

        return single_subject_data


class ProcessLongWalkV3DebriefBehaviourDataStrategyStep:
    input_data_type = RawLongWalkV3DebriefBehaviourData


def build_longwalkv3_debrief_pipeline_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


@dataclass
class LongWalkV3DebriefPipelineOutput(PipelineOutputData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_longwalkv3_debrief_pipeline_output_schema
    )
