from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.graphomotor_qc import (
    plot_c3_c4_eeg_preview,
    plot_raw_eeg_preview,
    plot_stream_presence_timeline,
)
from mooi_toolbox.processing.graphomotor_task import GraphomotorTaskProcessor
from mooi_toolbox.processing.graphomotor_xdf import (
    XdfStream,
    add_qc_flags,
    choose_best_xdfs,
    find_eda_stream_and_column,
    find_largest_stream,
    is_eeg_stream,
    load_subject_xdf_candidates,
    stream_to_dataframe,
)

logger = logging.getLogger(__name__)


@dataclass
class GraphomotorPipelineOutputData:
    subject_id: str
    candidate_df_out: pd.DataFrame = field(default_factory=pd.DataFrame)
    selected_df_out: pd.DataFrame = field(default_factory=pd.DataFrame)
    processing_df_out: pd.DataFrame = field(default_factory=pd.DataFrame)
    figure_data_out: dict[str, Figure] = field(default_factory=dict)


def process_full_recording_eda(
    stream: XdfStream,
    eda_column: str,
    subject_id: str,
) -> tuple[pd.DataFrame, Figure]:
    eda_raw_timestamped = stream_to_dataframe(stream)

    if eda_column != "EDA":
        eda_raw_timestamped = eda_raw_timestamped.rename(columns={eda_column: "EDA"})

    time_stamps = eda_raw_timestamped["time_stamps"]
    sampling_rate = 0.0

    if len(time_stamps) >= 2:
        duration = float(time_stamps.iloc[-1] - time_stamps.iloc[0])
        if duration > 0:
            sampling_rate = len(time_stamps) / duration

    if sampling_rate <= 0:
        sampling_rate = 1000.0

    logger.info(
        "Processing EDA for %s with sampling rate %.3f Hz",
        subject_id,
        sampling_rate,
    )

    eda_proc_out = eda.run_nk_eda_processing(
        eda_raw_timestamped["EDA"],
        sampling_rate=sampling_rate,
    )
    eda_data_out = eda.get_eda_data_out(
        eda_proc_out,
        interval_label="FullRecording_",
    )
    eda_figure = eda.plot_eda(
        eda_raw_timestamped=eda_raw_timestamped,
        scr_participant_data=eda_data_out,
        nk_complete_ts_out=eda_proc_out,
        vr_intervals=None,
        show_plots=False,
    )

    return eda_data_out, eda_figure


def _build_processing_output(
    subject_id: str,
    xdf_fn: Path,
    parts: list[pd.DataFrame],
) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()

    output = pd.concat(
        [part.reset_index(drop=True) for part in parts],
        axis=1,
    )
    output = output.drop(
        columns=["Subject_ID", "XDF_File"],
        errors="ignore",
    )
    output.insert(0, "XDF_File", xdf_fn.name)
    output.insert(0, "Subject_ID", subject_id)
    return output


def run_pipeline(
    participant_id_in: str,
    data_folder_in: Path,
    task_processor: GraphomotorTaskProcessor,
    output_folder_in: Path | None = None,
    skip_heavy_processing: bool = False,
    verbose: bool = False,
) -> GraphomotorPipelineOutputData:
    """Process exactly one graphomotor participant.

    XDF selection and generic recording QC are shared across graphomotor tasks.
    Task-specific processing is delegated to ``task_processor``.
    """
    del output_folder_in

    output = GraphomotorPipelineOutputData(subject_id=participant_id_in)
    logger.info("Graphomotor task: %s", task_processor.task_name)

    candidates_df, streams_by_path = load_subject_xdf_candidates(
        data_folder_in,
        participant_id_in,
        verbose=verbose,
    )
    output.candidate_df_out = candidates_df

    if candidates_df.empty:
        logger.warning("No usable XDF files found for %s.", participant_id_in)
        return output

    selected_df = add_qc_flags(choose_best_xdfs(candidates_df))
    output.selected_df_out = selected_df

    if selected_df.empty:
        logger.warning("No XDF selected for %s.", participant_id_in)
        return output

    selected_row = selected_df.iloc[0]
    xdf_fn = Path(selected_row["XDF_Path"])
    streams = streams_by_path.get(xdf_fn)

    if streams is None:
        try:
            streams = get_and_check_xdf(xdf_fn, verbose=False)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
            logger.warning(
                "Could not reload selected XDF %s: %s",
                xdf_fn.name,
                error,
            )
            return output

    logger.info(
        "Selected XDF for %s: %s",
        participant_id_in,
        xdf_fn.name,
    )
    logger.info(
        "Selection status: %s",
        selected_row.get("Selection_Status", ""),
    )
    logger.info(
        "Selection reason: %s",
        selected_row.get("Selection_Reason", ""),
    )
    logger.info(
        "Selection label: %s",
        selected_row.get("Selection_Label", ""),
    )

    timeline_figure = plot_stream_presence_timeline(
        streams,
        participant_id_in,
        summary_row=selected_row,
    )
    if timeline_figure is not None:
        output.figure_data_out["selected_stream_presence_timeline"] = timeline_figure

    eeg_stream = find_largest_stream(streams, is_eeg_stream)

    raw_eeg_figure = plot_raw_eeg_preview(
        eeg_stream,
        participant_id_in,
    )
    if raw_eeg_figure is not None:
        output.figure_data_out["raw_eeg_preview"] = raw_eeg_figure

    c3_c4_figure = plot_c3_c4_eeg_preview(
        eeg_stream,
        participant_id_in,
    )
    if c3_c4_figure is not None:
        output.figure_data_out["raw_eeg_C3_C4_selected_xdf"] = c3_c4_figure

    if skip_heavy_processing:
        return output

    processing_parts: list[pd.DataFrame] = []

    eda_stream, eda_column = find_eda_stream_and_column(streams)

    if eda_stream is not None and eda_column is not None:
        try:
            eda_output, eda_figure = process_full_recording_eda(
                eda_stream,
                eda_column,
                participant_id_in,
            )
            processing_parts.append(eda_output)
            output.figure_data_out["EDA_QC"] = eda_figure
        except eda.EDAProcessingError as error:
            logger.warning(
                "Skipping EDA processing for %s: %s",
                participant_id_in,
                error,
            )
        except (ValueError, TypeError, KeyError) as error:
            logger.warning(
                "Could not prepare EDA for %s: %s",
                participant_id_in,
                error,
            )
    elif eda_stream is not None:
        logger.info(
            "EDA-like stream found for %s, but no clear EDA column name was found.",
            participant_id_in,
        )

    task_result = task_processor.run(
        streams,
        participant_id_in,
    )

    if not task_result.summary_data.empty:
        processing_parts.append(task_result.summary_data)

    output.figure_data_out.update(task_result.figure_data_out)

    output.processing_df_out = _build_processing_output(
        participant_id_in,
        xdf_fn,
        processing_parts,
    )

    return output
