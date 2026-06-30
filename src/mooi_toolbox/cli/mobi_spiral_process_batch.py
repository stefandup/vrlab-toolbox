import click
import logging
import os
from pathlib import Path

import pandas as pd

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.eeg import run_spiral_eeg_processing, EEGProcessingError
from mooi_toolbox.processing.plot_utils import save_plot
from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf

logger = logging.getLogger(__name__)

EDA_COLUMN_NAMES = ["EDA", "EDA0", "GSR", "GSR0"]


def get_stream_name(stream) -> str:
    return stream["info"]["name"][0]


def get_stream_type(stream) -> str:
    return stream["info"].get("type", [""])[0]


def get_effective_srate(stream) -> float:
    time_stamps = stream.get("time_stamps", [])

    if len(time_stamps) < 2:
        return 0

    duration = time_stamps[-1] - time_stamps[0]

    if duration <= 0:
        return 0

    return len(time_stamps) / duration


def get_column_names_from_stream(stream) -> list[str]:
    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        return [channel["label"][0] for channel in channels]
    except Exception:
        time_series = stream.get("time_series", [])

        if len(time_series) == 0:
            return []

        first_sample = time_series[0]

        if hasattr(first_sample, "__len__"):
            n_channels = len(first_sample)
        else:
            n_channels = 1

        return [f"channel_{i}" for i in range(n_channels)]


def stream_to_dataframe(stream) -> pd.DataFrame:
    column_names = get_column_names_from_stream(stream)

    if len(column_names) == 0:
        raise ValueError("Stream has no samples or no channel names.")

    df = pd.DataFrame(
        stream["time_series"],
        columns=column_names,
    )

    df.insert(0, "time_stamps", stream["time_stamps"])

    return df


def find_eda_stream(streams):
    for stream in streams:
        if len(stream.get("time_series", [])) == 0:
            continue

        column_names = get_column_names_from_stream(stream)

        for column in column_names:
            if column in EDA_COLUMN_NAMES:
                return stream, column

    return None, None


def find_eeg_stream(streams):
    for stream in streams:
        if len(stream.get("time_series", [])) == 0:
            continue

        stream_name = get_stream_name(stream).lower()
        stream_type = get_stream_type(stream).lower()

        if stream_name == "eeg" or stream_type == "eeg":
            return stream

    return None


def find_ipad_stream(streams):
    for stream in streams:
        if len(stream.get("time_series", [])) == 0:
            continue

        stream_name = get_stream_name(stream).lower()
        stream_type = get_stream_type(stream).lower()

        if (
            "mindlogger" in stream_name
            or "live_event" in stream_name
            or "live_event" in stream_type
            or "drawing" in stream_name
        ):
            return stream

    return None


def has_spiral_markers(streams) -> bool:
    return find_ipad_stream(streams) is not None


def score_xdf_streams(streams) -> int:
    score = 0

    for stream in streams:
        stream_name = get_stream_name(stream).lower()
        stream_type = get_stream_type(stream).lower()
        n_samples = len(stream.get("time_series", []))

        if n_samples == 0:
            continue

        if stream_name == "eeg" or stream_type == "eeg":
            score += 1000

        if "opensignals" in stream_name:
            score += 500

        if "mindlogger" in stream_name or "live_event" in stream_type:
            score += 300

        if "neon" in stream_name:
            score += 100

        if n_samples > 10000:
            score += 100

    return score


def find_best_xdf_files(root: Path, verbose: bool = False) -> list[Path]:
    best_files = {}

    for xdf_fn in root.rglob("*.xdf"):
        subject_id = xdf_io.get_subject_id(xdf_fn)

        try:
            streams = get_and_check_xdf(xdf_fn, verbose=False)
        except Exception as error:
            logger.warning(
                "Skipping %s because XDF could not be loaded: %s",
                xdf_fn.name,
                error,
            )
            continue

        score = score_xdf_streams(streams)

        if verbose:
            logger.info(
                "XDF candidate subject=%s file=%s score=%s",
                subject_id,
                xdf_fn.name,
                score,
            )

        if score == 0:
            continue

        if subject_id not in best_files:
            best_files[subject_id] = {
                "xdf_fn": xdf_fn,
                "score": score,
            }
        elif score > best_files[subject_id]["score"]:
            best_files[subject_id] = {
                "xdf_fn": xdf_fn,
                "score": score,
            }

    return [item["xdf_fn"] for item in best_files.values()]


def process_eda_stream(
    stream,
    eda_column: str,
    subject_id: str,
    output_folder: str,
) -> pd.DataFrame:
    eda_raw_timestamped = stream_to_dataframe(stream)

    if eda_column != "EDA":
        eda_raw_timestamped = eda_raw_timestamped.rename(
            columns={eda_column: "EDA"}
        )

    sampling_rate = get_effective_srate(stream)

    if sampling_rate <= 0:
        sampling_rate = 1000

    logger.info("Processing EDA with sampling rate %.3f Hz", sampling_rate)

    eda_proc_out = eda.run_nk_eda_processing(
        eda_raw_timestamped["EDA"],
        sampling_rate=sampling_rate,
    )

    eda_data_out = eda.get_eda_data_out(
        eda_proc_out,
        interval_label="FullRecording_",
    )

    fig = eda.plot_eda(
        eda_raw_timestamped=eda_raw_timestamped,
        scr_participant_data=eda_data_out,
        nk_complete_ts_out=eda_proc_out,
        vr_intervals=None,
        show_plots=False,
    )

    try:
        save_plot(
            fig,
            output_folder,
            subject_id,
            f"Subject {subject_id} EDA QC",
        )
    except AttributeError as error:
        logger.info("Error saving EDA plot: %s", error)

    return eda_data_out


@click.command()
@click.argument(
    "input_folder",
    type=click.Path(exists=True, dir_okay=True),
    required=True,
)
@click.argument(
    "output_folder",
    type=click.Path(exists=True, dir_okay=True),
    required=True,
)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: str, output_folder: str, verbose: bool):
    """CLI tool for batch processing spiral task EEG and EDA data."""

    logger.info(
        "Looking into input folder: %s. Output folder: %s",
        input_folder,
        output_folder,
    )

    out_fn = os.path.join(
        output_folder,
        "spiral_process_batch_out.csv",
    )

    root = Path(input_folder)
    out_file_parts = []

    best_xdf_files = find_best_xdf_files(root, verbose=verbose)

    if len(best_xdf_files) == 0:
        logger.warning("No usable XDF files found.")
        return

    for xdf_fn in best_xdf_files:
        subject_id = xdf_io.get_subject_id(xdf_fn)

        mobi_logging.log_section(logger, f"Subject {subject_id}")

        try:
            streams = get_and_check_xdf(xdf_fn, verbose=False)
        except Exception as error:
            logger.warning(
                "Skipping %s because XDF could not be loaded: %s",
                xdf_fn.name,
                error,
            )
            continue

        if not has_spiral_markers(streams):
            logger.info(
                "Skipping %s because it does not contain iPad / spiral markers.",
                xdf_fn.name,
            )
            continue

        logger.info(
            "Selected XDF for subject %s: %s",
            subject_id,
            xdf_fn.name,
        )

        eda_stream, eda_column = find_eda_stream(streams)
        eeg_stream = find_eeg_stream(streams)

        logger.info("EDA found: %s %s", eda_stream is not None, eda_column)
        logger.info("EEG found: %s", eeg_stream is not None)
        logger.info("iPad markers found: %s", has_spiral_markers(streams))

        participant_parts = []

        if eda_stream is not None:
            try:
                eda_data_out = process_eda_stream(
                    stream=eda_stream,
                    eda_column=eda_column,
                    subject_id=subject_id,
                    output_folder=output_folder,
                )

                participant_parts.append(eda_data_out.reset_index(drop=True))
                logger.info("Done EDA for subject %s", subject_id)

            except Exception as error:
                logger.warning(
                    "Skipping EDA for subject %s because processing failed: %s",
                    subject_id,
                    error,
                )
        else:
            logger.warning("No EDA stream found for subject %s", subject_id)

        if eeg_stream is not None:
            try:
                eeg_proc_out = run_spiral_eeg_processing(
                    eeg_stream=eeg_stream,
                    streams=streams,
                    subject_id=subject_id,
                    show_plots=False,
                )

                eeg_data_out = eeg_proc_out["summary_data"]

                try:
                    save_plot(
                        eeg_proc_out["qc_figure"],
                        output_folder,
                        subject_id,
                        f"Subject {subject_id} Spiral EEG QC",
                    )

                    save_plot(
                        eeg_proc_out["all_channels_figure"],
                        output_folder,
                        subject_id,
                        f"Subject {subject_id} EEG All Channels Entire Run",
                    )

                except AttributeError as error:
                    logger.info("Error saving EEG plot: %s", error)

                participant_parts.append(eeg_data_out.reset_index(drop=True))
                logger.info("Done spiral EEG for subject %s", subject_id)

            except EEGProcessingError as error:
                logger.warning(
                    "Skipping EEG for subject %s because processing failed: %s",
                    subject_id,
                    error,
                )
            except Exception as error:
                logger.warning(
                    "Skipping EEG for subject %s because processing failed: %s",
                    subject_id,
                    error,
                )
        else:
            logger.warning("No EEG stream found for subject %s", subject_id)

        if len(participant_parts) == 0:
            logger.warning("No spiral output for subject %s", subject_id)
            continue

        participant_data_out = pd.concat(participant_parts, axis=1)

        for column in ["Subject_ID", "XDF_File"]:
            if column in participant_data_out.columns:
                participant_data_out = participant_data_out.drop(columns=[column])

        participant_data_out.insert(0, "XDF_File", xdf_fn.name)
        participant_data_out.insert(0, "Subject_ID", subject_id)

        out_file_parts.append(participant_data_out)

    if len(out_file_parts) == 0:
        logger.warning("No files were successfully processed.")
        return

    out_df = pd.concat(out_file_parts, axis=0)
    out_df.to_csv(out_fn, index=False)

    logger.info("Saved output to %s", out_fn)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()