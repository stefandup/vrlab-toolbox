from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TypedDict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from vrlab_toolbox.processing import eda
from vrlab_toolbox.processing.eeg import (
    BAD_CHANNELS,
    EEGProcessingError,
    bandpower_welch,
    clean_eeg,
    get_interval_signal,
)
from vrlab_toolbox.processing.graphomotor_xdf import (
    MOVEMENT_EPSILON,
    XdfStream,
    get_pen_movement_intervals,
)

logger = logging.getLogger(__name__)

MOTOR_CHANNELS = ["C3", "C4", "Cz"]
OCCIPITAL_CHANNELS = ["O1", "O2"]
ALPHA_BAND = (8, 12)
BETA_BAND = (13, 30)
EXPECTED_SPIRAL_COUNT = 16
EXPECTED_SPIRALS_PER_HAND = 8
MAX_QC_POINTS = 20000


@dataclass(frozen=True)
class SpiralDrawingIntervals:
    switch_time: float
    dominant_intervals: list[tuple[float, float]]
    nondominant_intervals: list[tuple[float, float]]
    attempt_features: pd.DataFrame
    selected_attempts: pd.DataFrame


class SpiralEEGProcessingResult(TypedDict):
    summary_data: pd.DataFrame
    time_stamps: np.ndarray
    eeg_clean: np.ndarray
    channel_names: list[str]


class SpiralEDAProcessingResult(TypedDict):
    summary_data: pd.DataFrame
    time_stamps: np.ndarray
    signal: np.ndarray


def estimate_spiral_centre(
    time_sec: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    restart_gap_sec: float = 0.5,
) -> tuple[float, float]:
    time_sec = np.asarray(time_sec, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if len(time_sec) != len(x) or len(time_sec) != len(y):
        raise ValueError("Spiral timestamps and coordinates must have the same length.")

    if len(time_sec) == 0:
        raise ValueError("Cannot estimate Spiral centre from empty data.")

    dx = np.diff(x, prepend=x[0])
    dy = np.diff(y, prepend=y[0])
    movement_distance = np.sqrt(dx**2 + dy**2)

    valid = np.isfinite(time_sec) & np.isfinite(x) & np.isfinite(y)
    moving = valid & (movement_distance > MOVEMENT_EPSILON)

    moving_idx = np.where(moving)[0]
    if len(moving_idx) == 0:
        raise ValueError("Cannot estimate Spiral centre without drawing movement.")

    start_idx = [moving_idx[0]]

    for previous_idx, current_idx in zip(moving_idx[:-1], moving_idx[1:], strict=False):
        gap = float(time_sec[current_idx] - time_sec[previous_idx])

        if gap >= restart_gap_sec:
            start_idx.append(current_idx)

    start_x = x[start_idx]
    start_y = y[start_idx]

    median_x = float(np.median(start_x))
    median_y = float(np.median(start_y))

    distance = np.sqrt((start_x - median_x) ** 2 + (start_y - median_y) ** 2)

    if len(distance) >= 3:
        median_distance = float(np.median(distance))
        mad = float(np.median(np.abs(distance - median_distance)))
        cutoff = median_distance + (2 * mad)
        keep = distance <= cutoff

        if np.any(keep):
            start_x = start_x[keep]
            start_y = start_y[keep]

    return float(np.median(start_x)), float(np.median(start_y))


def estimate_spiral_centre_radius(
    time_sec: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    centre: tuple[float, float],
    restart_gap_sec: float = 0.5,
) -> float:
    time_sec = np.asarray(time_sec, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if len(time_sec) != len(x) or len(time_sec) != len(y):
        raise ValueError("Spiral timestamps and coordinates must have the same length.")

    if len(time_sec) == 0:
        raise ValueError("Cannot estimate Spiral centre radius from empty data.")

    dx = np.diff(x, prepend=x[0])
    dy = np.diff(y, prepend=y[0])
    movement_distance = np.sqrt(dx**2 + dy**2)

    valid = np.isfinite(time_sec) & np.isfinite(x) & np.isfinite(y)
    moving = valid & (movement_distance > MOVEMENT_EPSILON)

    moving_idx = np.where(moving)[0]
    if len(moving_idx) == 0:
        raise ValueError("Cannot estimate Spiral centre radius without drawing movement.")

    start_idx = [moving_idx[0]]

    for previous_idx, current_idx in zip(moving_idx[:-1], moving_idx[1:], strict=False):
        gap = float(time_sec[current_idx] - time_sec[previous_idx])

        if gap >= restart_gap_sec:
            start_idx.append(current_idx)

    start_x = x[start_idx]
    start_y = y[start_idx]

    centre_x, centre_y = centre
    distance = np.sqrt((start_x - centre_x) ** 2 + (start_y - centre_y) ** 2)

    if len(distance) >= 3:
        median_distance = float(np.median(distance))
        mad = float(np.median(np.abs(distance - median_distance)))
        cutoff = median_distance + (2 * mad)
        inlier_distance = distance[distance <= cutoff]

        if len(inlier_distance) > 0:
            distance = inlier_distance

    radius = float(np.max(distance)) * 1.5

    return max(radius, MOVEMENT_EPSILON)


def detect_spiral_start_times(
    time_sec: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    centre: tuple[float, float],
    centre_radius: float,
    restart_gap_sec: float = 0.5,
) -> list[float]:
    time_sec = np.asarray(time_sec, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if len(time_sec) == 0:
        return []

    if len(time_sec) != len(x) or len(time_sec) != len(y):
        raise ValueError("Spiral timestamps and coordinates must have the same length.")

    dx = np.diff(x, prepend=x[0])
    dy = np.diff(y, prepend=y[0])
    movement_distance = np.sqrt(dx**2 + dy**2)

    centre_x, centre_y = centre
    distance_from_centre = np.sqrt((x - centre_x) ** 2 + (y - centre_y) ** 2)

    valid = np.isfinite(time_sec) & np.isfinite(x) & np.isfinite(y)
    moving = valid & (movement_distance > MOVEMENT_EPSILON)
    inside_centre = valid & (distance_from_centre <= centre_radius)

    starts: list[float] = []
    left_centre = False
    previous_moving_time: float | None = None

    for idx in np.where(moving)[0]:
        current_time = float(time_sec[idx])
        restarted_after_gap = (
            previous_moving_time is not None
            and current_time - previous_moving_time >= restart_gap_sec
        )

        if inside_centre[idx] and (not starts or left_centre or restarted_after_gap):
            starts.append(current_time)
            left_centre = False
        elif starts and not inside_centre[idx]:
            left_centre = True

        previous_moving_time = current_time

    return starts


def get_spiral_attempt_intervals(
    time_sec: np.ndarray,
    start_times: list[float],
) -> list[tuple[float, float]]:
    time_sec = np.asarray(time_sec, dtype=float)

    if len(time_sec) == 0 or not start_times:
        return []

    intervals: list[tuple[float, float]] = []

    for index, start_time in enumerate(start_times):
        if index + 1 < len(start_times):
            next_start = start_times[index + 1]
            end_idx = int(np.searchsorted(time_sec, next_start, side="left")) - 1

            if end_idx < 0:
                continue

            end_time = float(time_sec[end_idx])
        else:
            end_time = float(time_sec[-1])

        if end_time >= start_time:
            intervals.append((float(start_time), end_time))

    return intervals


def get_spiral_attempt_features(
    time_sec: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    centre: tuple[float, float],
    attempt_intervals: list[tuple[float, float]],
) -> pd.DataFrame:
    time_sec = np.asarray(time_sec, dtype=float)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if len(time_sec) != len(x) or len(time_sec) != len(y):
        raise ValueError("Spiral timestamps and coordinates must have the same length.")

    centre_x, centre_y = centre
    rows = []

    for attempt_number, (start, end) in enumerate(attempt_intervals, start=1):
        mask = (time_sec >= start) & (time_sec <= end)
        attempt_x = x[mask]
        attempt_y = y[mask]
        attempt_time = time_sec[mask]

        valid = np.isfinite(attempt_x) & np.isfinite(attempt_y) & np.isfinite(attempt_time)
        attempt_x = attempt_x[valid]
        attempt_y = attempt_y[valid]
        attempt_time = attempt_time[valid]

        if len(attempt_time) < 2:
            continue

        centred_x = attempt_x - centre_x
        centred_y = attempt_y - centre_y

        radius = np.sqrt(centred_x**2 + centred_y**2)
        angle = np.unwrap(np.arctan2(centred_y, centred_x))

        dx = np.diff(attempt_x)
        dy = np.diff(attempt_y)

        rows.append(
            {
                "Attempt": attempt_number,
                "Start_Time": float(attempt_time[0]),
                "End_Time": float(attempt_time[-1]),
                "Duration_sec": float(attempt_time[-1] - attempt_time[0]),
                "Max_Radius": float(np.max(radius)),
                "Angular_Travel_rad": float(np.sum(np.abs(np.diff(angle)))),
                "Path_Length": float(np.sum(np.sqrt(dx**2 + dy**2))),
            }
        )

    return pd.DataFrame(rows)


def select_completed_spiral_attempts(
    features: pd.DataFrame,
    expected_count: int = EXPECTED_SPIRAL_COUNT,
) -> pd.DataFrame:
    if features.empty:
        return features.copy()

    ordered = features.sort_values("Start_Time").copy()

    if len(ordered) <= expected_count:
        return ordered.reset_index(drop=True)

    score_columns = [
        "Max_Radius",
        "Angular_Travel_rad",
        "Path_Length",
    ]

    completion_score = ordered[score_columns].rank(pct=True).mean(axis=1)
    selected_idx = completion_score.nlargest(expected_count).index

    return ordered.loc[selected_idx].sort_values("Start_Time").reset_index(drop=True)


def label_spiral_hands(
    selected_attempts: pd.DataFrame,
) -> tuple[pd.DataFrame, float | None]:
    ordered = selected_attempts.sort_values("Start_Time").reset_index(drop=True).copy()

    if len(ordered) != EXPECTED_SPIRAL_COUNT:
        return ordered, None

    ordered["Spiral_Number"] = np.arange(1, EXPECTED_SPIRAL_COUNT + 1)
    ordered["Hand"] = [
        "Dominant" if index < EXPECTED_SPIRALS_PER_HAND else "NonDominant"
        for index in range(EXPECTED_SPIRAL_COUNT)
    ]

    dominant_end = float(ordered.iloc[EXPECTED_SPIRALS_PER_HAND - 1]["End_Time"])
    nondominant_start = float(ordered.iloc[EXPECTED_SPIRALS_PER_HAND]["Start_Time"])
    switch_time = dominant_end + ((nondominant_start - dominant_end) / 2)

    return ordered, switch_time


def get_hand_drawing_intervals(
    selected_attempts: pd.DataFrame,
    movement_intervals: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    dominant_intervals: list[tuple[float, float]] = []
    nondominant_intervals: list[tuple[float, float]] = []

    for _, attempt in selected_attempts.iterrows():
        attempt_start = float(attempt["Start_Time"])
        attempt_end = float(attempt["End_Time"])
        hand = str(attempt["Hand"])

        for movement_start, movement_end in movement_intervals:
            overlap_start = max(attempt_start, movement_start)
            overlap_end = min(attempt_end, movement_end)

            if overlap_end <= overlap_start:
                continue

            interval = (overlap_start, overlap_end)

            if hand == "Dominant":
                dominant_intervals.append(interval)
            elif hand == "NonDominant":
                nondominant_intervals.append(interval)

    return dominant_intervals, nondominant_intervals


def get_hand_switch_time(
    dominant_intervals: list[tuple[float, float]],
    nondominant_intervals: list[tuple[float, float]],
) -> float | None:
    if not dominant_intervals or not nondominant_intervals:
        return None

    dominant_end = max(end for _, end in dominant_intervals)
    nondominant_start = min(start for start, _ in nondominant_intervals)

    if nondominant_start < dominant_end:
        raise ValueError("Dominant and non-dominant Spiral intervals overlap.")

    return dominant_end + ((nondominant_start - dominant_end) / 2)


def get_spiral_drawing_intervals(
    ipad_stream: XdfStream,
) -> SpiralDrawingIntervals:
    movement_intervals, ipad_time_abs, x, y = get_pen_movement_intervals(ipad_stream)

    if len(ipad_time_abs) == 0:
        raise EEGProcessingError("iPad stream has no timestamps.")
    if len(x) == 0 or len(y) == 0:
        raise EEGProcessingError("iPad stream does not contain usable x/y drawing columns.")
    if not movement_intervals:
        raise EEGProcessingError("No sustained Spiral drawing movement detected.")

    centre = estimate_spiral_centre(ipad_time_abs, x, y)
    centre_radius = estimate_spiral_centre_radius(
        ipad_time_abs,
        x,
        y,
        centre=centre,
    )

    start_times = detect_spiral_start_times(
        ipad_time_abs,
        x,
        y,
        centre=centre,
        centre_radius=centre_radius,
    )

    attempt_intervals = get_spiral_attempt_intervals(
        ipad_time_abs,
        start_times,
    )

    attempt_features = get_spiral_attempt_features(
        ipad_time_abs,
        x,
        y,
        centre=centre,
        attempt_intervals=attempt_intervals,
    )

    selected_attempts = select_completed_spiral_attempts(attempt_features)
    labelled_attempts, _ = label_spiral_hands(selected_attempts)

    if "Hand" not in labelled_attempts.columns:
        raise EEGProcessingError(
            f"Could not identify {EXPECTED_SPIRAL_COUNT} usable Spiral drawings."
        )

    dominant_intervals, nondominant_intervals = get_hand_drawing_intervals(
        labelled_attempts,
        movement_intervals,
    )

    switch_time = get_hand_switch_time(
        dominant_intervals,
        nondominant_intervals,
    )

    if switch_time is None:
        raise EEGProcessingError("Could not identify dominant and non-dominant drawing intervals.")

    logger.info("Spiral centre: %s", centre)
    logger.info("Detected Spiral attempts: %d", len(attempt_features))
    logger.info("Selected Spiral drawings: %d", len(labelled_attempts))
    logger.info("Detected switch time: %.3f", switch_time)

    return SpiralDrawingIntervals(
        switch_time=switch_time,
        dominant_intervals=dominant_intervals,
        nondominant_intervals=nondominant_intervals,
        attempt_features=attempt_features,
        selected_attempts=labelled_attempts,
    )


def get_spiral_eeg_data_out(
    eeg_clean: np.ndarray,
    time_sec: np.ndarray,
    sampling_rate: float,
    channel_names: list[str],
    dominant_intervals: list[tuple[float, float]],
    nondominant_intervals: list[tuple[float, float]],
    switch_time: float,
) -> pd.DataFrame:
    motor_names = [channel for channel in MOTOR_CHANNELS if channel in channel_names]
    occipital_names = [channel for channel in OCCIPITAL_CHANNELS if channel in channel_names]

    if not motor_names:
        raise EEGProcessingError("No C3/C4/Cz motor channels found.")

    rows: list[dict[str, float | str | None]] = []

    for channel in motor_names + occipital_names:
        channel_idx = channel_names.index(channel)
        signal = eeg_clean[:, channel_idx]

        dominant_signal = get_interval_signal(signal, time_sec, dominant_intervals)
        nondominant_signal = get_interval_signal(signal, time_sec, nondominant_intervals)

        row: dict[str, float | str | None] = {
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
            "dominant_beta": None,
            "nondominant_beta": None,
        }

        if channel in MOTOR_CHANNELS:
            row["dominant_beta"] = bandpower_welch(
                dominant_signal,
                sampling_rate,
                BETA_BAND,
            )
            row["nondominant_beta"] = bandpower_welch(
                nondominant_signal,
                sampling_rate,
                BETA_BAND,
            )

        rows.append(row)

    return pd.DataFrame(rows)


def run_spiral_eeg_processing(
    eeg_data: pd.DataFrame,
    drawing_intervals: SpiralDrawingIntervals,
) -> SpiralEEGProcessingResult:
    try:
        if "time_stamps" not in eeg_data.columns:
            raise EEGProcessingError("EEG data has no time_stamps column.")

        channel_names = [column for column in eeg_data.columns if column != "time_stamps"]
        if not channel_names:
            raise EEGProcessingError("EEG data has no channels.")

        eeg_time_abs = pd.to_numeric(
            eeg_data["time_stamps"],
            errors="coerce",
        ).to_numpy(dtype=float)
        eeg_raw = (
            eeg_data[channel_names]
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
            .to_numpy(dtype=float)
        )

        if eeg_raw.ndim != 2:
            raise EEGProcessingError("EEG data is not 2D.")
        if len(eeg_time_abs) != len(eeg_raw):
            raise EEGProcessingError("EEG sample count does not match timestamp count.")
        if len(eeg_time_abs) < 2:
            raise EEGProcessingError("EEG data does not contain enough timestamps.")

        duration = float(eeg_time_abs[-1] - eeg_time_abs[0])
        sampling_rate = len(eeg_time_abs) / duration if duration > 0 else 0.0
        if sampling_rate <= 0:
            sampling_rate = 300.0

        keep_idx = [
            index for index, channel in enumerate(channel_names) if channel not in BAD_CHANNELS
        ]
        channel_names = [channel_names[index] for index in keep_idx]
        eeg_raw = eeg_raw[:, keep_idx]
        eeg_clean = clean_eeg(eeg_raw, sampling_rate)

        eeg_time_sec = eeg_time_abs - eeg_time_abs[0]
        dominant_intervals = [
            (start - eeg_time_abs[0], end - eeg_time_abs[0])
            for start, end in drawing_intervals.dominant_intervals
        ]
        nondominant_intervals = [
            (start - eeg_time_abs[0], end - eeg_time_abs[0])
            for start, end in drawing_intervals.nondominant_intervals
        ]

        task_start = float(drawing_intervals.selected_attempts.iloc[0]["Start_Time"])
        switch_time = drawing_intervals.switch_time - task_start

        summary_data = get_spiral_eeg_data_out(
            eeg_clean=eeg_clean,
            time_sec=eeg_time_sec,
            sampling_rate=sampling_rate,
            channel_names=channel_names,
            dominant_intervals=dominant_intervals,
            nondominant_intervals=nondominant_intervals,
            switch_time=switch_time,
        )

        return {
            "summary_data": summary_data,
            "time_stamps": eeg_time_abs,
            "eeg_clean": eeg_clean,
            "channel_names": channel_names,
        }

    except EEGProcessingError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise EEGProcessingError("Could not process spiral EEG data.") from error


def run_spiral_eda_processing(
    eda_data: pd.DataFrame,
    drawing_intervals: SpiralDrawingIntervals,
) -> SpiralEDAProcessingResult:
    if "time_stamps" not in eda_data.columns or "EDA" not in eda_data.columns:
        raise eda.EDAProcessingError("EDA data must contain time_stamps and EDA columns.")

    time_stamps = pd.to_numeric(eda_data["time_stamps"], errors="coerce")
    signal = pd.to_numeric(eda_data["EDA"], errors="coerce")
    valid = time_stamps.notna() & signal.notna()
    time_stamps = time_stamps[valid].reset_index(drop=True)
    signal = signal[valid].reset_index(drop=True)

    if len(time_stamps) < 2:
        raise eda.EDAProcessingError("EDA stream does not contain enough timestamps.")

    duration = float(time_stamps.iloc[-1] - time_stamps.iloc[0])
    if duration <= 0:
        raise eda.EDAProcessingError("EDA stream duration is invalid.")

    sampling_rate = int(round(len(time_stamps) / duration))
    if sampling_rate <= 0:
        raise eda.EDAProcessingError("EDA sampling rate is invalid.")

    dominant_block = (
        drawing_intervals.dominant_intervals[0][0],
        drawing_intervals.dominant_intervals[-1][1],
    )
    nondominant_block = (
        drawing_intervals.nondominant_intervals[0][0],
        drawing_intervals.nondominant_intervals[-1][1],
    )

    parts = []

    for hand, (start, end) in {
        "Dominant": dominant_block,
        "NonDominant": nondominant_block,
    }.items():
        mask = (time_stamps >= start) & (time_stamps <= end)
        eda_signal = signal[mask]

        if len(eda_signal) < sampling_rate * 2:
            logger.warning("Not enough EDA data for %s hand.", hand)
            continue

        try:
            eda_processed = eda.run_nk_eda_processing(
                eda_signal,
                sampling_rate=sampling_rate,
            )
        except eda.EDAProcessingError:
            logger.warning("Skipping EDA for %s hand.", hand)
            continue

        parts.append(
            eda.get_eda_data_out(
                eda_processed,
                interval_label=f"{hand}_",
            )
        )

    if not parts:
        raise eda.EDAProcessingError("Could not process dominant or non-dominant Spiral EDA.")

    return {
        "summary_data": pd.concat(parts, axis=1),
        "time_stamps": time_stamps.to_numpy(dtype=float),
        "signal": signal.to_numpy(dtype=float),
    }


def _plot_task_attempts(
    ax,
    drawing_intervals: SpiralDrawingIntervals,
    task_start: float,
) -> None:
    selected = drawing_intervals.selected_attempts
    selected_attempt_numbers = set(selected["Attempt"].astype(int).tolist())

    for _, attempt in drawing_intervals.attempt_features.iterrows():
        start = float(attempt["Start_Time"]) - task_start
        end = float(attempt["End_Time"]) - task_start
        attempt_number = int(attempt["Attempt"])

        if attempt_number not in selected_attempt_numbers:
            ax.hlines(0.5, start, end, linewidth=6, color="0.7")
            ax.text((start + end) / 2, 0.72, "retry", ha="center", fontsize=8)

    for _, attempt in selected.iterrows():
        start = float(attempt["Start_Time"]) - task_start
        end = float(attempt["End_Time"]) - task_start
        hand = str(attempt["Hand"])
        spiral_number = int(attempt["Spiral_Number"])
        color = "C0" if hand == "Dominant" else "C1"

        ax.hlines(0.5, start, end, linewidth=10, color=color)
        ax.text((start + end) / 2, 0.5, str(spiral_number), ha="center", va="center", fontsize=8)

    switch_time = drawing_intervals.switch_time - task_start
    ax.axvline(switch_time, color="red", linestyle="--", linewidth=1.2)
    ax.set_ylim(0, 1)
    ax.set_yticks([])
    ax.set_xlabel("Seconds from first selected spiral")
    ax.set_title(
        f"Task detection: {len(selected)}/{EXPECTED_SPIRAL_COUNT} selected from "
        f"{len(drawing_intervals.attempt_features)} attempts"
    )


def _plot_eeg_qc(
    ax,
    eeg_result: SpiralEEGProcessingResult | None,
    drawing_intervals: SpiralDrawingIntervals,
    task_start: float,
) -> None:
    if eeg_result is None:
        ax.text(0.5, 0.5, "EEG unavailable / processing failed", ha="center", va="center")
        ax.set_axis_off()
        return

    time_stamps = eeg_result["time_stamps"]
    eeg_clean = eeg_result["eeg_clean"]
    channel_names = eeg_result["channel_names"]
    motor_names = [channel for channel in MOTOR_CHANNELS if channel in channel_names]

    if not motor_names:
        ax.text(0.5, 0.5, "C3/C4/Cz unavailable", ha="center", va="center")
        ax.set_axis_off()
        return

    downsample_factor = max(1, int(len(time_stamps) / MAX_QC_POINTS))
    time_sec = time_stamps[::downsample_factor] - task_start
    eeg_plot = eeg_clean[::downsample_factor]
    offset = 0.0

    for channel in motor_names:
        channel_idx = channel_names.index(channel)
        signal = eeg_plot[:, channel_idx]
        spread = float(np.nanpercentile(np.abs(signal), 95))

        if not np.isfinite(spread) or spread <= 0:
            spread = 1.0

        ax.plot(time_sec, signal / spread + offset, linewidth=0.7, label=channel)
        offset += 3.0

    for start, end in drawing_intervals.dominant_intervals:
        ax.axvspan(start - task_start, end - task_start, alpha=0.08, color="C0")
    for start, end in drawing_intervals.nondominant_intervals:
        ax.axvspan(start - task_start, end - task_start, alpha=0.08, color="C1")

    ax.axvline(
        drawing_intervals.switch_time - task_start,
        color="red",
        linestyle="--",
        linewidth=1.2,
    )
    ax.set_ylabel("Scaled EEG")
    ax.set_title("Cleaned motor EEG")
    ax.legend(loc="upper right", ncol=len(motor_names), fontsize=8)


def _plot_eda_qc(
    ax,
    eda_result: SpiralEDAProcessingResult | None,
    drawing_intervals: SpiralDrawingIntervals,
    task_start: float,
) -> None:
    if eda_result is None:
        ax.text(0.5, 0.5, "EDA unavailable / processing failed", ha="center", va="center")
        ax.set_axis_off()
        return

    time_stamps = eda_result["time_stamps"]
    signal = eda_result["signal"]
    downsample_factor = max(1, int(len(time_stamps) / MAX_QC_POINTS))

    ax.plot(
        time_stamps[::downsample_factor] - task_start,
        signal[::downsample_factor],
        linewidth=0.8,
    )

    dominant_start = drawing_intervals.dominant_intervals[0][0] - task_start
    dominant_end = drawing_intervals.dominant_intervals[-1][1] - task_start
    nondominant_start = drawing_intervals.nondominant_intervals[0][0] - task_start
    nondominant_end = drawing_intervals.nondominant_intervals[-1][1] - task_start

    ax.axvspan(dominant_start, dominant_end, alpha=0.08, color="C0")
    ax.axvspan(nondominant_start, nondominant_end, alpha=0.08, color="C1")
    ax.axvline(
        drawing_intervals.switch_time - task_start,
        color="red",
        linestyle="--",
        linewidth=1.2,
    )

    summary = eda_result["summary_data"]
    dominant_scr = summary.get("Dominant_SCR_per_min", pd.Series([np.nan])).iloc[0]
    nondominant_scr = summary.get("NonDominant_SCR_per_min", pd.Series([np.nan])).iloc[0]

    ax.set_ylabel("EDA")
    ax.set_xlabel("Seconds from first selected spiral")
    ax.set_title(
        f"EDA: dominant {dominant_scr:.2f} SCR/min | non-dominant {nondominant_scr:.2f} SCR/min"
    )


def _plot_bandpower_qc(
    alpha_ax,
    beta_ax,
    eeg_result: SpiralEEGProcessingResult | None,
) -> None:
    if eeg_result is None or eeg_result["summary_data"].empty:
        for ax in (alpha_ax, beta_ax):
            ax.text(0.5, 0.5, "Band power unavailable", ha="center", va="center")
            ax.set_axis_off()
        return

    summary = eeg_result["summary_data"]
    width = 0.35

    alpha_x = np.arange(len(summary))
    alpha_ax.bar(
        alpha_x - width / 2,
        summary["dominant_alpha"],
        width,
        label="Dominant",
    )
    alpha_ax.bar(
        alpha_x + width / 2,
        summary["nondominant_alpha"],
        width,
        label="Non-dominant",
    )
    alpha_ax.set_xticks(alpha_x)
    alpha_ax.set_xticklabels(summary["channel"])
    alpha_ax.set_title("Alpha power")
    alpha_ax.legend(loc="best", fontsize=8)

    beta_summary = summary[summary["channel"].isin(MOTOR_CHANNELS)].reset_index(drop=True)
    beta_x = np.arange(len(beta_summary))
    beta_ax.bar(
        beta_x - width / 2,
        beta_summary["dominant_beta"],
        width,
        label="Dominant",
    )
    beta_ax.bar(
        beta_x + width / 2,
        beta_summary["nondominant_beta"],
        width,
        label="Non-dominant",
    )
    beta_ax.set_xticks(beta_x)
    beta_ax.set_xticklabels(beta_summary["channel"])
    beta_ax.set_title("Beta power")
    beta_ax.legend(loc="best", fontsize=8)


def plot_spiral_qc(
    subject_id: str,
    drawing_intervals: SpiralDrawingIntervals,
    eeg_result: SpiralEEGProcessingResult | None,
    eda_result: SpiralEDAProcessingResult | None,
    show_plots: bool = False,
) -> Figure:
    task_start = float(drawing_intervals.selected_attempts.iloc[0]["Start_Time"])
    switch_time = drawing_intervals.switch_time - task_start

    fig = plt.figure(figsize=(15, 11))
    gs = fig.add_gridspec(
        4,
        2,
        height_ratios=[0.8, 1.5, 1.2, 1.0],
    )

    task_ax = fig.add_subplot(gs[0, :])
    eeg_ax = fig.add_subplot(gs[1, :])
    eda_ax = fig.add_subplot(gs[2, :])
    alpha_ax = fig.add_subplot(gs[3, 0])
    beta_ax = fig.add_subplot(gs[3, 1])

    eeg_status = "EEG OK" if eeg_result is not None else "EEG missing"
    eda_status = "EDA OK" if eda_result is not None else "EDA missing"

    fig.suptitle(
        f"Spiral QC — {subject_id} | 16/16 spirals | switch {switch_time:.1f}s | "
        f"{eeg_status} | {eda_status}",
        fontsize=14,
        fontweight="bold",
    )

    _plot_task_attempts(task_ax, drawing_intervals, task_start)
    _plot_eeg_qc(eeg_ax, eeg_result, drawing_intervals, task_start)
    _plot_eda_qc(eda_ax, eda_result, drawing_intervals, task_start)
    _plot_bandpower_qc(alpha_ax, beta_ax, eeg_result)

    fig.tight_layout(rect=[0, 0, 1, 0.96])

    if show_plots:
        plt.show()

    return fig
