import logging
from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing import crane_behaviour as crane_behaviour
from mooi_toolbox.processing import crane_debrief_behaviour as debrief
from mooi_toolbox.processing import pipeline
from mooi_toolbox.processing.biopac import BiopacDataImportStartegy
from mooi_toolbox.processing.crane_behaviour import (
    ImportCraneBehaviourDataStrategyStep,
    ProcessCraneBehaviourDataStrategyStep,
)
from mooi_toolbox.processing.crane_debrief_behaviour import (
    ImportCraneDebriefDataProcessStrategyStep,
    ProcessCraneDebriefBehaviourDataStrategyStep,
)
from mooi_toolbox.processing.crane_trial_intervals import CraneGetTrialIntervalStrategyStep
from mooi_toolbox.processing.eda import ProcessEdaPhysiologyDataStrategyStep
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.output_data import (
    PipelineOutputData,
    build_base_pipeline_output_schema,
)

logger = logging.getLogger(__name__)

EMOTIONS_TESTED = [
    "Boredom",
    "Dissatisfaction",
    "Joy",
    "Sadness",
    "Satisfaction",
    "Confused",
    "Anger",
]

BLOCK_TYPES = ("NonStressBlock", "StressBlock")
TRIAL_TYPES = ("SlipTrial", "NonSlipTrial")
BEHAVIOUR_OUTPUT_METRICS = (
    "nausea_avg",
    "dizziness_avg",
    "stressed_avg",
    "dropped_total",
    "nr_frustration_barrels",
    "nr_error_slips",
    "nr_slips",
    "nr_no_reason_slips",
    "nr_forced_slips",
    "avg_velocity",
    "target_score",
    *(f"{emotion}_proportion" for emotion in EMOTIONS_TESTED),
)

DEBRIEF_OUTPUT_METRICS = tuple(debrief.emotion_cols)
EXPECTED_INTERVAL_NR = 23


def _optional_float_column() -> pa.Column:
    return pa.Column(float, nullable=True, coerce=True, required=False)


def build_crane_debrief_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            f"Debrief_{metric}_{trial_type}": _optional_float_column()
            for metric in DEBRIEF_OUTPUT_METRICS
            for trial_type in TRIAL_TYPES
        },
        coerce=True,
        strict=False,
    )


# TODO Unlikely to be unique!


@dataclass
class CraneDebriefOutputData(PipelineOutputData):
    validation_schema: pa.DataFrameSchema = field(default_factory=build_crane_debrief_output_schema)


# TODO: Might be redundant as the physiology is less uniquely specified


# Schema builds more or less automatically based on the constants set.
# TODO THis schema can be split into behaviour/debrief and physiology types.
# TODO: Can be rebuild from a CranePipelineOutputData.from_pipeline_output(...) classmethod
def build_crane_participant_output_schema() -> pa.DataFrameSchema:
    """Create schema for the wide participant output produced by this pipeline."""
    behaviour_columns = {
        f"{metric}_{block_type}_{trial_type}": _optional_float_column()
        for metric in BEHAVIOUR_OUTPUT_METRICS
        for block_type in BLOCK_TYPES
        for trial_type in TRIAL_TYPES
    }

    debrief_columns = {
        f"Debrief_{metric}_{trial_type}": _optional_float_column()
        for metric in DEBRIEF_OUTPUT_METRICS
        for trial_type in TRIAL_TYPES
    }

    physiology_columns = {
        r"^.+_SCR_per_min$": pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
            regex=True,
        )
    }

    return build_base_pipeline_output_schema(
        {**behaviour_columns, **debrief_columns, **physiology_columns}
    )


@dataclass
class CranePipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_crane_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(config_in: ParticipantConfig) -> CranePipelineOutputData:

    import_behav_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[ImportCraneBehaviourDataStrategyStep(), ImportCraneDebriefDataProcessStrategyStep()]
    )
    process_behav_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps=[
            ProcessCraneBehaviourDataStrategyStep(),
            ProcessCraneDebriefBehaviourDataStrategyStep(),
        ]
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[BiopacDataImportStartegy()]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessEdaPhysiologyDataStrategyStep()]
    )

    crane_pipeline = pipeline.PipelineTemplate(
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_behaviour_data_import_steps=import_behav_steps,
        get_intervals_strategy=CraneGetTrialIntervalStrategyStep(),
        sequential_behaviour_processing_steps=process_behav_steps,
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_pipeline_data_out = crane_pipeline.run(config_in)
    # TODO: This needs a classmethod to avoid future errors when implementing pipeline
    crane_pipeline_output_data = CranePipelineOutputData(config_in.subject_id)
    crane_pipeline_output_data.subject_df_out = participant_pipeline_data_out.subject_df_out
    crane_pipeline_output_data.status = participant_pipeline_data_out.status
    crane_pipeline_output_data.figure_data_out = participant_pipeline_data_out.figure_data_out

    return crane_pipeline_output_data
