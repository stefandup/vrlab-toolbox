import io
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pandera.pandas as pa
import pyxdf

from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.foh_config import TARGET_TYPES, TRIAL_NUMBERS, TRIAL_TYPES
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.lsl import gather_xdf_data_streams
from mooi_toolbox.processing.output_data import PipelineOutputData
from mooi_toolbox.processing.trial_intervals import TrialIntervals

logger = logging.getLogger(__name__)


class TPProcessingError(ValueError):
    """Raised when Target processing fails."""


def build_foh_raw_target_behaviour_file_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            "TimeSpawned": pa.Column(float, pa.Check.ge(1), nullable=False),
            "TimeHit": pa.Column(float, pa.Check.ge(1), nullable=False),
            "HitLatency": pa.Column(float, pa.Check.ge(0), nullable=False),
            "TargetType": pa.Column(str, pa.Check.isin(TARGET_TYPES), nullable=False),
            "time_stamps": pa.Column(float, pa.Check.ge(1), nullable=False),
        },
        strict=True,
        coerce=True,
    )


def _opt_float_column() -> pa.Column:
    return pa.Column(float, nullable=True, coerce=True, required=False)


def build_foh_target_behaviour_pipeline_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            f"{trial_type}_{TRIAL_NUMBERS[trial_type]}_{target_type}_Target": _opt_float_column()
            for trial_type in TRIAL_TYPES
            for target_type in TARGET_TYPES
        },
        coerce=True,
        strict=False,
    )


@dataclass
class FohTargetBehaviourOutputData(PipelineOutputData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_foh_target_behaviour_pipeline_output_schema
    )


class FohRawTargetBehaviourData(RawBehaviourData):
    filename_glob = "xdf"
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_foh_raw_target_behaviour_file_schema
    )


class ImportFohTargetBehaviourDataStrategyStep:
    behaviour_output_type: type[FohRawTargetBehaviourData] = FohRawTargetBehaviourData

    def run(self, config_in: ParticipantConfig) -> FohRawTargetBehaviourData:
        streams: list[dict]
        lsl_behav_stream_to_get = "FOH_target"
        expected_hdr = "TimeSpawned,TimeHit,HitLatency,TargetType"
        xdf_path = config_in.physiology_fn
        streams, _ = pyxdf.load_xdf(xdf_path)
        FOH_target_df_list = gather_xdf_data_streams(streams, [lsl_behav_stream_to_get])
        FOH_target_df = FOH_target_df_list["FOH_target"]

        try:
            lines = FOH_target_df["FOH_target"].dropna().astype(str).tolist()

            if not lines:
                raise TPProcessingError("No target data found.")

            if FOH_target_df["FOH_target"].iloc[0] != expected_hdr:
                logger.warning("Missing header info. Trying to compensate...")
                lines = [expected_hdr] + lines

        except KeyError as e:
            raise TPProcessingError("Error in reading target data") from e

        csv_text = "\n".join(lines)
        if not csv_text:
            raise TPProcessingError("Error reading target data.")

        try:
            target_csvdata_df = pd.read_csv(io.StringIO(csv_text), header=0)
        except (KeyError, pd.errors.ParserError, pd.errors.EmptyDataError) as e:
            raise TPProcessingError("Error reading target data.") from e

        # Remove rows where 'FOH_target' is any unwanted header string or is empty

        unwanted_rows = ["TimeSpawned,TimeHit,HitLatency,TargetType", ""]
        # TODO: BUG?
        filtered_FOH_target_df = FOH_target_df[~FOH_target_df["FOH_target"].isin(unwanted_rows)]
        # filtered_FOH_target_df = filtered_FOH_target_df[~FOH_target_df["FOH_target"].isna()]
        # Prevent index mismatch during filtering
        filtered_FOH_target_df = filtered_FOH_target_df[
            ~filtered_FOH_target_df["FOH_target"].isna()
        ]

        # Concatenate target_csvdata_df with FOH_target_df["time_stamps"] horizontally
        try:
            target_csvdata_df = pd.concat(
                [target_csvdata_df, filtered_FOH_target_df[["time_stamps"]].reset_index(drop=True)],
                axis=1,
            )
        except (KeyError, TypeError, IndexError) as e:
            raise TPProcessingError("Error in time stamps") from e

        return FohRawTargetBehaviourData(subject_config=config_in, raw_behav_df=target_csvdata_df)


class ProcessFohTargetDataWithIntervalsStrategyStep:
    input_data_type: type[FohRawTargetBehaviourData] = FohRawTargetBehaviourData

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: FohRawTargetBehaviourData,
        trial_intervals_in: TrialIntervals,
    ) -> FohTargetBehaviourOutputData:

        target_df_out, _ = run_processing(
            raw_behaviour_data_in.raw_behav_df, trial_intervals_in.intervals
        )
        # Clean column names for output

        target_df_out.columns = [c.lower() for c in target_df_out.columns]

        target_behaviour_outputdata = FohTargetBehaviourOutputData(config_in.subject_id)
        target_behaviour_outputdata.append_dataframe(
            target_df_out, build_foh_target_behaviour_pipeline_output_schema().columns
        )

        return target_behaviour_outputdata


def run_processing(
    target_csvdata_df: pd.DataFrame, vr_intervals: dict[str, tuple[float, float]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Process text data received from lsl for FOH behavioural targets"""
    # TODO: Consider logging what is dropped in the na below

    for interval_id, interval in vr_intervals.items():
        idx = (target_csvdata_df["time_stamps"] >= interval[0]) & (
            target_csvdata_df["time_stamps"] <= interval[1]
        )

        target_csvdata_df.loc[idx, "TrialType"] = interval_id

    # Summarize Target info

    order = ["Short", "Medium", "Long"]
    df = target_csvdata_df.copy()
    df = df.dropna()

    # Arrange in order
    df["TargetType"] = pd.Categorical(df["TargetType"], categories=order, ordered=True)

    df2 = df.copy()
    try:
        # start with normal labels
        df2["wide_col"] = df2["TrialType"] + "_" + df2["TargetType"].astype(str) + "_Target"
    except KeyError as e:
        raise TPProcessingError("Error loading target data. No data found.") from e

    # Additional Baseline labels
    Baseline_mask = df2["TrialType"].astype(str).str.strip().str.lower().eq("baseline")
    df2["Baseline_idx"] = np.nan
    df2.loc[Baseline_mask, "Baseline_idx"] = df2.loc[Baseline_mask].groupby("TargetType").cumcount()

    if not Baseline_mask.any():
        logger.warning("Missing baseline in target data")
    else:
        df2["Baseline_idx"] = df2["Baseline_idx"].astype("Int64")

        # overwrite only Baseline rows
        Baseline_mask = df2["TrialType"].astype(str).str.strip().str.lower().eq("baseline")
        df2.loc[Baseline_mask, "wide_col"] = (
            "Baseline_"
            + df2.loc[Baseline_mask, "Baseline_idx"].astype("Int64").astype(str)
            + "_"
            + df2.loc[Baseline_mask, "TargetType"].astype(str)
            + "_Target"
        )

    # Additional Stress labels
    stress_mask = df2["TrialType"].astype(str).str.strip().str.lower().eq("stress")
    df2["stress_idx"] = np.nan
    df2.loc[stress_mask, "stress_idx"] = df2.loc[stress_mask].groupby("TargetType").cumcount()
    if not stress_mask.any():
        logger.warning("Missing stress in target data")
    else:
        df2["stress_idx"] = df2["stress_idx"].astype("Int64")

        # overwrite only stress rows
        stress_mask = df2["TrialType"].astype(str).str.strip().str.lower().eq("stress")
        df2.loc[stress_mask, "wide_col"] = (
            "Stress_"
            + df2.loc[stress_mask, "stress_idx"].astype("Int64").astype(str)
            + "_"
            + df2.loc[stress_mask, "TargetType"].astype(str)
            + "_Target"
        )

    # Wide (single row)
    target_wide = df2.pivot_table(
        index=None, columns="wide_col", values="HitLatency", aggfunc="first"
    )
    target_data_out = target_wide.reset_index(drop=True)

    return target_data_out, df2
