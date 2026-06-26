from typing import TypedDict
import logging

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from scipy.signal import butter, sosfiltfilt, iirnotch, filtfilt, welch

logger = logging.getLogger(__name__)


class EEGProcessingError(Exception):
    """Raised when EEG spiral processing fails."""


class SpiralEEGProcessingResult(TypedDict):
    """Output from spiral EEG processing."""
    summary_data: pd.DataFrame
    qc_figure: Figure
    all_channels_figure: Figure


BAD_CHANNELS = [
    "TRG", "ACCT", "ACCX", "ACCY", "ACCZ",
    "X1", "X2", "X3",
    "A2",
    "Cz",
]

MOTOR_CHANNELS = ["C3", "C4"]

ALPHA_BAND = (8, 12)
BETA_BAND = (13, 30)

MIN_DRAWING_INTERVAL_SEC = 2.0
MIN_SWITCH_PAUSE_SEC = 8.0
DOWNSAMPLE_FACTOR = 10
Y_SCALE_UV = 300


def get_stream_name(stream) -> str:
    return stream["info"]["name"][0]


def get_stream_type(stream) -> str:
    return stream["info"].get("type", [""])[0]


def get_effective_srate(stream) -> float:
    time_stamps = np.asarray(stream.get("time_stamps", []), dtype=float)

    if len(time_stamps) < 2:
        return 0

    duration = time_stamps[-1] - time_stamps[0]

    if duration <= 0:
        return 0

    return len(time_stamps) / duration


def get_channel_names(stream, n_channels: int) -> list[str]:
    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        names = [channel["label"][0] for channel in channels]

        if len(names) == n_channels:
            return names

    except Exception:
        pass

    return [f"Ch {i + 1}" for i in range(n_channels)]


def safe_float_array(values) -> np.ndarray:
    out = []

    for value in values:
        try:
            out.append(float(value))
        except Exception:
            out.append(np.nan)

    return np.asarray(out, dtype=float)


def find_ipad_stream(streams):
    for stream in streams:
        if len(stream.get("time_series", [])) == 0:
            continue

        name = get_stream_name(stream).lower()
        stream_type = get_stream_type(stream).lower()

        if (
            "mindlogger" in name
            or "live_event" in name
            or "live_event" in stream_type
            or "drawing" in name
        ):
            return stream

    return None


def clean_eeg(data: np.ndarray, sampling_rate: float) -> np.ndarray:
    data = np.asarray(data, dtype=float).copy()

    data = data - np.nanmean(data, axis=0)

    b_notch, a_notch = iirnotch(w0=50, Q=30, fs=sampling_rate)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    sos = butter(
        4,
        [1, 40],
        btype="bandpass",
        fs=sampling_rate,
        output="sos",
    )

    data = sosfiltfilt(sos, data, axis=0)

    return data


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
    if len(drawing_intervals) == 0:
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

    big_gaps = [
        gap for gap in gaps
        if gap["gap_duration"] >= MIN_SWITCH_PAUSE_SEC
    ]

    if len(big_gaps) > 0:
        chosen_gap = max(big_gaps, key=lambda item: item["gap_duration"])
    else:
        chosen_gap = max(gaps, key=lambda item: item["gap_duration"])

    switch_time = chosen_gap["left_end"] + (chosen_gap["gap_duration"] / 2)
    split_idx = chosen_gap["index"] + 1

    dominant_intervals = drawing_intervals[:split_idx]
    nondominant_intervals = drawing_intervals[split_idx:]

    return switch_time, dominant_intervals, nondominant_intervals


def get_drawing_intervals_from_ipad(
    ipad_stream,
    eeg_start_time: float,
) -> tuple[float | None, list[tuple[float, float]], list[tuple[float, float]], np.ndarray, np.ndarray, np.ndarray]:
    ipad_data = np.asarray(ipad_stream["time_series"])
    ipad_time_abs = np.asarray(ipad_stream["time_stamps"], dtype=float)
    ipad_time_eeg = ipad_time_abs - eeg_start_time

    if ipad_data.ndim != 2 or ipad_data.shape[1] < 2:
        raise EEGProcessingError("iPad stream does not contain x/y drawing columns.")

    x = safe_float_array(ipad_data[:, 0])
    y = safe_float_array(ipad_data[:, 1])

    drawing_active = (
        np.isfinite(x)
        & np.isfinite(y)
        & (
            (np.abs(x) > 0.001)
            | (np.abs(y) > 0.001)
        )
    )

    drawing_intervals = detect_active_intervals(
        ipad_time_eeg,
        drawing_active,
        min_duration=MIN_DRAWING_INTERVAL_SEC,
    )

    switch_time, dominant_intervals, nondominant_intervals = detect_switch_from_big_pause(
        drawing_intervals
    )

    return switch_time, dominant_intervals, nondominant_intervals, ipad_time_eeg, x, y


def get_interval_signal(
    signal: np.ndarray,
    time_sec: np.ndarray,
    intervals: list[tuple[float, float]],
) -> np.ndarray:
    pieces = []

    for start, end in intervals:
        mask = (time_sec >= start) & (time_sec <= end)
        pieces.append(signal[mask])

    if len(pieces) == 0:
        return np.asarray([])

    return np.concatenate(pieces)


def bandpower_welch(
    signal: np.ndarray,
    sampling_rate: float,
    band: tuple[int, int],
) -> float:
    signal = np.asarray(signal, dtype=float)
    signal = signal[np.isfinite(signal)]

    if len(signal) < int(sampling_rate * 2):
        return np.nan

    freqs, power = welch(
        signal,
        fs=sampling_rate,
        nperseg=min(int(sampling_rate * 2), len(signal)),
    )

    band_mask = (freqs >= band[0]) & (freqs <= band[1])

    if not np.any(band_mask):
        return np.nan

    return np.trapz(power[band_mask], freqs[band_mask])


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

    ax.axvline(
        switch_time,
        color="red",
        linestyle="--",
        linewidth=1.3,
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
    motor_names = [channel for channel in MOTOR_CHANNELS if channel in channel_names]

    if len(motor_names) == 0:
        raise EEGProcessingError("No C3/C4 motor channels found.")

    summary_rows = []

    for channel in motor_names:
        channel_idx = channel_names.index(channel)
        signal = eeg_clean[:, channel_idx]

        dominant_signal = get_interval_signal(signal, time_sec, dominant_intervals)
        nondominant_signal = get_interval_signal(signal, time_sec, nondominant_intervals)

        summary_rows.append(
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

    return pd.DataFrame(summary_rows)


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
        "Shaded areas = detected drawing intervals | Red dashed line = detected dominant to non-dominant hand switch",
        ha="center",
        fontsize=10,
    )

    plt.tight_layout(rect=[0, 0.03, 1, 0.97])

    if show_plots:
        plt.show()

    return fig


def run_spiral_eeg_processing(
    eeg_stream,
    streams,
    subject_id: str,
    show_plots: bool = False,
) -> SpiralEEGProcessingResult:
    """Run EEG processing for the spiral task and return data + QC figures."""
    try:
        ipad_stream = find_ipad_stream(streams)

        if ipad_stream is None:
            raise EEGProcessingError("No iPad / MindLogger drawing stream found.")

        eeg_raw = np.asarray(eeg_stream["time_series"], dtype=float)
        eeg_time_abs = np.asarray(eeg_stream["time_stamps"], dtype=float)

        if eeg_raw.ndim != 2:
            raise EEGProcessingError("EEG stream is not 2D.")

        sampling_rate = get_effective_srate(eeg_stream)

        if sampling_rate <= 0:
            sampling_rate = 300

        time_sec = eeg_time_abs - eeg_time_abs[0]

        original_channel_names = get_channel_names(
            eeg_stream,
            eeg_raw.shape[1],
        )

        keep_idx = [
            i for i, channel in enumerate(original_channel_names)
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

    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise EEGProcessingError("Could not process spiral EEG data.") from error