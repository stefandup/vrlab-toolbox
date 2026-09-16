"""Standalone PySide6 tool: read-only viewer for a vrlab_crane_process output folder.

See process_results_common.py -- this file only supplies crane's config, plus the
"Process BIDS Folder" callback, which just calls the CLI's own `run_batch` (the same
function `vrlab_crane_process`'s `main()` calls) rather than re-implementing it. The
Summary Stats dashboard below is crane-specific for the same reason: it's built from
column names crane's own pipeline commits to (`crane_behaviour.py`,
`crane_debrief_behaviour.py`, `eda.py`), not from anything longwalk produces.
"""

import re
from collections import Counter
from pathlib import Path

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from vrlab_toolbox.cli.vrlab_crane_process import PHYSIO_GLOB_PATTERN
from vrlab_toolbox.cli.vrlab_crane_process import run_batch as _run_crane_batch
from vrlab_toolbox.gui.process_results_common import (
    STATUS_ICON,
    ProcessResultsConfig,
    ProgressCallback,
    run_process_results_app,
    worst_status,
)
from vrlab_toolbox.processing.crane_debrief_behaviour import DEBRIEF_OUTPUT_METRICS
from vrlab_toolbox.processing.processing_status import ProcessingStatus


def _process_bids_folder(
    bids_folder: Path,
    output_folder: Path,
    progress_callback: ProgressCallback | None,
    skip_existing: bool,
) -> list[str]:
    csv_path = _run_crane_batch(
        bids_folder,
        output_folder,
        progress_callback=progress_callback,
        skip_existing=skip_existing,
    )
    return [f"Wrote {csv_path.name}"]


# Every non-training trial is hypothesised to trend across this same four-condition
# order -- see crane_behaviour.py's BEHAVIOUR_OUTPUT_METRICS, whose column names are
# built as "{metric}_{BlockType}_{TrialType}". Kept as our own tuple (rather than
# imported) because crane_behaviour.py's own TRIAL_TYPES order (Slip before NonSlip)
# doesn't match the display order wanted here.
_BLOCK_ORDER = ("NonStressBlock", "StressBlock")
_TRIAL_ORDER = ("NonSlipTrial", "SlipTrial")
CONDITIONS = tuple((block, trial) for block in _BLOCK_ORDER for trial in _TRIAL_ORDER)
# Single-line (rather than "NonStress\nNonSlip" split across two lines): rotated close
# to vertical (see `_draw_condition_bar_chart`), a rotated multi-line label's lines end
# up side by side instead of stacked, which reads worse than one rotated line.
CONDITION_LABELS = ("NonStress NonSlip", "NonStress Slip", "Stress NonSlip", "Stress Slip")
# Lighter = NonSlip, darker = Slip; blue = NonStress, red = Stress -- reused on every
# condition-grouped panel so the same condition always reads as the same color.
_CONDITION_COLORS = ("#9ecae1", "#3182bd", "#fc9272", "#de2d26")

# The non-emotion behaviour metrics from crane_behaviour.py's BEHAVIOUR_OUTPUT_METRICS,
# each already broken out per condition -- one small bar-panel per metric. Excludes
# that tuple's `{emotion}_proportion` columns (in-task emotion feedback, distinct from
# the Slip/NonSlip debrief ratings the dashboard's own emotion panel covers) and
# `target_score` (the game's fixed session goal, not something expected to trend by
# condition -- shown instead as its own number alongside the TP/ITI counts, see
# `_draw_goal_count`).
BEHAVIOUR_METRICS = (
    "nausea_avg",
    "dizziness_avg",
    "stressed_avg",
    "dropped_total",
    "nr_frustration_barrels",
    "nr_error_slips",
    "nr_slips",
    "nr_no_reason_slips",
    "nr_forced_slips",
    "avg_velocity",
)
# Nausea/dizziness/stressed are all 1-5 Likert ratings (see
# crane_behaviour.py's schema, `pa.Check.isin([1,2,3,4,5])`) -- fixing their y-axis to
# that known range makes panels comparable to each other instead of each auto-scaling
# to its own (often much narrower) data range.
_LIKERT_METRICS = ("nausea_avg", "dizziness_avg", "stressed_avg")
_LIKERT_YLIM = (0.0, 5.0)

# SCR_per_min column names, after eda.py's `correct_order` collapses per-trial digits
# and re-suffixes duplicates -- see that function's own docstring/logic. The optional
# digit/suffix groups also match the (rarer) fallback-strategy naming, which skips
# `correct_order` entirely.
_TP_SCR_RE = re.compile(r"^TP\d*_SCR_per_min(_\d+)?$")
_ITI_SCR_RE = re.compile(r"^ITI(_\d+)?_SCR_per_min(_\d+)?$")


def _condition_column(metric: str, block: str, trial: str) -> str:
    return f"{metric}_{block}_{trial}"


def _condition_scr_pattern(block: str, trial: str) -> re.Pattern[str]:
    return re.compile(rf"^{block}_{trial}_\d*_?SCR_per_min(_\d+)?$")


def _debrief_column(emotion: str, trial: str) -> str:
    return f"Debrief_crane_{emotion}_{trial}"


def _condition_means_and_sds(
    subset: pd.DataFrame, columns_per_condition: list[list[str]]
) -> tuple[list[float], list[float]]:
    """For each condition's list of matching columns, averages across columns *within*
    a subject first (e.g. several per-trial SCR readings for one condition), then takes
    the mean/SD of those per-subject values across `subset`'s rows -- so a subject with
    more matching trials/columns doesn't get weighted more heavily than one with fewer.
    """
    means, sds = [], []
    for columns in columns_per_condition:
        present = [c for c in columns if c in subset.columns]
        if not present:
            means.append(float("nan"))
            sds.append(0.0)
            continue
        numeric = subset[present].apply(pd.to_numeric, errors="coerce")
        per_subject = pd.Series(numeric.mean(axis=1, skipna=True)).dropna()
        means.append(per_subject.mean() if not per_subject.empty else float("nan"))
        sds.append(per_subject.std() if len(per_subject) > 1 else 0.0)
    return means, sds


def _draw_condition_bar_chart(
    axes: Axes,
    means: list[float],
    sds: list[float] | None,
    title: str,
    ylim: tuple[float, float] | None = None,
    tick_fontsize: int = 6,
    title_fontsize: int = 8,
) -> None:
    positions = range(len(CONDITION_LABELS))
    axes.bar(positions, means, yerr=sds, capsize=3, color=_CONDITION_COLORS)
    axes.set_xticks(list(positions))
    axes.set_xticklabels(CONDITION_LABELS, fontsize=tick_fontsize)
    # Each of the 12 small per-metric panels is only ~1.6in wide -- four centered
    # horizontal labels there collide (same crowding the debrief panel below avoids
    # with its own rotated labels). Near-vertical keeps each label's horizontal
    # footprint down to about one character wide, which a shallower angle didn't.
    axes.tick_params(axis="x", labelrotation=90, labelsize=tick_fontsize)
    for tick_label in axes.get_xticklabels():
        tick_label.set_ha("center")
    axes.tick_params(axis="y", labelsize=tick_fontsize)
    axes.set_title(title, fontsize=title_fontsize)
    if ylim is not None:
        axes.set_ylim(*ylim)


# A step marked ERROR doesn't always mean the whole subject is unusable -- often just
# one sub-step (e.g. a trigger-interval count mismatch) flagged something worth a
# second look while everything else still processed fine. The icon/color stay
# alarming-red (an "x" still means "look at this one" -- see `STATUS_ICON`), but the
# word shown next to it reads as a softer "warning" rather than "error".
_STATUS_DISPLAY_LABEL = {ProcessingStatus.ERROR: "warning"}


def _status_label(status: ProcessingStatus) -> str:
    return _STATUS_DISPLAY_LABEL.get(status, status.value)


def _status_summary_text(subset: pd.DataFrame, subject_ids: list[str]) -> str:
    """Processing-status readout as one text line for the Activity Log -- one subject's
    own worst status when exactly one is selected, otherwise a count per status across
    the selection (plus any selected subject with no batch-CSV row at all, i.e. no
    output yet). Used to live as its own large-font row in the dashboard figure; now
    text so that space goes back to the actual charts (see `build_crane_group_dashboard`
    and `ProcessResultsConfig.dashboard_overhead_lines`).
    """
    no_output = len(subject_ids) - len(subset)

    if len(subject_ids) == 1:
        if subset.empty:
            return "Status: No output yet"
        status = worst_status(str(subset.iloc[0].get("Processing_Status", "")))
        icon, _color = STATUS_ICON[status]
        return f"Status: {icon} {_status_label(status).upper()}"

    status_values = subset["Processing_Status"] if "Processing_Status" in subset.columns else []
    counts = Counter(worst_status(str(value)) for value in status_values)
    parts = [
        f"{STATUS_ICON[status][0]} {count} {_status_label(status)}"
        for status, count in counts.items()
    ]
    if no_output:
        parts.append(f"{STATUS_ICON[ProcessingStatus.NOT_RUN][0]} {no_output} no output yet")
    return "Status: " + ("    ".join(parts) if parts else "No subjects selected")


def _tp_subject_count_text(subset: pd.DataFrame) -> str:
    """How many of `subset`'s subjects have at least one unrecognized (TP) trigger
    period -- a data-quality flag, so what matters at group level is how many subjects
    were affected, not a raw total that just scales with however many trials happened
    to have one (which told a group viewer little -- see the dashboard's own docstring).
    """
    columns = [c for c in subset.columns if _TP_SCR_RE.fullmatch(c)]
    total = len(subset)
    affected = 0
    if columns and total:
        has_tp_data = pd.Series(subset[columns].notna().any(axis=1))
        affected = int(has_tp_data.sum())
    return f"Subjects with unrecognized (TP) trigger periods: {affected} / {total}"


def _iti_median_count_text(subset: pd.DataFrame) -> str:
    """Typical (median) number of ITI intervals with data, per subject -- ITIs are an
    expected, structural part of every session, so the per-subject count is more
    informative at group level than a raw sum across however many subjects are selected.
    """
    columns = [c for c in subset.columns if _ITI_SCR_RE.fullmatch(c)]
    if not columns or subset.empty:
        return "Median ITI intervals with data, per subject: -"
    per_subject_counts = subset[columns].notna().sum(axis=1)
    median = float(per_subject_counts.median())
    text = f"{median:.0f}" if median == int(median) else f"{median:.1f}"
    return f"Median ITI intervals with data, per subject: {text}"


def _goal_count_text(subset: pd.DataFrame) -> str:
    """The crane game's target/goal barrel count -- a single number (the typical value
    across `subset`, via median) rather than a per-condition trend, since it's a fixed
    session target rather than something expected to vary by Stress x Slip.
    """
    columns = [_condition_column("target_score", block, trial) for block, trial in CONDITIONS]
    present = [c for c in columns if c in subset.columns]
    if not present:
        return "Goal (target barrels), median: -"
    numeric = subset[present].apply(pd.to_numeric, errors="coerce")
    per_subject = pd.Series(numeric.mean(axis=1, skipna=True)).dropna()
    if per_subject.empty:
        return "Goal (target barrels), median: -"
    value = float(per_subject.median())
    return f"Goal (target barrels), median: {value:.0f}"


def _draw_behaviour_metric(axes: Axes, subset: pd.DataFrame, metric: str, individual: bool) -> None:
    columns_per_condition = [
        [_condition_column(metric, block, trial)] for block, trial in CONDITIONS
    ]
    means, sds = _condition_means_and_sds(subset, columns_per_condition)
    ylim = _LIKERT_YLIM if metric in _LIKERT_METRICS else None
    _draw_condition_bar_chart(
        axes, means, None if individual else sds, metric.replace("_", " "), ylim=ylim
    )
    # Bars alone read as unitless numbers at this panel size -- the y-axis names what's
    # actually being counted/averaged, and "mean" only applies in group mode (an
    # individual subject's bars are that subject's own values, not an average).
    axes.set_ylabel(metric.replace("_", " ") + (" (mean)" if not individual else ""), fontsize=6)


def _draw_scr_condition_bars(axes: Axes, subset: pd.DataFrame, individual: bool) -> None:
    """EDA/SCR gets its own full-width row (like the debrief panel below it) rather
    than sharing space with the behaviour-metric grid -- it's a different data source
    (physiology, not self-report) and easy to overlook as just one more small subplot.
    """
    columns_per_condition = [
        [c for c in subset.columns if _condition_scr_pattern(block, trial).fullmatch(c)]
        for block, trial in CONDITIONS
    ]
    means, sds = _condition_means_and_sds(subset, columns_per_condition)
    _draw_condition_bar_chart(
        axes,
        means,
        None if individual else sds,
        "EDA: SCR per minute by condition",
        tick_fontsize=9,
        title_fontsize=11,
    )
    axes.set_ylabel("SCR/min", fontsize=8)


def _draw_debrief_emotions(axes: Axes, subset: pd.DataFrame, individual: bool) -> None:
    positions = range(len(DEBRIEF_OUTPUT_METRICS))
    width = 0.35
    for offset, trial, color, label in (
        (-width / 2, "NonSlipTrial", "#9ecae1", "Non-Slip"),
        (width / 2, "SlipTrial", "#de2d26", "Slip"),
    ):
        columns_per_emotion = [
            [_debrief_column(emotion, trial)] for emotion in DEBRIEF_OUTPUT_METRICS
        ]
        means, sds = _condition_means_and_sds(subset, columns_per_emotion)
        bar_positions = [p + offset for p in positions]
        axes.bar(
            bar_positions,
            means,
            width=width,
            yerr=None if individual else sds,
            capsize=2,
            color=color,
            label=label,
        )
    axes.set_xticks(list(positions))
    axes.set_xticklabels([emotion.capitalize() for emotion in DEBRIEF_OUTPUT_METRICS], fontsize=7)
    axes.tick_params(axis="x", labelrotation=30, labelsize=7)
    for tick_label in axes.get_xticklabels():
        tick_label.set_ha("right")
    axes.tick_params(axis="y", labelsize=7)
    axes.set_title("Debrief: emotion ratings by trial type", fontsize=9)
    axes.legend(fontsize=7, loc="upper right")


def build_crane_group_dashboard(
    figure: Figure, batch_df: pd.DataFrame, subject_ids: list[str]
) -> None:
    """`ProcessResultsConfig.build_group_dashboard` for crane: a fixed-layout "one
    dashboard" over whichever subjects are selected (or the whole roster, if none are)
    -- every behaviour metric trending across the four Stress x Slip conditions,
    EDA/SCR's own trend across those same conditions, and debrief emotions by trial
    type. Processing status, SCR/EDA interval counts and the target-score goal are
    `crane_dashboard_overhead_lines` instead, shown in the Activity Log rather than as
    rows here -- see `ProcessResultsConfig.dashboard_overhead_lines`.
    """
    n_cols = 6
    # Explicit hspace/wspace are unnecessary here -- the figure this is drawn into is
    # always built with layout="constrained" (see `ProcessResultsWindow._refresh_stats_tab`),
    # which recomputes spacing/margins on every draw instead of using fixed values.
    gridspec = figure.add_gridspec(4, n_cols, height_ratios=[1, 1, 1.1, 1.2])
    subset = batch_df.loc[batch_df["Subject_ID"].isin(subject_ids)]
    individual = len(subject_ids) == 1

    # 10 behaviour metrics -- fits a 2-row x 6-col grid with two slots left empty.
    metric_positions = [(row, col) for row in range(2) for col in range(n_cols)]
    for (row, col), metric in zip(metric_positions, BEHAVIOUR_METRICS, strict=False):
        _draw_behaviour_metric(figure.add_subplot(gridspec[row, col]), subset, metric, individual)

    _draw_scr_condition_bars(figure.add_subplot(gridspec[2, :]), subset, individual)
    _draw_debrief_emotions(figure.add_subplot(gridspec[3, :]), subset, individual)


def crane_dashboard_overhead_lines(batch_df: pd.DataFrame, subject_ids: list[str]) -> list[str]:
    """`ProcessResultsConfig.dashboard_overhead_lines` for crane: the status/count
    readout that used to be `build_crane_group_dashboard`'s own top two rows, now text
    in the Activity Log instead so that space goes back to the charts.
    """
    subset = batch_df.loc[batch_df["Subject_ID"].isin(subject_ids)]
    return [
        _status_summary_text(subset, subject_ids),
        _tp_subject_count_text(subset),
        _iti_median_count_text(subset),
        _goal_count_text(subset),
    ]


CRANE_PROCESS_RESULTS_CONFIG = ProcessResultsConfig(
    dataset_name="crane",
    window_title="Crane Process Results",
    csv_glob="*vrlab_crane_process_batch_data_out.csv",
    process_bids_folder=_process_bids_folder,
    bids_physio_glob=PHYSIO_GLOB_PATTERN,
    build_group_dashboard=build_crane_group_dashboard,
    dashboard_overhead_lines=crane_dashboard_overhead_lines,
)


def main() -> None:
    run_process_results_app(CRANE_PROCESS_RESULTS_CONFIG, settings_app_name="CraneProcessResults")


if __name__ == "__main__":
    main()
