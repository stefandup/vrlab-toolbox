"""Standalone PySide6 tool: read-only viewer for a vrlab_longwalk3_process output folder.

Built like crane_process_results_gui.py: the shared window lives in process_results_common.py,
this file only supplies LongwalkV3's config -- the "Process BIDS Folder" callback (the CLI's own
`run_batch`), how a subject id is read from a BIDS physiology path, and a LongwalkV3 Summary
Stats dashboard built from the column names the LongwalkV3 pipeline writes (D3: one wide row
per subject, every session's columns prefixed "sesNN_"; SCR per threat-marker segment,
"sesNN_<marker name>_SCR_per_min").

Icons (emoji) appear only on the figures, never in the CSV/SAV -- the same icon set as the
interval QC plot (longwalk3_trigger_pulses.ACTOR_CLASS_ICONS).
"""

import re
from collections import Counter
from pathlib import Path

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from vrlab_toolbox.cli.vrlab_longwalk3_process import BATCH_OUTPUT_STEM, PHYSIO_GLOB_PATTERN
from vrlab_toolbox.cli.vrlab_longwalk3_process import run_batch as _run_longwalk3_batch
from vrlab_toolbox.gui.process_results_common import (
    STATUS_ICON,
    ProcessResultsConfig,
    ProgressCallback,
    run_process_results_app,
    worst_status,
)
from vrlab_toolbox.processing.longwalk3_trial_intervals import (
    THREAT_MARKER_CLASS,
    threat_marker_number,
)
from vrlab_toolbox.processing.longwalk3_trigger_pulses import (
    ACTOR_CLASS_ICONS,
    icon_font_families,
)
from vrlab_toolbox.processing.processing_status import ProcessingStatus

# "ses01_ThreatLevelMarkerNew2_SCR_per_min" -> session "01", segment
# "ThreatLevelMarkerNew2" (threat marker 2 -> 3, see longwalk3_trial_intervals).
SCR_COLUMN_PATTERN = re.compile(r"^ses(?P<session>\d+)_(?P<actor>.+?)_SCR_per_min(?:_\d+)?$")
SESSION_STATUS_PATTERN = re.compile(r"^ses(?P<session>\d+)_Processing_Status$")


def _process_bids_folder(
    bids_folder: Path,
    output_folder: Path,
    progress_callback: ProgressCallback | None,
    skip_existing: bool,
) -> list[str]:
    csv_path = _run_longwalk3_batch(
        bids_folder,
        output_folder,
        progress_callback=progress_callback,
        skip_existing=skip_existing,
    )
    return [f"Wrote {csv_path.name}"]


def subject_id_from_bids_path(path: Path) -> str:
    """The subject id of a BIDS physiology file, from its `sub-<id>` folder (same as the CLI's
    `find_subject_ids`) -- falling back to the filename's own sub- entity."""
    folder = next((part for part in path.parts if part.startswith("sub-")), None)
    if folder is not None and folder != path.name:
        return folder.removeprefix("sub-")
    match = re.match(r"^sub-(?P<id>[^_]+)_", path.name)
    return match["id"] if match else path.stem


def actor_class_label(actor: str, with_icon: bool = True) -> str:
    """'BP_NPC_C' -> '🚶 NPC' (or 'NPC' without the icon)."""
    key = actor.replace("_", "")
    short = re.sub(r"^BP|C$", "", key)
    icon = ACTOR_CLASS_ICONS.get(key)
    return f"{icon} {short}" if with_icon and icon else short


def _scr_columns(df: pd.DataFrame) -> dict[tuple[str, str], list[str]]:
    """{(session, actor class): [its SCR_per_min columns]}."""
    columns: dict[tuple[str, str], list[str]] = {}
    for column in df.columns:
        match = SCR_COLUMN_PATTERN.match(str(column))
        if match:
            columns.setdefault((match["session"], match["actor"]), []).append(str(column))
    return columns


def _per_subject_mean(subset: pd.DataFrame, columns: list[str]) -> pd.Series:
    """One value per subject: the mean across `columns` within that subject first, so a
    subject with more intervals of a class doesn't weigh more."""
    if not columns:
        return pd.Series(dtype=float)
    numeric = subset[columns].apply(pd.to_numeric, errors="coerce")
    return pd.Series(numeric.mean(axis=1, skipna=True)).dropna()


def _bar(axes: Axes, labels: list[str], values: list[pd.Series], individual: bool, colors) -> None:
    means = [float(v.mean()) if not v.empty else float("nan") for v in values]
    sds = [float(v.std()) if len(v) > 1 else 0.0 for v in values]
    positions = list(range(len(labels)))
    axes.bar(positions, means, yerr=None if individual else sds, capsize=3, color=colors)
    axes.set_xticks(positions)
    fonts = icon_font_families()
    axes.set_xticklabels(labels, fontsize=9, **({"fontfamily": fonts} if fonts else {}))
    axes.tick_params(axis="y", labelsize=8)


def _segment_sort_key(segment: str) -> tuple[int, str]:
    return (threat_marker_number(segment), segment)


def _draw_scr_by_segment(axes: Axes, subset: pd.DataFrame, individual: bool) -> None:
    """SCR/min per threat-marker segment (marker N -> N+1), all sessions pooled per subject."""
    by_segment: dict[str, list[str]] = {}
    for (_session, segment), columns in _scr_columns(subset).items():
        by_segment.setdefault(segment, []).extend(columns)
    segments = sorted(by_segment, key=_segment_sort_key)
    if not segments:
        axes.text(0.5, 0.5, "No threat-marker segments in the output yet", ha="center")
        axes.set_axis_off()
        return
    icon = ACTOR_CLASS_ICONS.get(THREAT_MARKER_CLASS, "")
    _bar(
        axes,
        [f"{icon}{threat_marker_number(s)}→{threat_marker_number(s) + 1}" for s in segments],
        [_per_subject_mean(subset, by_segment[s]) for s in segments],
        individual,
        "#de2d26",
    )
    axes.tick_params(axis="x", labelrotation=90)
    axes.set_title(
        "EDA: SCR per minute by threat-marker segment (marker N → N+1), all sessions",
        fontsize=11,
    )
    axes.set_ylabel("SCR/min" + ("" if individual else " (mean)"), fontsize=8)


def _draw_scr_by_session(axes: Axes, subset: pd.DataFrame, individual: bool) -> None:
    by_session: dict[str, list[str]] = {}
    for (session, _actor), columns in _scr_columns(subset).items():
        by_session.setdefault(session, []).extend(columns)
    sessions = sorted(by_session)
    if not sessions:
        axes.set_axis_off()
        return
    _bar(
        axes,
        [f"ses-{s}" for s in sessions],
        [_per_subject_mean(subset, by_session[s]) for s in sessions],
        individual,
        "#3182bd",
    )
    axes.set_title("EDA: SCR per minute by session", fontsize=11)
    axes.set_ylabel("SCR/min" + ("" if individual else " (mean)"), fontsize=8)


def _draw_session_status(axes: Axes, subset: pd.DataFrame) -> None:
    """Per session: how many selected subjects came out OK / corrected / error."""
    status_columns = sorted(c for c in subset.columns if SESSION_STATUS_PATTERN.match(str(c)))
    if not status_columns:
        axes.set_axis_off()
        return
    order = (ProcessingStatus.OK, ProcessingStatus.CORRECTED, ProcessingStatus.ERROR)
    colors = {
        ProcessingStatus.OK: "#31a354",
        ProcessingStatus.CORRECTED: "#fdae6b",
        ProcessingStatus.ERROR: "#de2d26",
    }
    labels = [f"ses-{c.removeprefix('ses').split('_', 1)[0]}" for c in status_columns]
    bottoms = [0] * len(status_columns)
    for status in order:
        counts = [
            sum(
                worst_status(str(value)) == status
                for value in subset[column].dropna()
                if str(value).strip()
            )
            for column in status_columns
        ]
        axes.bar(labels, counts, bottom=bottoms, color=colors[status], label=status.value)
        bottoms = [b + c for b, c in zip(bottoms, counts, strict=True)]
    axes.set_title("Sessions processed, by status", fontsize=11)
    axes.set_ylabel("Subjects", fontsize=8)
    axes.tick_params(labelsize=8)
    axes.legend(fontsize=7, loc="upper right")


def build_longwalk3_group_dashboard(
    figure: Figure, batch_df: pd.DataFrame, subject_ids: list[str]
) -> None:
    """`ProcessResultsConfig.build_group_dashboard` for LongwalkV3: SCR per minute by
    threat-marker segment, SCR per minute by session, and per-session processing status.
    Behaviour/debrief metrics come later (D1)."""
    gridspec = figure.add_gridspec(2, 2, height_ratios=[1.3, 1])
    subset = batch_df.loc[batch_df["Subject_ID"].isin(subject_ids)]
    individual = len(subject_ids) == 1
    _draw_scr_by_segment(figure.add_subplot(gridspec[0, :]), subset, individual)
    _draw_scr_by_session(figure.add_subplot(gridspec[1, 0]), subset, individual)
    _draw_session_status(figure.add_subplot(gridspec[1, 1]), subset)


def longwalk3_dashboard_overhead_lines(batch_df: pd.DataFrame, subject_ids: list[str]) -> list[str]:
    """Status readout for the Activity Log (plain text, no icons beyond the shared status
    marks): overall status counts and how many sessions each subject has processed."""
    subset = batch_df.loc[batch_df["Subject_ID"].isin(subject_ids)]
    no_output = len(subject_ids) - len(subset)
    statuses = subset["Processing_Status"] if "Processing_Status" in subset.columns else []
    counts = Counter(worst_status(str(value)) for value in statuses)
    parts = [f"{STATUS_ICON[s][0]} {n} {s.value}" for s, n in counts.items()]
    if no_output:
        parts.append(f"{STATUS_ICON[ProcessingStatus.NOT_RUN][0]} {no_output} no output yet")
    lines = ["Status: " + ("    ".join(parts) if parts else "No subjects selected")]

    status_columns = [c for c in subset.columns if SESSION_STATUS_PATTERN.match(str(c))]
    if status_columns and not subset.empty:
        per_subject = subset[status_columns].notna().sum(axis=1)
        lines.append(
            f"Sessions processed per subject: median {float(per_subject.median()):g}, "
            f"range {int(per_subject.min())}-{int(per_subject.max())}"
        )
        corrected = sum(
            "TrialIntervals=corrected" in str(value)
            for column in status_columns
            for value in subset[column].dropna()
        )
        if corrected:
            lines.append(
                f"Sessions with interpolated trigger times (TrialIntervals=corrected): "
                f"{corrected} -- see their Interval_qc plots"
            )
    return lines


LONGWALK3_PROCESS_RESULTS_CONFIG = ProcessResultsConfig(
    dataset_name="longwalk3",
    window_title="LongwalkV3 Process Results",
    csv_glob=f"*{BATCH_OUTPUT_STEM}.csv",
    process_bids_folder=_process_bids_folder,
    bids_physio_glob=PHYSIO_GLOB_PATTERN,
    bids_subject_id_from_path=subject_id_from_bids_path,
    build_group_dashboard=build_longwalk3_group_dashboard,
    dashboard_overhead_lines=longwalk3_dashboard_overhead_lines,
    window_icon_path=Path("assets") / "longwalkv3_icon.png",
)


def main() -> None:
    run_process_results_app(
        LONGWALK3_PROCESS_RESULTS_CONFIG, settings_app_name="LongwalkV3ProcessResults"
    )


if __name__ == "__main__":
    main()
