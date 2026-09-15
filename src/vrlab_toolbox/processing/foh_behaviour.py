import logging
from dataclasses import dataclass, field

import pandera.pandas as pa
import pyxdf

from vrlab_toolbox.processing.behaviour import RawBehaviourData
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.lsl import (
    all_lsl_streams_empty,
    gather_xdf_data_streams,
)
from vrlab_toolbox.processing.output_data import PipelineOutputData

logger = logging.getLogger(__name__)


def build_foh_raw_behav_schema() -> pa.DataFrameSchema:
    foh_raw_behav_file_schema = pa.DataFrameSchema(
        {
            "time_stamps": pa.Column(float, pa.Check.ge(1), nullable=False),
            "VR_trial": pa.Column(
                str,
                pa.Check.isin(
                    [
                        "DoSTDQuestions",
                        "RaiseSafetyPlatform",
                        "SafetyPlatformReachedMax",
                        "RaiseMainPlatform",
                        "MainPlatformAtMax",
                        "MainPlatformLowering",
                        "MainPlatformAtMin",
                        "SafetyPlatformAtMin",
                        "RunFOHQuestions",
                        "",
                    ]
                ),
                nullable=False,
            ),
        },
        strict=True,
        coerce=True,
    )

    return foh_raw_behav_file_schema


@dataclass
class RawFohBehaviourData(RawBehaviourData):
    validation_schema: pa.DataFrameSchema = field(default_factory=build_foh_raw_behav_schema)


class ImportFohBehaviourDataStrategyStep:
    behaviour_output_type: type[RawFohBehaviourData] = RawFohBehaviourData

    def run(self, config_in: ParticipantConfig) -> RawFohBehaviourData:
        streams: list[dict]
        lsl_behav_stream_to_get = "VR_trial_events"
        xdf_path = config_in.physiology_fn
        streams, _ = pyxdf.load_xdf(xdf_path)

        selected_lsl_behav_stream_df = gather_xdf_data_streams(streams, [lsl_behav_stream_to_get])

        if all_lsl_streams_empty(selected_lsl_behav_stream_df):
            logger.warning(f"All streams empty for path {xdf_path}.")

        missing_streams_out = {lsl_behav_stream_to_get} - set(selected_lsl_behav_stream_df.keys())

        if missing_streams_out:
            logger.warning(f"Missing streams {missing_streams_out} for {config_in.subject_id}")
            raise ValueError

        return RawFohBehaviourData(
            subject_config=config_in,
            raw_behav_df=selected_lsl_behav_stream_df[lsl_behav_stream_to_get],
        )


# TODO: Under construction!
class ProcessFohBehaviouralDataStrateyStep:
    input_data_type: type[RawFohBehaviourData] = RawFohBehaviourData

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: RawFohBehaviourData,
    ) -> PipelineOutputData:

        return PipelineOutputData(config_in.subject_id)
