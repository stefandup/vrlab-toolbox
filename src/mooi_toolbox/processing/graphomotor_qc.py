from __future__ import annotations

import logging

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from mooi_toolbox.processing.graphomotor_xdf import (
    XdfStream,
    find_largest_stream,
    get_n_samples,
    get_stream_name,
    get_stream_type,
    is_continuous_neon_gaze_stream,
    is_ecg_stream,
    is_eda_stream,
    is_eeg_stream,
    is_pen_stream,
    stream_to_dataframe,
)

logger = logging.getLogger(__name__)


def plot_stream_presence_timeline(
    streams: list[XdfStream],
    subject_id: str,
    summary_row: pd.Series | None = None,
) -> Figure | None:
    rows = []
    global_start: float | None = None

    for stream in streams:
        time_stamps = stream.get("time_stamps", [])
        if len(time_stamps) < 2:
            continue

        try:
            start = float(time_stamps[0])
            end = float(time_stamps[-1])
        except (TypeError, ValueError):
            continue

        if end <= start:
            continue

        global_start = start if global_start is None else min(global_start, start)
        rows.append(
            {
                "label": f"{get_stream_name(stream)} ({get_stream_type(stream)})",
                "start": start,
                "end": end,
                "samples": get_n_samples(stream),
            }
        )

    if not rows or global_start is None:
        return None

    key_rows = []
    for label, predicate in (
        ("Pen/iPad", is_pen_stream),
        ("Neon gaze", is_continuous_neon_gaze_stream),
        ("EEG", is_eeg_stream),
        ("EDA", is_eda_stream),
        ("ECG", is_ecg_stream),
    ):
        stream = find_largest_stream(streams, predicate)

        if stream is not None and len(stream.get("time_stamps", [])) >= 2:
            time_stamps = stream["time_stamps"]
            key_rows.append(
                {
                    "label": (
                        f"KEY: {label} — {get_stream_name(stream)} "
                        f"({get_stream_type(stream)})"
                    ),
                    "start": float(time_stamps[0]),
                    "end": float(time_stamps[-1]),
                    "samples": get_n_samples(stream),
                }
            )
        else:
            key_rows.append(
                {
                    "label": f"KEY: {label} — MISSING IN SELECTED XDF",
                    "start": global_start,
                    "end": global_start,
                    "samples": 0,
                }
            )

    key_label_names = [row["label"] for row in key_rows]
    other_rows = [
        row
        for row in sorted(rows, key=lambda item: item["start"])
        if not any(row["label"] in key_label for key_label in key_label_names)
    ]
    plot_rows = key_rows + other_rows

    fig_height = max(5, min(14, 0.45 * len(plot_rows)))
    fig, ax = plt.subplots(figsize=(13, fig_height))

    for i, row in enumerate(plot_rows):
        start = row["start"] - global_start
        width = max(row["end"] - row["start"], 0)

        if row["samples"] > 0 and width > 0:
            ax.barh(i, width, left=start, height=0.55)
            ax.text(start + width, i, f"  {row['samples']} samples", va="center", fontsize=8)
        else:
            ax.scatter([0], [i], marker="x", s=45)
            ax.text(0, i, "  missing / 0 samples", va="center", fontsize=8)

    ax.set_yticks(np.arange(len(plot_rows)))
    ax.set_yticklabels([row["label"] for row in plot_rows], fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Seconds from first stream start in selected XDF")

    title = f"{subject_id}: selected XDF stream presence timeline"
    if summary_row is not None:
        title += f" — {summary_row.get('Selection_Label', '')}"
        if str(summary_row.get("QC_Status", "")) != "OK":
            title += f" — {summary_row.get('QC_Status', '')}"

    ax.set_title(title)
    fig.tight_layout()
    return fig


def find_channel_column(dataframe: pd.DataFrame, wanted: str) -> str | None:
    wanted_lower = wanted.lower()

    for column in dataframe.columns:
        if column.lower() == wanted_lower:
            return column

    for column in dataframe.columns:
        normalized = column.lower().replace(" ", "").replace("_", "")
        if normalized == wanted_lower:
            return column

    return None


def plot_c3_c4_eeg_preview(
    eeg_stream: XdfStream | None,
    subject_id: str,
) -> Figure | None:
    if eeg_stream is None or get_n_samples(eeg_stream) == 0:
        logger.info(
            "No C3/C4 EEG preview made for %s because selected XDF has no EEG.",
            subject_id,
        )
        return None

    try:
        dataframe = stream_to_dataframe(eeg_stream)
    except (ValueError, TypeError) as error:
        logger.info("Could not convert EEG stream to dataframe for %s: %s", subject_id, error)
        return None

    channels_to_plot = [
        column
        for channel in ("C3", "C4")
        if (column := find_channel_column(dataframe, channel)) is not None
    ]

    if not channels_to_plot:
        logger.info(
            "No C3/C4 columns found for %s. Available columns: %s",
            subject_id,
            list(dataframe.columns),
        )
        return None

    max_points = min(15000, len(dataframe))
    plot_df = dataframe.iloc[:max_points].copy()

    time_sec = pd.to_numeric(plot_df["time_stamps"], errors="coerce")
    if time_sec.notna().sum() < 2:
        time_sec = pd.Series(np.arange(len(plot_df)), index=plot_df.index)
    else:
        time_sec = time_sec - time_sec.iloc[0]

    fig, ax = plt.subplots(figsize=(13, 5))

    for column in channels_to_plot:
        signal = pd.to_numeric(plot_df[column], errors="coerce")
        if signal.notna().sum() < 5:
            continue
        ax.plot(time_sec, signal, linewidth=0.8, label=column)

    ax.set_xlabel("Seconds from EEG start in selected XDF")
    ax.set_ylabel("Raw EEG amplitude")
    ax.set_title(
        f"{subject_id}: raw EEG C3/C4 preview from selected XDF "
        f"({get_n_samples(eeg_stream)} samples)"
    )
    ax.legend(loc="best")
    fig.tight_layout()
    return fig


def plot_raw_eeg_preview(
    eeg_stream: XdfStream | None,
    subject_id: str,
) -> Figure | None:
    if eeg_stream is None or get_n_samples(eeg_stream) == 0:
        logger.info("No raw EEG preview made for %s because selected XDF has no EEG.", subject_id)
        return None

    try:
        dataframe = stream_to_dataframe(eeg_stream)
    except (ValueError, TypeError) as error:
        logger.info("Could not convert EEG stream to dataframe for %s: %s", subject_id, error)
        return None

    eeg_columns = [column for column in dataframe.columns if column != "time_stamps"]
    if not eeg_columns:
        logger.info("No EEG columns found for raw EEG preview for %s.", subject_id)
        return None

    plot_columns = eeg_columns[: min(8, len(eeg_columns))]
    max_points = min(3000, len(dataframe))
    plot_df = dataframe.iloc[:max_points].copy()

    time_sec = pd.to_numeric(plot_df["time_stamps"], errors="coerce")
    if time_sec.notna().sum() < 2:
        time_sec = pd.Series(np.arange(len(plot_df)), index=plot_df.index)
    else:
        time_sec = time_sec - time_sec.iloc[0]

    fig, ax = plt.subplots(figsize=(12, 6))
    offset = 0.0
    plotted = 0

    for column in plot_columns:
        signal = pd.to_numeric(plot_df[column], errors="coerce")
        if signal.notna().sum() < 5:
            continue

        signal = signal - np.nanmedian(signal)
        spread = float(np.nanpercentile(np.abs(signal), 95))
        if spread <= 0 or not np.isfinite(spread):
            spread = 1.0

        ax.plot(time_sec, signal / spread + offset, linewidth=0.8, label=column)
        offset += 3.0
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        logger.info("No usable numeric EEG columns found for raw EEG preview for %s.", subject_id)
        return None

    ax.set_xlabel("Seconds from EEG start in selected XDF")
    ax.set_ylabel("Channels, scaled and offset")
    ax.set_title(
        f"{subject_id}: raw EEG preview from selected XDF "
        f"({get_n_samples(eeg_stream)} samples, first {max_points} shown)"
    )
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    fig.tight_layout()
    return fig
