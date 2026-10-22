"""Standalone PySide6 viewer and runner for Spiral processing results.

The shared ``process_results_common`` window owns folder selection, processing,
subject status, logs and per-subject QC-image discovery. This module only wires
that window to ``vrlab_spiral_process.run_batch`` and supplies a compact Spiral
summary dashboard for the participant-level CSV produced by the pipeline.
"""

from pathlib import Path

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from vrlab_toolbox.cli.vrlab_spiral_process import PHYSIO_GLOB_PATTERN
from vrlab_toolbox.cli.vrlab_spiral_process import run_batch as _run_spiral_batch
from vrlab_toolbox.gui.process_results_common import (
    STATUS_ICON,
    ProcessResultsConfig,
    ProgressCallback,
    run_process_results_app,
    worst_status,
)
from vrlab_toolbox.processing.lsl import get_subject_id
from vrlab_toolbox.processing.processing_status import ProcessingStatus
from vrlab_toolbox.processing.spiral import EXPECTED_SPIRAL_COUNT

_HANDS = ("dominant", "nondominant")
_HAND_LABELS = ("Dominant", "Non-dominant")
_MOTOR_CHANNELS = ("C3", "C4", "Cz")
_ALPHA_CHANNELS = (*_MOTOR_CHANNELS, "O1", "O2")


def _process_bids_folder(
    bids_folder: Path,
    output_folder: Path,
    progress_callback: ProgressCallback | None,
    skip_existing: bool,
) -> list[str]:
    csv_path = _run_spiral_batch(
        bids_folder,
        output_folder,
        progress_callback=progress_callback,
        skip_existing=skip_existing,
    )
    if csv_path is None:
        return ["No subjects were successfully processed."]
    return [f"Wrote {csv_path.name}"]


def _numeric_values(subset: pd.DataFrame, column: str) -> pd.Series:
    if column not in subset.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(subset[column], errors="coerce").dropna()


def _mean_and_sd(subset: pd.DataFrame, column: str) -> tuple[float, float]:
    values = _numeric_values(subset, column)
    if values.empty:
        return float("nan"), 0.0
    return float(values.mean()), float(values.std()) if len(values) > 1 else 0.0


def _draw_hand_bars(
    axes: Axes,
    subset: pd.DataFrame,
    dominant_column: str,
    nondominant_column: str,
    title: str,
    ylabel: str,
    individual: bool,
) -> None:
    columns = (dominant_column, nondominant_column)
    means = []
    sds = []

    for column in columns:
        mean, sd = _mean_and_sd(subset, column)
        means.append(mean)
        sds.append(sd)

    positions = range(len(_HAND_LABELS))
    axes.bar(
        positions,
        means,
        yerr=None if individual else sds,
        capsize=3,
    )
    axes.set_xticks(list(positions))
    axes.set_xticklabels(_HAND_LABELS)
    axes.set_title(title)
    axes.set_ylabel(ylabel)


def _draw_channel_band_bars(
    axes: Axes,
    subset: pd.DataFrame,
    channels: tuple[str, ...],
    band: str,
    individual: bool,
) -> None:
    positions = list(range(len(channels)))
    width = 0.36

    for hand_index, (hand, hand_label) in enumerate(zip(_HANDS, _HAND_LABELS, strict=True)):
        means = []
        sds = []
        for channel in channels:
            mean, sd = _mean_and_sd(subset, f"{channel}_{hand}_{band}")
            means.append(mean)
            sds.append(sd)

        offset = -width / 2 if hand_index == 0 else width / 2
        bar_positions = [position + offset for position in positions]
        axes.bar(
            bar_positions,
            means,
            width=width,
            yerr=None if individual else sds,
            capsize=3,
            label=hand_label,
        )

    axes.set_xticks(positions)
    axes.set_xticklabels(channels)
    axes.set_title(f"EEG {band} band power")
    axes.set_ylabel("Band power")
    axes.legend()


def build_spiral_group_dashboard(
    figure: Figure,
    batch_df: pd.DataFrame,
    subject_ids: list[str],
) -> None:
    subset = batch_df.loc[batch_df["Subject_ID"].isin(subject_ids)]
    individual = len(subject_ids) == 1

    gridspec = figure.add_gridspec(3, 1, height_ratios=[0.9, 1.2, 1.2])

    _draw_hand_bars(
        figure.add_subplot(gridspec[0, 0]),
        subset,
        "Dominant_SCR_per_min",
        "NonDominant_SCR_per_min",
        "EDA: skin conductance responses by hand",
        "SCR/min",
        individual,
    )
    _draw_channel_band_bars(
        figure.add_subplot(gridspec[1, 0]),
        subset,
        _ALPHA_CHANNELS,
        "alpha",
        individual,
    )
    _draw_channel_band_bars(
        figure.add_subplot(gridspec[2, 0]),
        subset,
        _MOTOR_CHANNELS,
        "beta",
        individual,
    )


def _status_summary_text(subset: pd.DataFrame, subject_ids: list[str]) -> str:
    if len(subject_ids) == 1:
        if subset.empty:
            return "Status: No output yet"
        status = worst_status(str(subset.iloc[0].get("Processing_Status", "")))
        icon, _color = STATUS_ICON[status]
        label = "warning" if status is ProcessingStatus.ERROR else status.value
        return f"Status: {icon} {label.upper()}"

    counts: dict[ProcessingStatus, int] = {}
    if "Processing_Status" in subset.columns:
        for value in subset["Processing_Status"]:
            status = worst_status(str(value))
            counts[status] = counts.get(status, 0) + 1

    parts = [
        f"{STATUS_ICON[status][0]} {count} "
        f"{'warning' if status is ProcessingStatus.ERROR else status.value}"
        for status, count in counts.items()
    ]
    no_output = len(subject_ids) - len(subset)
    if no_output:
        parts.append(f"{STATUS_ICON[ProcessingStatus.NOT_RUN][0]} {no_output} no output yet")
    return "Status: " + ("    ".join(parts) if parts else "No subjects selected")


def _completed_spiral_text(subset: pd.DataFrame) -> str:
    values = _numeric_values(subset, "Spiral_Selected_Count")
    if values.empty:
        return f"Complete Spiral sessions ({EXPECTED_SPIRAL_COUNT}/{EXPECTED_SPIRAL_COUNT}): 0 / {len(subset)}"
    complete = int((values == EXPECTED_SPIRAL_COUNT).sum())
    return (
        f"Complete Spiral sessions ({EXPECTED_SPIRAL_COUNT}/{EXPECTED_SPIRAL_COUNT}): "
        f"{complete} / {len(subset)}"
    )


def _attempts_text(subset: pd.DataFrame) -> str:
    values = _numeric_values(subset, "Spiral_Attempts_Detected")
    if values.empty:
        return "Detected attempts, median: -"
    return f"Detected attempts, median: {float(values.median()):.1f}"


def _switch_time_text(subset: pd.DataFrame) -> str:
    values = _numeric_values(subset, "Switch_Time_sec")
    if values.empty:
        return "Dominant → non-dominant switch time, median: -"
    return f"Dominant → non-dominant switch time, median: {float(values.median()):.1f} s"


def spiral_dashboard_overhead_lines(
    batch_df: pd.DataFrame,
    subject_ids: list[str],
) -> list[str]:
    subset = batch_df.loc[batch_df["Subject_ID"].isin(subject_ids)]
    return [
        _status_summary_text(subset, subject_ids),
        _completed_spiral_text(subset),
        _attempts_text(subset),
        _switch_time_text(subset),
    ]


SPIRAL_PROCESS_RESULTS_CONFIG = ProcessResultsConfig(
    dataset_name="spiral",
    window_title="Spiral Process Results",
    csv_glob="spiral_process_batch_out.csv",
    process_bids_folder=_process_bids_folder,
    bids_physio_glob=PHYSIO_GLOB_PATTERN,
    bids_subject_id_from_path=get_subject_id,
    build_group_dashboard=build_spiral_group_dashboard,
    dashboard_overhead_lines=spiral_dashboard_overhead_lines,
)


def main() -> None:
    run_process_results_app(
        SPIRAL_PROCESS_RESULTS_CONFIG,
        settings_app_name="SpiralProcessResults",
    )


if __name__ == "__main__":
    main()
