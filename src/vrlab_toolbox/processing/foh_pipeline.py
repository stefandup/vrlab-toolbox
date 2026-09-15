import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from vrlab_toolbox.processing import pipeline
from vrlab_toolbox.processing.eda import ProcessEdaPhysiologyDataStrategyStep
from vrlab_toolbox.processing.foh_behaviour import (
    ImportFohBehaviourDataStrategyStep,
    ProcessFohBehaviouralDataStrateyStep,
)
from vrlab_toolbox.processing.foh_target_behaviour import (
    ImportFohTargetBehaviourDataStrategyStep,
    ProcessFohTargetDataWithIntervalsStrategyStep,
)
from vrlab_toolbox.processing.foh_trial_intervals import FohGetTrialIntervalStrategyStep
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.lsl import FohLslPhysiologyDataImportStrategy
from vrlab_toolbox.processing.output_data import PipelineOutputData

from . import trial_intervals as trial_intervals

logger = logging.getLogger(__name__)


def has_missing_requirements(missing: set, required: list[str]) -> bool:
    return any(stream in missing for stream in required)


class FindFohParticipantFilesStrategyStep:
    physiology_data_type = FohLslPhysiologyDataImportStrategy.input_data_file_format
    behaviour_data_types = [
        ProcessFohBehaviouralDataStrateyStep.input_data_type,
        ProcessFohTargetDataWithIntervalsStrategyStep.input_data_type,
    ]

    def run(
        self, participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
    ) -> ParticipantConfig:

        return ParticipantConfig.from_lsl_data(
            id_in=participant_id_in,
            physiology_data_type_in=self.physiology_data_type,
            data_folder_in=data_folder_in,
            output_folder_in=output_folder_in,
        )


# TODO: Fill out pipeline output schema for FOH
def build_foh_participant_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


@dataclass
class FohPipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_foh_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(
    participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
) -> FohPipelineOutputData:

    import_behav_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[ImportFohBehaviourDataStrategyStep(), ImportFohTargetBehaviourDataStrategyStep()]
    )
    process_behav_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps=[], steps_with_trial_intervals=[ProcessFohTargetDataWithIntervalsStrategyStep()]
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[FohLslPhysiologyDataImportStrategy()]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessEdaPhysiologyDataStrategyStep()]
    )

    foh_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=FindFohParticipantFilesStrategyStep(),
        get_intervals_strategy=FohGetTrialIntervalStrategyStep(),
        sequential_behaviour_data_import_steps=import_behav_steps,
        sequential_behaviour_processing_steps=process_behav_steps,
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_config, participant_pipeline_data_output = foh_pipeline.run(
        participant_id_in=participant_id_in,
        data_folder_in=data_folder_in,
        output_folder_in=output_folder_in,
    )

    foh_pipeline_data_out = FohPipelineOutputData(participant_config.subject_id)
    foh_pipeline_data_out.subject_df_out = participant_pipeline_data_output.subject_df_out
    foh_pipeline_data_out.status = participant_pipeline_data_output.status
    foh_pipeline_data_out.figure_data_out = participant_pipeline_data_output.figure_data_out

    return foh_pipeline_data_out
