from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from vrlab_toolbox.processing import pipeline
from vrlab_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from vrlab_toolbox.processing.eda import ProcessEdaPhysiologyDataStrategyStep
from vrlab_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from vrlab_toolbox.processing.longwalk3_behaviour import (
    ImportLongWalkV3BehaviourDataStrategyStep,
    ProcessLongWalkV3BehaviourDataStrategyStep,
)
from vrlab_toolbox.processing.longwalk3_debrief_behaviour import (
    ImportLongWalkV3DebriefDataProcessStrategyStep,
    ProcessLongWalkV3DebriefBehaviourDataStrategyStep,
)
from vrlab_toolbox.processing.longwalk3_trial_intervals import (
    LongWalkV3GetTrialIntervalStrategyStep,
)
from vrlab_toolbox.processing.output_data import PipelineOutputData


class FindLongWalkV3ParticipantFilesStrategyStep:
    physiology_data_type = PhysiologyFileFormat.BIOPAC
    behaviour_data_types = [
        ProcessLongWalkV3BehaviourDataStrategyStep.input_data_type,
        ProcessLongWalkV3DebriefBehaviourDataStrategyStep.input_data_type,
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


def build_longwalkv3_participant_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


@dataclass
class LongWalkV3PipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_longwalkv3_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(
    participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
) -> LongWalkV3PipelineOutputData:
    """Run the longwalkV3 behaviour/physiology pipeline for a single participant.

    `data_folder_in` must be a BIDS-formatted folder. This assumes the data has
    already been through the crosscheck tool (`gui/longwalkV3_bids_crosscheck_gui.py`)
    so duplicate runs and id/date corrections are resolved before processing.
    """

    import_behav_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[
            ImportLongWalkV3BehaviourDataStrategyStep(),
            ImportLongWalkV3DebriefDataProcessStrategyStep(),
        ]
    )
    process_behav_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps=[
            ProcessLongWalkV3BehaviourDataStrategyStep(),
            ProcessLongWalkV3DebriefBehaviourDataStrategyStep(),
        ]
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[
            BiopacPhysiologyDataImportStartegy(
                input_data_file_format=FindLongWalkV3ParticipantFilesStrategyStep.physiology_data_type
            )
        ]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessEdaPhysiologyDataStrategyStep()]
    )

    longwalkV3_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=FindLongWalkV3ParticipantFilesStrategyStep(),
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_behaviour_data_import_steps=import_behav_steps,
        get_intervals_strategy=LongWalkV3GetTrialIntervalStrategyStep(),
        sequential_behaviour_processing_steps=process_behav_steps,
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_config, participant_pipeline_data_out = longwalkV3_pipeline.run(
        participant_id_in,
        data_folder_in,
        output_folder_in,
    )
    # TODO: This needs a classmethod to avoid future errors when implementing pipeline
    longwalkV3_pipeline_output_data = LongWalkV3PipelineOutputData(participant_config.subject_id)
    longwalkV3_pipeline_output_data.subject_df_out = participant_pipeline_data_out.subject_df_out
    longwalkV3_pipeline_output_data.status = participant_pipeline_data_out.status
    longwalkV3_pipeline_output_data.figure_data_out = participant_pipeline_data_out.figure_data_out

    return longwalkV3_pipeline_output_data
