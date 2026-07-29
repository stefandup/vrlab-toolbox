import io
import logging

import numpy as np
import pandas as pd

from mooi_toolbox.processing.behaviour import RawBehaviourData

logger = logging.getLogger(__name__)


class TPProcessingError(Exception):
    """Raised when Target processing fails."""


class FohTargetBehaviour(RawBehaviourData):
    filename_glob = "xdf"


def run_processing(
    FOH_target_df: pd.DataFrame, vr_intervals: dict[str, tuple[float, float]]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Process text data received from lsl for FOH behavioural targets"""
    # TODO: Consider logging what is dropped in the na below
    # TODO: examine a better way of checking the hdr.
    expected_hdr = "TimeSpawned,TimeHit,HitLatency,TargetType"
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
    filtered_FOH_target_df = filtered_FOH_target_df[~filtered_FOH_target_df["FOH_target"].isna()]

    # Concatenate target_csvdata_df with FOH_target_df["time_stamps"] horizontally
    try:
        target_csvdata_df = pd.concat(
            [target_csvdata_df, filtered_FOH_target_df[["time_stamps"]].reset_index(drop=True)],
            axis=1,
        )
    except (KeyError, TypeError, IndexError) as e:
        raise TPProcessingError("Error in time stamps") from e

    for interval_id, interval in vr_intervals.items():
        # TODO: This should be removed.
        if interval_id == "Complete":
            print(f"Skipping {interval_id}")
            continue

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
