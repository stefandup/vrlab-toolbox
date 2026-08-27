from __future__ import annotations

import logging
from typing import TypedDict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from mooi_toolbox.processing.eeg import (
    BAD_CHANNELS,
    EEGProcessingError,
    bandpower_welch,
    clean_eeg,
    get_channel_names,
    get_effective_srate,
    get_interval_signal,
    safe_float_array,
)
from mooi_toolbox.processing.graphomotor_task import GraphomotorTaskResult
from mooi_toolbox.processing.graphomotor_xdf import (
    XdfStream,
    find_largest_stream,
    get_pen_movement_intervals,
    is_eeg_stream,
    is_pen_stream,
)

logger = logging.getLogger(__name__)

MOTOR_CHANNELS = ["C3", "C4"]
ALPHA_BAND = (8, 12)
BETA_BAND = (13, 30)
MIN_DRAWING_INTERVAL_SEC = 2.0
MIN_SWITCH_PAUSE_SEC = 8.0
DOWNSAMPLE_FACTOR = 10
Y_SCALE_UV = 300


class SpiralEEGProcessingResult(TypedDict):
    summary_data: pd.DataFrame
    qc_figure: Figure
    all_channels_figure: Figure


def detect_active_intervals(
    time_sec: np.ndarray,
    active: np.ndarray,
    min_duration: float = MIN_DRAWING_INTERVAL_SEC,
) -> list[tuple[float, float]]:
    intervals = []

    time_sec = np.asarray(time_sec, dtype=float)
    active = np.asarray(active, dtype=bool)

    if len(time_sec) == 0 or not np.any(active):
        return intervals

    active_idx = np.where(active)[0]
    start_idx = active_idx[0]
    previous_idx = active_idx[0]

    for current_idx in active_idx[1:]:
        if current_idx != previous_idx + 1:
            start = time_sec[start_idx]
            end = time_sec[previous_idx]

            if end - start >= min_duration:
                intervals.append((start, end))

            start_idx = current_idx

        previous_idx = current_idx

    start = time_sec[start_idx]
    end = time_sec[previous_idx]

    if end - start >= min_duration:
        intervals.append((start, end))

    return intervals


def detect_switch_from_big_pause(
    drawing_intervals: list[tuple[float, float]],
) -> tuple[float | None, list[tuple[float, float]], list[tuple[float, float]]]:
    if not drawing_intervals:
        return None, [], []

    if len(drawing_intervals) == 1:
        start, end = drawing_intervals[0]
        switch_time = start + ((end - start) / 2)
        return switch_time, [(start, switch_time)], [(switch_time, end)]

    gaps = []

    for i in range(len(drawing_intervals) - 1):
        left_end = drawing_intervals[i][1]
        right_start = drawing_intervals[i + 1][0]
        gap_duration = right_start - left_end
        gaps.append(
            {
                "index": i,
                "left_end": left_end,
                "right_start": right_start,
                "gap_duration": gap_duration,
            }
        )

    big_gaps = [gap for gap in gaps if gap["gap_duration"] >= MIN_SWITCH_PAUSE_SEC]
    chosen_gap = max(big_gaps or gaps, key=lambda item: item["gap_duration"])

    switch_time = chosen_gap["left_end"] + (chosen_gap["gap_duration"] / 2)
    split_idx = chosen_gap["index"] + 1

    dominant_intervals = drawing_intervals[:split_idx]
    nondominant_intervals = drawing_intervals[split_idx:]

    return switch_time, dominant_intervals, nondominant_intervals


def get_drawing_intervals_from_ipad(
    ipad_stream: XdfStream,
    eeg_start_time: float,
) -> tuple[
    float | None,
    list[tuple[float, float]],
    list[tuple[float, float]],
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Detect real Spiral drawing from x/y movement, not non-zero position."""
    intervals_abs, ipad_time_abs, x, y = get_pen_movement_intervals(ipad_stream)

    if len(ipad_time_abs) == 0:
        raise EEGProcessingError("iPad stream has no timestamps.")
    if len(x) == 0 or len(y) == 0:
        raise EEGProcessingError("iPad stream does not contain usable x/y drawing columns.")
    if not intervals_abs:
        raise EEGProcessingError("No sustained Spiral drawing movement detected.")

    ipad_time_eeg = ipad_time_abs - eeg_start_time

    drawing_intervals = [
        (start - eeg_start_time, end - eeg_start_time)
        for start, end in intervals_abs
    ]

    switch_time, dominant_intervals, nondominant_intervals = detect_switch_from_big_pause(
        drawing_intervals
    )

    return (
        switch_time,
        dominant_intervals,
        nondominant_intervals,
        ipad_time_eeg,
        x,
        y,
    )


def get_spiral_eeg_data_out(
    eeg_clean: np.ndarray,
    time_sec: np.ndarray,
    sampling_rate: float,
    channel_names: list[str],
    dominant_intervals: list[tuple[float, float]],
    nondominant_intervals: list[tuple[float, float]],
    switch_time: float | None,
) -> pd.DataFrame:
    """Return one long-format row per motor channel for plotting and export."""

    motor_names = [channel for channel in MOTOR_CHANNELS if channel in channel_names]

    if not motor_names:
        raise EEGProcessingError("No C3/C4 motor channels found.")

    rows: list[dict[str, float | str | None]] = []

    for channel in motor_names:
        channel_idx = channel_names.index(channel)
        signal = eeg_clean[:, channel_idx]

        dominant_signal = get_interval_signal(
            signal,
            time_sec,
            dominant_intervals,
        )
        nondominant_signal = get_interval_signal(
            signal,
            time_sec,
            nondominant_intervals,
        )

        rows.append(
            {
                "channel": channel,
                "Switch_Time_sec": switch_time,
                "dominant_alpha": bandpower_welch(
                    dominant_signal,
                    sampling_rate,
                    ALPHA_BAND,
                ),
                "nondominant_alpha": bandpower_welch(
                    nondominant_signal,
                    sampling_rate,
                    ALPHA_BAND,
                ),
                "dominant_beta": bandpower_welch(
                    dominant_signal,
                    sampling_rate,
                    BETA_BAND,
                ),
                "nondominant_beta": bandpower_welch(
                    nondominant_signal,
                    sampling_rate,
                    BETA_BAND,
                ),
            }
        )

    return pd.DataFrame(rows)


def shade_intervals(
    ax,
    dominant_intervals: list[tuple[float, float]],
    nondominant_intervals: list[tuple[float, float]],
) -> None:
    for start, end in dominant_intervals:
        ax.axvspan(start, end, alpha=0.25)

    for start, end in nondominant_intervals:
        ax.axvspan(start, end, alpha=0.25)


def add_switch_marker(ax, switch_time: float | None) -> None:
    if switch_time is None:
        return

    ax.axvline(switch_time, color="red", linestyle="--", linewidth=1.3)


def plot_spiral_eeg_qc(
    eeg_clean: np.ndarray,
    time_sec: np.ndarray,
    channel_names: list[str],
    ipad_time_sec: np.ndarray,
    ipad_x: np.ndarray,
    ipad_y: np.ndarray,
    summary_data: pd.DataFrame,
    dominant_intervals: list[tuple[float, float]],
    nondominant_intervals: list[tuple[float, float]],
    switch_time: float | None,
    subject_id: str,
    show_plots: bool = False,
) -> Figure:
    duration_sec = time_sec[-1]

    time_ds = time_sec[::DOWNSAMPLE_FACTOR]
    eeg_ds = eeg_clean[::DOWNSAMPLE_FACTOR]
    eeg_ds = eeg_ds - np.nanmean(eeg_ds, axis=0)

    motor_names = [channel for channel in MOTOR_CHANNELS if channel in channel_names]

    fig, axs = plt.subplots(
        4,
        1,
        figsize=(16, 12),
        sharex=False,
        gridspec_kw={"height_ratios": [1.2, 1.3, 1, 1]},
    )

    fig.suptitle(
        f"Spiral Drawing EEG Summary: Dominant vs Non-dominant Hand\nSubject {subject_id}",
        fontsize=16,
        fontweight="bold",
    )

    axs[0].plot(ipad_time_sec, ipad_x, label="iPad x", linewidth=0.8)
    axs[0].plot(ipad_time_sec, ipad_y, label="iPad y", linewidth=0.8)
    shade_intervals(axs[0], dominant_intervals, nondominant_intervals)
    add_switch_marker(axs[0], switch_time)
    axs[0].set_title("iPad drawing signal")
    axs[0].set_ylabel("x / y")
    axs[0].legend(loc="upper right")
    axs[0].set_xlim(0, duration_sec)

    for channel in motor_names:
        channel_idx = channel_names.index(channel)
        axs[1].plot(
            time_ds,
            eeg_ds[:, channel_idx],
            label=f"{channel} EEG",
            linewidth=0.7,
        )

    shade_intervals(axs[1], dominant_intervals, nondominant_intervals)
    add_switch_marker(axs[1], switch_time)
    axs[1].set_title("C3/C4 cleaned EEG")
    axs[1].set_ylabel("µV")
    axs[1].set_ylim(-Y_SCALE_UV, Y_SCALE_UV)
    axs[1].legend(loc="upper right")
    axs[1].set_xlim(0, duration_sec)

    x_pos = np.arange(len(summary_data))
    width = 0.35

    axs[2].bar(
        x_pos - width / 2,
        summary_data["dominant_alpha"],
        width,
        label="Dominant",
    )
    axs[2].bar(
        x_pos + width / 2,
        summary_data["nondominant_alpha"],
        width,
        label="Non-dominant",
    )
    axs[2].set_xticks(x_pos)
    axs[2].set_xticklabels(summary_data["channel"])
    axs[2].set_title("Alpha power: dominant vs non-dominant")
    axs[2].set_ylabel("Alpha power")
    axs[2].legend(loc="upper right")

    axs[3].bar(
        x_pos - width / 2,
        summary_data["dominant_beta"],
        width,
        label="Dominant",
    )
    axs[3].bar(
        x_pos + width / 2,
        summary_data["nondominant_beta"],
        width,
        label="Non-dominant",
    )
    axs[3].set_xticks(x_pos)
    axs[3].set_xticklabels(summary_data["channel"])
    axs[3].set_title("Beta power: dominant vs non-dominant")
    axs[3].set_ylabel("Beta power")
    axs[3].legend(loc="upper right")

    axs[1].set_xlabel("Time from EEG start (seconds)")

    fig.text(
        0.5,
        0.01,
        "Shaded areas = detected drawing intervals | Red dashed line = detected hand switch pause",
        ha="center",
        fontsize=10,
    )

    plt.tight_layout(rect=[0, 0.03, 1, 0.94])

    if show_plots:
        plt.show()

    return fig


def plot_all_eeg_channels(
    eeg_raw: np.ndarray,
    time_sec: np.ndarray,
    channel_names: list[str],
    dominant_intervals: list[tuple[float, float]],
    nondominant_intervals: list[tuple[float, float]],
    switch_time: float | None,
    subject_id: str,
    show_plots: bool = False,
) -> Figure:
    downsample_factor = max(1, int(len(time_sec) / 20000))

    time_ds = time_sec[::downsample_factor]
    eeg_ds = eeg_raw[::downsample_factor, :]
    n_channels = eeg_ds.shape[1]

    fig, axs = plt.subplots(
        n_channels,
        1,
        figsize=(18, max(10, n_channels * 1.1)),
        sharex=True,
    )

    if n_channels == 1:
        axs = [axs]

    fig.suptitle(
        f"All EEG channels across entire run\nSubject {subject_id}",
        fontsize=16,
        fontweight="bold",
    )

    for i, ax in enumerate(axs):
        signal = eeg_ds[:, i]
        signal = signal - np.nanmean(signal)

        ax.plot(time_ds, signal, linewidth=0.45)
        shade_intervals(ax, dominant_intervals, nondominant_intervals)
        add_switch_marker(ax, switch_time)
        ax.set_ylabel(channel_names[i], rotation=0, labelpad=25)
        ax.grid(True, alpha=0.25)

    axs[-1].set_xlabel("Time from EEG start (seconds)")

    fig.text(
        0.5,
        0.01,
        (
            "Shaded areas = detected drawing intervals | Red dashed line = detected dominant "
            "to non-dominant hand switch"
        ),
        ha="center",
        fontsize=10,
    )

    plt.tight_layout(rect=[0, 0.03, 1, 0.97])

    if show_plots:
        plt.show()

    return fig


def run_spiral_eeg_processing(
    eeg_stream: XdfStream,
    streams: list[XdfStream],
    subject_id: str,
    show_plots: bool = False,
) -> SpiralEEGProcessingResult:
    try:
        ipad_stream = find_largest_stream(streams, is_pen_stream)
        if ipad_stream is None:
            raise EEGProcessingError("No iPad / MindLogger drawing stream found.")

        eeg_raw = np.asarray(eeg_stream["time_series"], dtype=float)
        eeg_time_abs = np.asarray(eeg_stream["time_stamps"], dtype=float)

        if eeg_raw.ndim != 2:
            raise EEGProcessingError("EEG stream is not 2D.")
        if len(eeg_time_abs) != len(eeg_raw):
            raise EEGProcessingError("EEG sample count does not match timestamp count.")

        sampling_rate = get_effective_srate(eeg_stream)
        if sampling_rate <= 0:
            sampling_rate = 300

        time_sec = eeg_time_abs - eeg_time_abs[0]
        original_channel_names = get_channel_names(eeg_stream, eeg_raw.shape[1])

        keep_idx = [
            i
            for i, channel in enumerate(original_channel_names)
            if channel not in BAD_CHANNELS
        ]
        channel_names = [original_channel_names[i] for i in keep_idx]
        eeg_raw = eeg_raw[:, keep_idx]
        eeg_clean = clean_eeg(eeg_raw, sampling_rate)

        (
            switch_time,
            dominant_intervals,
            nondominant_intervals,
            ipad_time_sec,
            ipad_x,
            ipad_y,
        ) = get_drawing_intervals_from_ipad(
            ipad_stream=ipad_stream,
            eeg_start_time=eeg_time_abs[0],
        )

        logger.info("Detected switch time: %s", switch_time)
        logger.info("Dominant intervals: %s", dominant_intervals)
        logger.info("Non-dominant intervals: %s", nondominant_intervals)

        summary_data = get_spiral_eeg_data_out(
            eeg_clean=eeg_clean,
            time_sec=time_sec,
            sampling_rate=sampling_rate,
            channel_names=channel_names,
            dominant_intervals=dominant_intervals,
            nondominant_intervals=nondominant_intervals,
            switch_time=switch_time,
        )

        qc_figure = plot_spiral_eeg_qc(
            eeg_clean=eeg_clean,
            time_sec=time_sec,
            channel_names=channel_names,
            ipad_time_sec=ipad_time_sec,
            ipad_x=ipad_x,
            ipad_y=ipad_y,
            summary_data=summary_data,
            dominant_intervals=dominant_intervals,
            nondominant_intervals=nondominant_intervals,
            switch_time=switch_time,
            subject_id=subject_id,
            show_plots=show_plots,
        )

        all_channels_figure = plot_all_eeg_channels(
            eeg_raw=eeg_raw,
            time_sec=time_sec,
            channel_names=channel_names,
            dominant_intervals=dominant_intervals,
            nondominant_intervals=nondominant_intervals,
            switch_time=switch_time,
            subject_id=subject_id,
            show_plots=show_plots,
        )

        return {
            "summary_data": summary_data,
            "qc_figure": qc_figure,
            "all_channels_figure": all_channels_figure,
        }

    except EEGProcessingError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise EEGProcessingError("Could not process spiral EEG data.") from error


class SpiralTaskProcessor:
    task_name = "spiral"

    def run(self, streams: list[XdfStream], subject_id: str) -> GraphomotorTaskResult:
        eeg_stream = find_largest_stream(streams, is_eeg_stream)

        if eeg_stream is None:
            logger.info(
                "No Spiral EEG processing for %s because selected XDF has no EEG.",
                subject_id,
            )
            return GraphomotorTaskResult()

        try:
            eeg_result = run_spiral_eeg_processing(
                eeg_stream=eeg_stream,
                streams=streams,
                subject_id=subject_id,
                show_plots=False,
            )
        except EEGProcessingError as error:
            logger.warning("Skipping Spiral EEG processing for %s: %s", subject_id, error)
            return GraphomotorTaskResult()

        summary_long = eeg_result["summary_data"]

        summary_wide: dict[str, float | None] = {}

        if not summary_long.empty:
            summary_wide["Switch_Time_sec"] = summary_long["Switch_Time_sec"].iloc[0]

            for _, row in summary_long.iterrows():
                channel = str(row["channel"])

                summary_wide[f"{channel}_dominant_alpha"] = row["dominant_alpha"]
                summary_wide[f"{channel}_nondominant_alpha"] = row["nondominant_alpha"]
                summary_wide[f"{channel}_dominant_beta"] = row["dominant_beta"]
                summary_wide[f"{channel}_nondominant_beta"] = row["nondominant_beta"]

        summary_data = pd.DataFrame([summary_wide])

        return GraphomotorTaskResult(
            summary_data=summary_data,
            figure_data_out={
                "Spiral_EEG_QC": eeg_result["qc_figure"],
                "EEG_All_Channels_Entire_Run": eeg_result["all_channels_figure"],
            },
        )
