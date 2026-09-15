import logging
from dataclasses import dataclass
from pathlib import Path

import pandera.pandas as pa
from pandas.core.api import DataFrame as DataFrame

from vrlab_toolbox.processing import pipeline
from vrlab_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from vrlab_toolbox.processing.eda import (
    ProcessEdaPhysiologyDataStrategyStep,
    build_eda_physiology_output_schema,
)
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.longwalk_behaviour import (
    LongWalkImportRawBehaviourDataStrategy,
    ProcessLongWalkBehaviourDataWithIntervalsStrategyStep,
    build_long_walk_behaviour_output_data_schema,
)
from vrlab_toolbox.processing.longwalk_trial_intervals import LongWalkGetTrialIntervalStrategyStep
from vrlab_toolbox.processing.output_data import (
    PipelineOutputData,
)

logger = logging.getLogger(__name__)

EXPECTED_INTERVAL_NR = 12


class FindLongWalkParticipantFilesStrategyStep:
    physiology_data_type = BiopacPhysiologyDataImportStartegy.input_data_file_format
    behaviour_data_types = [
        ProcessLongWalkBehaviourDataWithIntervalsStrategyStep.input_data_type,
    ]

    def run(
        self, participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
    ) -> ParticipantConfig:

        return ParticipantConfig.from_bids_data(
            id_in=participant_id_in,
            physiology_data_type_in=self.physiology_data_type,
            data_folder_in=data_folder_in,
            behaviour_data_types_in=self.behaviour_data_types,
            output_folder_in=output_folder_in,
        )


def build_longwalk_participant_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            **build_long_walk_behaviour_output_data_schema().columns,
            **build_eda_physiology_output_schema().columns,
        }
    )


@dataclass
class LongWalkPipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> DataFrame:
        return build_longwalk_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(
    participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
) -> LongWalkPipelineOutputData:

    import_behav_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[LongWalkImportRawBehaviourDataStrategy()]
    )
    process_behav_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps_with_trial_intervals=[ProcessLongWalkBehaviourDataWithIntervalsStrategyStep()]
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[BiopacPhysiologyDataImportStartegy()]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessEdaPhysiologyDataStrategyStep()]
    )

    long_walk_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=FindLongWalkParticipantFilesStrategyStep(),
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_behaviour_data_import_steps=import_behav_steps,
        get_intervals_strategy=LongWalkGetTrialIntervalStrategyStep(),
        sequential_behaviour_processing_steps=process_behav_steps,
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_config, participant_pipeline_data_out = long_walk_pipeline.run(
        participant_id_in,
        data_folder_in,
        output_folder_in,
    )

    long_walk_pipeline_output_data = LongWalkPipelineOutputData(participant_config.subject_id)
    long_walk_pipeline_output_data.subject_df_out = participant_pipeline_data_out.subject_df_out
    long_walk_pipeline_output_data.status = participant_pipeline_data_out.status
    long_walk_pipeline_output_data.figure_data_out = participant_pipeline_data_out.figure_data_out

    return long_walk_pipeline_output_data
