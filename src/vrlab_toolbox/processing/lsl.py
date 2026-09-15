import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pyxdf

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat

logger = logging.getLogger(__name__)


@dataclass
class LslEventSpecification:
    stream: Literal["VR_markers", "VR_trial_events"]
    column: str
    event: str | int
    offset_seconds: float = 0


@dataclass
class LslIntervalSpecifications:
    start: LslEventSpecification
    end: LslEventSpecification
    start_fallback: LslEventSpecification | None = None
    end_fallback: LslEventSpecification | None = None


# TODO: generalize or move out!
class FohLslPhysiologyDataImportStrategy:
    input_data_file_format = PhysiologyFileFormat.LSL
    output_data_type = RawBioData

    def run(self, config_in: ParticipantConfig) -> RawBioData:
        streams_to_get = ["OpenSignals", "VR_markers"]

        streams, _ = pyxdf.load_xdf(config_in.physiology_fn)
        selected_lsl_physiology_streams_dfs = gather_xdf_data_streams(streams, streams_to_get)
        missing_streams = set(streams_to_get) - set(selected_lsl_physiology_streams_dfs.keys())

        if has_missing_requirements(missing_streams, ["OpenSignals"]):
            logger.warning(f"Missing physiology data - {missing_streams}")
            return RawBioData()

        df_dict_out = {
            "EDA": selected_lsl_physiology_streams_dfs["OpenSignals"].copy(),
            "ECG": selected_lsl_physiology_streams_dfs["OpenSignals"].copy(),
        }

        if not has_missing_requirements(missing_streams, ["VR_markers"]):
            marker_df_dict = {
                "VR_markers": selected_lsl_physiology_streams_dfs["VR_markers"].copy()
            }
            df_dict_out.update(marker_df_dict)

        # Note when imported like this, the labels are regularized.

        physiology_data_out = RawBioData(raw_data=df_dict_out)
        physiology_data_out.raw_data["EDA"] = physiology_data_out.raw_data["EDA"].drop(
            columns="ECG"
        )
        physiology_data_out.raw_data["ECG"] = physiology_data_out.raw_data["ECG"].drop(
            columns="EDA"
        )

        return physiology_data_out


class xdfIOException(Exception):
    """Raised when an XDF stream cannot be read or extracted."""


def has_missing_requirements(missing: set, required: list[str]) -> bool:
    return any(stream in missing for stream in required)


def create_intervals_from_df(marker_df: pd.DataFrame):
    return [
        (marker_df["time_stamps"].iloc[i], marker_df["time_stamps"].iloc[i + 1])
        for i in range(len(marker_df) - 1)
    ]


def cut_df_per_interval(start_end_in: tuple, timestamped_df_in: pd.DataFrame):
    start, end = start_end_in

    mask = (timestamped_df_in["time_stamps"] >= start) & (timestamped_df_in["time_stamps"] <= end)

    return timestamped_df_in.loc[mask]


def divide_df_into_blocks(time_in_seconds, timestamped_df_in):
    df_list_out = []
    t_min = timestamped_df_in["time_stamps"].min()
    t_max = timestamped_df_in["time_stamps"].max()

    time_markers = np.arange(t_min, t_max, time_in_seconds)

    for i in range(len(time_markers)):
        start = time_markers[i]
        end = time_markers[i + 1] if i + 1 < len(time_markers) else t_max
        mask = (timestamped_df_in["time_stamps"] >= start) & (
            timestamped_df_in["time_stamps"] <= end
        )
        df_list_out.append(timestamped_df_in.loc[mask])

    return df_list_out


def log_column_names(stream):
    channels = stream["info"]["desc"][0]["channels"][0]["channel"]
    column_names = [channel["label"][0] for channel in channels]
    logger.info(f"Column Names for: {column_names}")


def extract_single_stream(streams: list, stream_name: str) -> tuple[pd.DataFrame, dict]:
    """Extract the time series and time stamps from a specified stream in xdf data."""
    for s in streams:
        if s["info"]["name"][0] == stream_name:
            single_stream = s
            single_stream_time_series = np.array(single_stream["time_series"])

            single_stream_time_stamps = np.array(single_stream["time_stamps"])

            # Make dataframe
            single_stream_df = pd.DataFrame(single_stream_time_series)
            # Add timestamps
            single_stream_df["time_stamps"] = single_stream_time_stamps

            return single_stream_df, single_stream
    raise xdfIOException(f"Could not find XDF stream {stream_name!r}")


def add_column_names(single_stream_df: pd.DataFrame, single_stream: dict):
    """Add column names to the single stream dataframes."""

    # Check if channel description exists and is valid
    try:
        if (
            single_stream["info"]["desc"][0] is not None
            and "channels" in single_stream["info"]["desc"][0]
        ):
            channels = single_stream["info"]["desc"][0]["channels"][0]["channel"]
            column_names = [channel["label"][0] for channel in channels]
            logger.info(f"Column names from metadata: {column_names}")

        else:
            raise KeyError("No valid channel description")

    except (KeyError, TypeError, IndexError):
        # Create column names if they aren't provided
        channel_count = int(single_stream["info"]["channel_count"][0])
        stream_name = single_stream["info"]["name"][0]
        column_names = [f"{stream_name}_ch{i + 1}" for i in range(channel_count)]
        logger.warning(
            f"Channel labels not available for {stream_name}. Using generic names: {column_names}"
        )

    # Apply the column names
    num_cols = len(column_names)
    single_stream_df.columns = column_names + list(single_stream_df.columns[num_cols:])

    return single_stream_df


def get_sampling_rate(single_stream: dict):
    return float(single_stream["info"]["nominal_srate"][0])


def get_start_time(header):
    return datetime.fromisoformat(header["info"]["datetime"][0])


def get_subject_id(xdf_fn: Path) -> str:
    return str(os.path.basename(xdf_fn).split("_")[0]).replace("sub-", "")


def gather_xdf_data_streams(streams: list, stream_ids: list[str]) -> dict[str, pd.DataFrame]:

    dict_out = dict()

    for stream_id in stream_ids:
        try:
            df_out, biosignals_stream = extract_single_stream(streams, stream_id)
            df_out = add_column_names(df_out, biosignals_stream)
            dict_out.update({stream_id: df_out})

        except xdfIOException:
            logger.warning(
                "Error loading data from stream ID: %s. Skipping...",
                stream_id,
            )
            continue

    return dict_out


def all_lsl_streams_empty(lsl_streams_in: dict):
    return all(stream.empty for stream in lsl_streams_in.values())
