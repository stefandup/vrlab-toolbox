import logging
import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Self

import pandas as pd
import pandera.pandas as pa
from typing_extensions import deprecated

from mooi_toolbox.processing import pandera_defaults as pa_default
from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.output_data import PipelineOutputData

logger = logging.getLogger(__name__)

REDCAP_FN = "CraneGame_Emotional Experience Form.xlsx"
GROUP_REDCAP_GLOB = "KHANYAEmotionLab-Getalldata_DATA_*.csv"
# TODO: Do a MAP for converting from redcap. Do stick to core emotions as listed here.
EMOTIONS_TESTED = (
    "boredom",
    "dissatisfaction",
    "joy",
    "sadness",
    "satisfaction",
    "confused",
    "anger",
)
emotion_cols = [emotion.lower() for emotion in EMOTIONS_TESTED]

crane_raw_debrief_file_schema = pa.DataFrameSchema(
    {
        "record_id": pa_default.str_col(),
        "started": pa_default.str_col(),  # Some have a str here others a 1/2
        "height": pa_default.str_col(),
        # We generate this as it helps validate our EMOTIONS_TESTED variable
        **{
            f"crane_{emotion}_{barrel_color}": pa_default.likert_col()
            for emotion in emotion_cols
            for barrel_color in ["rb", "gb"]
        },
    },
    strict=True,
    coerce=True,
)

DEBRIEF_OUTPUT_METRICS = tuple(emotion_cols)
TRIAL_TYPES = ("SlipTrial", "NonSlipTrial")


def build_crane_debrief_pipeline_output_schema() -> pa.DataFrameSchema:
    """
    Debrief output data looks the same as the raw data, except it is a single subject row
    without the SubjectID, which is supplied by the parent rawbehav class
    """
    return pa.DataFrameSchema(
        {
            "Debrief_started": pa_default.optional_str_col(),  # Some have a str here others a 1/2
            "Debrief_height": pa_default.optional_str_col(),
            **{
                f"Debrief_crane_{metric}_{trial_type}": pa_default.optional_float_col()
                for metric in DEBRIEF_OUTPUT_METRICS
                for trial_type in TRIAL_TYPES
            },
        }
    )


@dataclass
class CraneDebriefPipelineOutput(PipelineOutputData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_crane_debrief_pipeline_output_schema
    )


@dataclass
class RawDebriefBehaviourData(RawBehaviourData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=lambda: crane_raw_debrief_file_schema
    )
    filename_glob = "sub-{participant_id}_*acq-debrief*.tsv"

    @classmethod
    def load_group_data_from_config(cls, config_in: ParticipantConfig) -> Self:

        debrief_df = get_group_debrief_data(config_in.behav_folder)

        return cls(subject_config=config_in, raw_behav_df=debrief_df)

    def get_single_subject_from_group_data(self, subject_id_in: str) -> "RawDebriefBehaviourData":

        matching_subject_df = self.raw_behav_df.loc[self.raw_behav_df["record_id"] == subject_id_in]

        if matching_subject_df.empty:
            logger.error(f"Subject {subject_id_in} not found in {GROUP_REDCAP_GLOB}.")
            raise ValueError

        raw_debrief_data_out = RawDebriefBehaviourData(
            subject_config=self.subject_config, raw_behav_df=matching_subject_df
        )

        return raw_debrief_data_out


class ImportCraneDebriefDataProcessStrategyStep:
    behaviour_output_type = RawDebriefBehaviourData

    def run(self, config_in: ParticipantConfig) -> RawDebriefBehaviourData:
        single_subject_data = RawDebriefBehaviourData.load_from_behaviour_type(
            config_in, self.behaviour_output_type
        )

        return single_subject_data


class ProcessCraneDebriefBehaviourDataStrategyStep:
    input_data_type = RawDebriefBehaviourData

    def run(
        self, config_in: ParticipantConfig, raw_behaviour_data_in: RawDebriefBehaviourData
    ) -> CraneDebriefPipelineOutput:

        raw_data_df = raw_behaviour_data_in.raw_behav_df
        pipeline_df_out = raw_data_df.copy()
        # TODO: Perhaps fix dissastifaction spelling in redcap? :)
        pipeline_df_out.columns = (
            pipeline_df_out.columns.str.replace("_gb", "_SlipTrial")
            .str.replace("_rb", "_NonSlipTrial")
            .str.replace("dissastifaction", "dissatisfaction")
        )
        pipeline_df_out = pipeline_df_out.drop(columns="record_id")
        pipeline_df_out = pipeline_df_out.add_prefix("Debrief_")

        debrief_pipeline_data_out = CraneDebriefPipelineOutput(config_in.subject_id)
        debrief_pipeline_data_out.append_dataframe(
            pipeline_df_out, build_crane_debrief_pipeline_output_schema().columns
        )

        return debrief_pipeline_data_out


@cache
def get_group_debrief_data(group_data_fn: Path) -> pd.DataFrame:

    red_cap_glob = GROUP_REDCAP_GLOB

    debrief_fn_list = list(group_data_fn.rglob(red_cap_glob))

    if not debrief_fn_list:
        logger.error(f"Could not find debrief data at {GROUP_REDCAP_GLOB}.")
        raise FileNotFoundError

    if len(debrief_fn_list) > 1:
        logger.warning(f"Multiple files detected. Using {debrief_fn_list[0]}")

    debrief_fn = debrief_fn_list[0]

    df = pd.read_csv(debrief_fn)

    debrief_cols_filter = list(crane_raw_debrief_file_schema.columns)

    crane_debrief_df = df.filter(items=debrief_cols_filter)

    try:
        crane_debrief_df_validated = crane_raw_debrief_file_schema.validate(crane_debrief_df)
    except pa.errors.SchemaErrors as e:
        logger.error("Error loading %s: %s", debrief_fn, e.failure_cases.to_string(index=False))
        raise

    return crane_debrief_df_validated


@deprecated("Older style data import")
def load_group_debrief_data(behaviour_data_dir: Path) -> pd.DataFrame:
    red_cap_fn = REDCAP_FN
    data_fn = os.path.join(behaviour_data_dir, red_cap_fn)

    df = pd.read_excel(data_fn, dtype={"Subject_ID": str})

    # Clean column names a bit
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.replace("/", "_")

    # Forward-fill subject-level variables
    subject_cols = ["Subject_ID", "started_with_Crane_MobiLab", "High_at_start_end"]

    df[subject_cols] = df[subject_cols].ffill()

    # Drop fully empty rows, if any
    df = df.dropna(how="all")
    df = df.drop(columns="Subject_Names")

    # Validate df

    try:
        df_validated = crane_raw_debrief_file_schema.validate(df)
    except pa.errors.SchemaErrors as e:
        logger.error("Error loading %s: %s", data_fn, e.failure_cases.to_string(index=False))
        raise

    # Optional: rename BARREL to something clearer
    df_validated = df_validated.rename(columns={"BARREL": "TrialType"})
    df_validated["TrialType"] = df_validated["TrialType"].replace(
        {"GREEN": "SlipTrial", "RED": "NonSlipTrial"}
    )

    emotion_totals = df_validated[emotion_cols].sum(axis=1)
    emotion_proportions = df_validated[emotion_cols].div(emotion_totals, axis=0)
    df_proportions = df_validated.drop(columns=emotion_cols, errors="ignore").join(
        emotion_proportions
    )

    wide = df_proportions.pivot(index=["Subject_ID"], columns="TrialType", values=emotion_cols)
    wide.columns = [f"{emotion}_{colour}" for emotion, colour in wide.columns]
    wide = wide.reset_index()
    debrief_data_out = wide.add_prefix("Debrief_")

    return debrief_data_out


def process(config_in: ParticipantConfig) -> pd.DataFrame:
    debrief_df = load_group_debrief_data(config_in.behav_folder)
    # Copy as to ensure the cache is read only.
    # Cahce ensures that we dont reload the excel for every subject
    subject_debrief_out = debrief_df.loc[
        debrief_df["Debrief_Subject_ID"] == config_in.subject_id
    ].copy()

    if subject_debrief_out.empty:
        logger.warning("Missing behaviour data for subject %s", config_in.subject_id)
        raise ValueError

    subject_debrief_out = subject_debrief_out.drop(columns="Debrief_Subject_ID")
    return subject_debrief_out
