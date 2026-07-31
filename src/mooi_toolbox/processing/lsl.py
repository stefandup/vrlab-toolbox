import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pyxdf

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LslParticipantConfig(ParticipantConfig):
    streams_to_run: dict[str, pd.DataFrame]
    missing_streams: set[str]

    @classmethod
    def from_lsl_data(
        cls,
        id_in: str,
        data_folder_in: Path,
        lsl_streams_to_get: list[str],
        physiology_data_type_in: PhysiologyFileFormat,
        behav_folder_in: Path | None = None,
        output_folder_in: Path | None = None,
        log_folder_in: Path | None = None,
        verbose: bool = False,
        show_plots: bool = False,
    ):

        if behav_folder_in is None:
            behav_folder_in = data_folder_in

        if output_folder_in is None:
            output_folder_in = data_folder_in / "output"

        output_folder_in.mkdir(parents=True, exist_ok=True)

        if log_folder_in is None:
            log_folder_in = output_folder_in / "logs"

        log_folder_in.mkdir(parents=True, exist_ok=True)
        stream_sets_to_run: list[dict[str, pd.DataFrame]] = []
        for xdf_path in data_folder_in.rglob(f"*{id_in}*{physiology_data_type_in.value}"):
            print(f"Found {xdf_path}")
            streams: list[dict]

            streams, _ = pyxdf.load_xdf(xdf_path)

            selected_lsl_streams_dfs = gather_xdf_data_streams(streams, lsl_streams_to_get)
            file_to_run_key = str(xdf_path.name).split("_")[-1]

            if file_to_run_key != "eeg.xdf":
                logger.warning(
                    f"{xdf_path} seems to be an old run as it ends on {file_to_run_key}.Skipping..."
                )
                continue

            if all_streams_empty(selected_lsl_streams_dfs):
                logger.warning(f"All streams empty for path {xdf_path}. Skipping...")
                continue
            print(f"Storing {xdf_path}")

            stream_sets_to_run.append(selected_lsl_streams_dfs)

        if len(stream_sets_to_run) > 0:
            logger.warning(
                f"Multiple sets for subject {id_in}. Chosing last one: {stream_sets_to_run[-1]}"
            )

        streams_out: dict[str, pd.DataFrame] = stream_sets_to_run[-1]
        missing_streams_out = set(lsl_streams_to_get) - set(streams_out.keys())

        if missing_streams_out:
            logger.warning(f"Missing streams {missing_streams_out} for {id_in}")

        # TODO: Make Crane config as well to avoid all these empties
        return cls(
            subject_id=id_in,
            physiology_fn="",
            physiology_data_type=physiology_data_type_in,
            data_folder=data_folder_in,
            behav_folder=behav_folder_in,
            _behaviour_file_names=dict(),
            log_folder=log_folder_in,
            output_folder=output_folder_in,
            verbose=verbose,
            show_plots=show_plots,
            streams_to_run=streams_out,
            missing_streams=missing_streams_out,
        )


class LslPhysiologyDataImportStrategy:
    input_data_file_format = PhysiologyFileFormat.LSL
    output_data_type = RawBioData

    def run(self, config_in: LslParticipantConfig) -> RawBioData:
        if has_missing_requirements(config_in.missing_streams, ["OpenSignals"]):
            logger.warning("Missing physiology data.")
            return RawBioData()

        return RawBioData(raw_data={"OpenSignals": config_in.streams_to_run["OpenSignals"]})


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


def print_column_names(stream):
    channels = stream["info"]["desc"][0]["channels"][0]["channel"]
    column_names = [channel["label"][0] for channel in channels]
    print(f"Column Names for: {column_names}")


def extract_single_stream(streams: list, stream_name: str) -> tuple[pd.DataFrame, dict]:
    """Extract the time series and time stamps from a specified stream in xdf data."""
    for s in streams:
        if s["info"]["name"][0] == stream_name:
            single_stream = s
            single_stream_time_series = np.array(single_stream["time_series"])
            # print("sample time series:", single_stream_time_series[:5])
            single_stream_time_stamps = np.array(single_stream["time_stamps"])
            # print("sample time stamps:", single_stream_time_stamps[:5])

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
            print("Column names from metadata:", column_names)

        else:
            raise KeyError("No valid channel description")

    except (KeyError, TypeError, IndexError):
        # Create column names if they aren't provided
        channel_count = int(single_stream["info"]["channel_count"][0])
        stream_name = single_stream["info"]["name"][0]
        column_names = [f"{stream_name}_ch{i + 1}" for i in range(channel_count)]
        print(f"Channel labels not available for {stream_name}. Using generic names:", column_names)

    # Apply the column names
    num_cols = len(column_names)
    single_stream_df.columns = column_names + list(single_stream_df.columns[num_cols:])

    return single_stream_df


def get_sampling_rate(single_stream: dict):
    return float(single_stream["info"]["nominal_srate"][0])


def get_start_time(header):
    return datetime.fromisoformat(header["info"]["datetime"][0])


def get_subject_id(xdf_fn: Path) -> str:
    return os.path.basename(xdf_fn).split("_")[0]


def gather_xdf_data_streams(streams: list, stream_ids: list) -> dict:

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


def all_streams_empty(lsl_streams_in: dict):
    return all(stream.empty for stream in lsl_streams_in.values())
