"""
mobi_spiral_process_batch_combined_preferred.py

Batch checker / processor for Graphomotor Spiral XDF files.

Main logic:
    For each participant, scan ALL .xdf files and choose ONE TASK XDF.

    Selection priority:
        1) Prefer XDFs that contain Pen/iPad + continuous Neon gaze + EEG together.
        2) If none exist, prefer Pen/iPad + continuous Neon gaze together.
        3) If none exist, choose the XDF with the most Pen/iPad samples.
        4) Tie-breakers: more Neon gaze samples, more EEG samples, more EDA/ECG samples,
           then more total samples.

Why:
    Most participants may not have EEG because EEG collection started recently.
    But when an EEG-containing task XDF exists, it should win over an older/longer
    file that has Pen + Neon but no EEG. This prevents cases like:
        *_old1.xdf has more Pen but no EEG
        *_eeg.xdf has Pen + Neon + EEG
    where the *_eeg.xdf is the correct synchronized file.

Outputs:
    1) spiral_all_xdf_candidates.csv
       - one row per XDF candidate
       - shows Pen, Neon, EEG, EDA, ECG sample counts for every file
       - shows Selection_Class so you can see why a file can/cannot win

    2) spiral_selected_xdf_summary.csv
       - one selected XDF per participant
       - QC_Status / Missing_Items
       - selection reason

    3) PNG per selected participant folder:
       - selected stream presence timeline
       - raw EEG preview PNG in the same style as the previous code
       - C3/C4 raw EEG preview PNG if EEG exists in the selected XDF
       - optional existing EEG/EDA QC plots if processing succeeds

Run from repo root:
    PYTHONPATH=src .venv/bin/python src/mooi_toolbox/cli/mobi_spiral_process_batch_combined_preferred.py \
        src/mooi_toolbox/test_data \
        src/mooi_toolbox/output_data \
        --verbose

Fast QC only, no heavy EEG/EDA processing:
    PYTHONPATH=src .venv/bin/python src/mooi_toolbox/cli/mobi_spiral_process_batch_combined_preferred.py \
        src/mooi_toolbox/test_data \
        src/mooi_toolbox/output_data \
        --verbose \
        --skip-heavy-processing
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

import click
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mooi_toolbox import mobi_logging
from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.eeg import EEGProcessingError, run_spiral_eeg_processing
from mooi_toolbox.processing.plot_utils import save_plot
from mooi_toolbox.read_mobi_xdf import xdf_io

logger = logging.getLogger(__name__)

EDA_COLUMN_NAMES = {"eda", "eda0", "gsr", "gsr0"}
ECG_COLUMN_NAMES = {"ecg", "ecg0", "ecg1", "ekg", "ekg0"}

EEG_LABELS = {
    "fp1", "fp2", "f3", "f4", "f7", "f8", "fz",
    "c3", "c4", "cz",
    "t3", "t4", "t5", "t6", "t7", "t8",
    "p3", "p4", "pz",
    "o1", "o2", "oz",
}


# -----------------------------------------------------------------------------
# Safe stream helpers
# -----------------------------------------------------------------------------

def safe_first(value: Any, default: str = "") -> str:
    try:
        if isinstance(value, list) and len(value) > 0:
            return str(value[0])
        return str(value)
    except Exception:
        return default


def get_stream_name(stream: dict) -> str:
    return safe_first(stream.get("info", {}).get("name", [""]))


def get_stream_type(stream: dict) -> str:
    return safe_first(stream.get("info", {}).get("type", [""]))


def get_nominal_srate(stream: dict) -> float:
    try:
        return float(safe_first(stream.get("info", {}).get("nominal_srate", [0]), "0"))
    except Exception:
        return 0.0


def get_n_samples(stream: dict | None) -> int:
    if stream is None:
        return 0
    try:
        return int(len(stream.get("time_series", [])))
    except Exception:
        return 0


def get_effective_srate(stream: dict | None) -> float:
    if stream is None:
        return 0.0

    time_stamps = stream.get("time_stamps", [])

    if len(time_stamps) < 2:
        return 0.0

    duration = float(time_stamps[-1] - time_stamps[0])

    if duration <= 0:
        return 0.0

    return float(len(time_stamps) / duration)


def get_duration_sec(stream: dict | None) -> float:
    if stream is None:
        return 0.0

    time_stamps = stream.get("time_stamps", [])

    if len(time_stamps) < 2:
        return 0.0

    return max(float(time_stamps[-1] - time_stamps[0]), 0.0)


def get_column_names_from_stream(stream: dict | None) -> list[str]:
    if stream is None:
        return []

    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        labels = []
        for i, channel in enumerate(channels):
            label = safe_first(channel.get("label", [f"channel_{i}"]))
            labels.append(label if label else f"channel_{i}")
        return labels
    except Exception:
        time_series = stream.get("time_series", [])

        if len(time_series) == 0:
            return []

        first_sample = time_series[0]

        if hasattr(first_sample, "__len__") and not isinstance(first_sample, str):
            n_channels = len(first_sample)
        else:
            n_channels = 1

        return [f"channel_{i}" for i in range(n_channels)]


def make_unique_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []

    for column in columns:
        base = str(column)
        if base not in seen:
            seen[base] = 0
            out.append(base)
        else:
            seen[base] += 1
            out.append(f"{base}_{seen[base]}")

    return out


def stream_to_dataframe(stream: dict) -> pd.DataFrame:
    column_names = make_unique_columns(get_column_names_from_stream(stream))

    if len(column_names) == 0:
        raise ValueError("Stream has no samples or no channel names.")

    time_series = stream.get("time_series", [])

    if len(time_series) == 0:
        raise ValueError("Stream has no samples.")

    df = pd.DataFrame(time_series, columns=column_names)
    df.insert(0, "time_stamps", stream.get("time_stamps", []))

    return df


def stream_text(stream: dict) -> str:
    name = get_stream_name(stream).lower()
    stream_type = get_stream_type(stream).lower()
    columns = " ".join(get_column_names_from_stream(stream)).lower()
    return f"{name} {stream_type} {columns}"


# -----------------------------------------------------------------------------
# Stream detection
# -----------------------------------------------------------------------------

def is_eeg_stream(stream: dict) -> bool:
    """Detect DSI/dsi2lsl EEG streams broadly."""
    if get_n_samples(stream) == 0:
        return False

    name = get_stream_name(stream).lower()
    stream_type = get_stream_type(stream).lower()
    text = stream_text(stream)
    columns = [c.lower() for c in get_column_names_from_stream(stream)]

    if name == "eeg" or stream_type == "eeg":
        return True

    if "eeg" in name or "eeg" in stream_type or "dsi" in name or "dsi" in text:
        return True

    n_eeg_like_columns = sum(c in EEG_LABELS for c in columns)
    return n_eeg_like_columns >= 4


def is_pen_stream(stream: dict) -> bool:
    """Detect iPad / MindLogger / drawing / pen stream.

    In this project the iPad/MindLogger stream may also show up as OpenSignals-like
    or live_event depending on naming. We keep this broad but require non-zero samples.
    """
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)

    return any(
        key in text
        for key in [
            "mindlogger",
            "live_event",
            "drawing",
            "draw",
            "spiral",
            "ipad",
            "apple_pencil",
            "pencil",
            "pen",
            "touch",
        ]
    )


def is_continuous_neon_gaze_stream(stream: dict) -> bool:
    """Detect continuous Neon gaze, not merely Neon events.

    Neon event streams can be present with 0/few samples. For gaze QC, we want the
    stream with actual gaze samples, commonly type/name containing Gaze.
    """
    if get_n_samples(stream) == 0:
        return False

    name = get_stream_name(stream).lower()
    stream_type = get_stream_type(stream).lower()
    text = stream_text(stream)
    n_samples = get_n_samples(stream)
    n_channels = len(get_column_names_from_stream(stream))

    # Avoid counting event/marker streams as gaze.
    if any(bad in text for bad in ["event", "marker", "scene camera marker"]):
        if "gaze" not in text:
            return False

    if "gaze" in name or "gaze" in stream_type or "gaze" in text:
        return n_samples > 5

    # Broad fallback for Neon/Pupil continuous eye streams.
    if any(key in text for key in ["neon", "pupil", "eye", "fixation", "saccade"]):
        return n_samples > 100 and n_channels >= 2

    return False


def is_any_neon_stream(stream: dict) -> bool:
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)
    return any(key in text for key in ["neon", "gaze", "pupil", "eye", "fixation", "saccade", "scene camera", "scenecamera"])


def is_eda_stream(stream: dict) -> bool:
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)
    columns = {c.lower() for c in get_column_names_from_stream(stream)}

    return (
        len(columns.intersection(EDA_COLUMN_NAMES)) > 0
        or "eda" in text
        or "gsr" in text
        or "electrodermal" in text
    )


def is_ecg_stream(stream: dict) -> bool:
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)
    columns = {c.lower() for c in get_column_names_from_stream(stream)}

    return (
        len(columns.intersection(ECG_COLUMN_NAMES)) > 0
        or "ecg" in text
        or "ekg" in text
        or "cardio" in text
    )


def find_streams(streams: list[dict], predicate: Callable[[dict], bool]) -> list[dict]:
    return [stream for stream in streams if predicate(stream)]


def find_largest_stream(streams: list[dict], predicate: Callable[[dict], bool]) -> dict | None:
    candidates = find_streams(streams, predicate)
    if len(candidates) == 0:
        return None
    return max(candidates, key=get_n_samples)


def find_eda_stream_and_column(streams: list[dict]) -> tuple[dict | None, str | None]:
    candidates = find_streams(streams, is_eda_stream)

    for stream in sorted(candidates, key=get_n_samples, reverse=True):
        for column in get_column_names_from_stream(stream):
            if column.lower() in EDA_COLUMN_NAMES:
                return stream, column

    if len(candidates) > 0:
        return candidates[0], None

    return None, None


# -----------------------------------------------------------------------------
# Candidate summaries and selection
# -----------------------------------------------------------------------------

def summarise_xdf_candidate(xdf_fn: Path, streams: list[dict]) -> dict:
    subject_id = xdf_io.get_subject_id(xdf_fn)

    pen_stream = find_largest_stream(streams, is_pen_stream)
    neon_gaze_stream = find_largest_stream(streams, is_continuous_neon_gaze_stream)
    any_neon_stream = find_largest_stream(streams, is_any_neon_stream)
    eeg_stream = find_largest_stream(streams, is_eeg_stream)
    eda_stream = find_largest_stream(streams, is_eda_stream)
    ecg_stream = find_largest_stream(streams, is_ecg_stream)

    pen_samples = get_n_samples(pen_stream)
    neon_gaze_samples = get_n_samples(neon_gaze_stream)
    any_neon_samples = get_n_samples(any_neon_stream)
    eeg_samples = get_n_samples(eeg_stream)
    eda_samples = get_n_samples(eda_stream)
    ecg_samples = get_n_samples(ecg_stream)
    total_samples = sum(get_n_samples(stream) for stream in streams)

    has_pen = pen_samples > 0
    has_neon_gaze = neon_gaze_samples > 0
    has_eeg = eeg_samples > 0

    if has_pen and has_neon_gaze and has_eeg:
        selection_class = 3
        selection_label = "BEST: Pen + Neon gaze + EEG in same XDF"
    elif has_pen and has_neon_gaze:
        selection_class = 2
        selection_label = "GOOD: Pen + Neon gaze in same XDF, no EEG"
    elif has_pen:
        selection_class = 1
        selection_label = "PARTIAL: Pen present, missing continuous Neon gaze"
    else:
        selection_class = 0
        selection_label = "LOW: No pen/iPad stream detected"

    selection_tuple = (
        selection_class,
        pen_samples,
        neon_gaze_samples,
        eeg_samples,
        eda_samples + ecg_samples,
        total_samples,
    )

    return {
        "Subject_ID": subject_id,
        "XDF_File": xdf_fn.name,
        "XDF_Path": str(xdf_fn),
        "Selection_Class": selection_class,
        "Selection_Label": selection_label,
        "Selection_Tuple": str(selection_tuple),
        "Selected_By": "Prefer Pen+Neon+EEG together, else Pen+Neon, else most Pen; tie-break by Neon, EEG, EDA/ECG, total samples",
        "Pen_Present": has_pen,
        "Pen_Samples": pen_samples,
        "Pen_Stream_Name": get_stream_name(pen_stream) if pen_stream is not None else "",
        "Pen_Stream_Type": get_stream_type(pen_stream) if pen_stream is not None else "",
        "Pen_Effective_SRate": round(get_effective_srate(pen_stream), 3),
        "Pen_Duration_sec": round(get_duration_sec(pen_stream), 3),
        "Neon_Gaze_Present": has_neon_gaze,
        "Neon_Gaze_Samples": neon_gaze_samples,
        "Neon_Gaze_Stream_Name": get_stream_name(neon_gaze_stream) if neon_gaze_stream is not None else "",
        "Neon_Gaze_Stream_Type": get_stream_type(neon_gaze_stream) if neon_gaze_stream is not None else "",
        "Neon_Gaze_Effective_SRate": round(get_effective_srate(neon_gaze_stream), 3),
        "Neon_Gaze_Duration_sec": round(get_duration_sec(neon_gaze_stream), 3),
        "Any_Neon_Present": any_neon_samples > 0,
        "Any_Neon_Samples": any_neon_samples,
        "Any_Neon_Stream_Name": get_stream_name(any_neon_stream) if any_neon_stream is not None else "",
        "Any_Neon_Stream_Type": get_stream_type(any_neon_stream) if any_neon_stream is not None else "",
        "EEG_Present": has_eeg,
        "EEG_Samples": eeg_samples,
        "EEG_Stream_Name": get_stream_name(eeg_stream) if eeg_stream is not None else "",
        "EEG_Stream_Type": get_stream_type(eeg_stream) if eeg_stream is not None else "",
        "EEG_Effective_SRate": round(get_effective_srate(eeg_stream), 3),
        "EEG_Duration_sec": round(get_duration_sec(eeg_stream), 3),
        "EDA_Present": eda_samples > 0,
        "EDA_Samples": eda_samples,
        "EDA_Stream_Name": get_stream_name(eda_stream) if eda_stream is not None else "",
        "ECG_Present": ecg_samples > 0,
        "ECG_Samples": ecg_samples,
        "ECG_Stream_Name": get_stream_name(ecg_stream) if ecg_stream is not None else "",
        "Total_Streams": len(streams),
        "Total_NonEmpty_Streams": sum(get_n_samples(stream) > 0 for stream in streams),
        "Total_Samples_All_Streams": total_samples,
    }


def load_all_xdf_candidates(root: Path, verbose: bool = False) -> tuple[pd.DataFrame, dict[str, list[dict]]]:
    rows = []
    streams_by_path: dict[str, list[dict]] = {}

    for xdf_fn in sorted(root.rglob("*.xdf")):
        try:
            streams = get_and_check_xdf(xdf_fn, verbose=False)
        except Exception as error:
            logger.warning("Skipping %s because XDF could not be loaded: %s", xdf_fn.name, error)
            continue

        row = summarise_xdf_candidate(xdf_fn, streams)
        rows.append(row)
        streams_by_path[str(xdf_fn)] = streams

        if verbose:
            logger.info(
                "Candidate subject=%s file=%s class=%s pen=%s neon_gaze=%s eeg=%s label=%s",
                row["Subject_ID"],
                row["XDF_File"],
                row["Selection_Class"],
                row["Pen_Samples"],
                row["Neon_Gaze_Samples"],
                row["EEG_Samples"],
                row["Selection_Label"],
            )

    return pd.DataFrame(rows), streams_by_path


def choose_best_xdfs(candidates_df: pd.DataFrame) -> pd.DataFrame:
    if candidates_df.empty:
        return candidates_df

    selected_rows = []

    for subject_id, group in candidates_df.groupby("Subject_ID", sort=True):
        pool = group.copy()

        pool = pool.sort_values(
            [
                "Selection_Class",
                "Pen_Samples",
                "Neon_Gaze_Samples",
                "EEG_Samples",
                "EDA_Samples",
                "ECG_Samples",
                "Total_Samples_All_Streams",
            ],
            ascending=[False, False, False, False, False, False, False],
        )

        best = pool.iloc[0].copy()

        if int(best["Selection_Class"]) == 3:
            note = "Selected combined synchronized XDF with Pen + Neon gaze + EEG."
        elif int(best["Selection_Class"]) == 2:
            note = "Selected best Pen + Neon gaze XDF. EEG not present in this participant/task XDF."
        elif int(best["Selection_Class"]) == 1:
            note = "Selected file with most Pen samples, but continuous Neon gaze is missing."
        else:
            note = "No Pen/iPad stream detected; selected highest available candidate for inspection."

        # Extra warning if EEG exists for the subject but not in the selected task XDF.
        subject_has_any_eeg = bool((group["EEG_Samples"] > 0).any())
        selected_has_eeg = int(best["EEG_Samples"]) > 0

        if subject_has_any_eeg and not selected_has_eeg:
            eeg_files = group.loc[group["EEG_Samples"] > 0, "XDF_File"].tolist()
            note += " WARNING: EEG exists in another XDF for this participant, but not in the selected task XDF: " + "; ".join(eeg_files)

        best["Selection_Note"] = note
        best["Subject_Has_Any_EEG_XDF"] = subject_has_any_eeg
        best["Selected_XDF_Has_EEG"] = selected_has_eeg
        selected_rows.append(best)

    best_df = pd.DataFrame(selected_rows)
    best_df.insert(0, "Selected_XDF", True)

    return best_df.reset_index(drop=True)


def add_qc_flags(selected_df: pd.DataFrame) -> pd.DataFrame:
    if selected_df.empty:
        return selected_df

    out = selected_df.copy()
    missing_items = []
    qc_status = []

    for _, row in out.iterrows():
        missing = []

        if int(row.get("Pen_Samples", 0) or 0) <= 0:
            missing.append("Pen")

        if int(row.get("Neon_Gaze_Samples", 0) or 0) <= 0:
            missing.append("Neon_Gaze")

        # EEG is optional because collection started recently. We do not mark the
        # whole file as bad just because EEG is absent.
        if bool(row.get("Subject_Has_Any_EEG_XDF", False)) and not bool(row.get("Selected_XDF_Has_EEG", False)):
            missing.append("EEG_NOT_IN_SELECTED_XDF")

        missing_items.append("; ".join(missing))
        qc_status.append("OK" if len(missing) == 0 else "CHECK: " + ", ".join(missing))

    out.insert(1, "QC_Status", qc_status)
    out.insert(2, "Missing_Items", missing_items)

    priority = [
        "Selected_XDF",
        "QC_Status",
        "Missing_Items",
        "Subject_ID",
        "XDF_File",
        "XDF_Path",
        "Selection_Class",
        "Selection_Label",
        "Selection_Note",
        "Pen_Present",
        "Pen_Samples",
        "Neon_Gaze_Present",
        "Neon_Gaze_Samples",
        "EEG_Present",
        "EEG_Samples",
        "Subject_Has_Any_EEG_XDF",
        "Selected_XDF_Has_EEG",
        "EDA_Present",
        "EDA_Samples",
        "ECG_Present",
        "ECG_Samples",
    ]
    remaining = [c for c in out.columns if c not in priority]

    return out[[c for c in priority if c in out.columns] + remaining]


# -----------------------------------------------------------------------------
# Plotting
# -----------------------------------------------------------------------------

def ensure_subject_output_folder(output_folder: Path, subject_id: str) -> Path:
    subject_folder = output_folder / subject_id
    subject_folder.mkdir(parents=True, exist_ok=True)
    return subject_folder


def save_matplotlib_figure(fig, out_path: Path):
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def remove_unwanted_old_pngs(subject_folder: Path, subject_id: str):
    unwanted_patterns = [
        f"{subject_id}_selected_stream_sample_counts.png",
        f"{subject_id}_pen_spiral_xy.png",
        f"{subject_id}_neon_gaze_xy.png",
    ]

    for pattern in unwanted_patterns:
        for path in subject_folder.glob(pattern):
            try:
                path.unlink()
            except Exception as error:
                logger.info("Could not remove old unwanted PNG %s: %s", path, error)


def plot_stream_presence_timeline(
    streams: list[dict],
    subject_id: str,
    out_folder: Path,
    summary_row: pd.Series | None = None,
):
    rows = []
    global_start = None

    for stream in streams:
        ts = stream.get("time_stamps", [])
        if len(ts) < 2:
            continue

        start = float(ts[0])
        end = float(ts[-1])

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

    if len(rows) == 0 or global_start is None:
        return

    key_rows = []

    for label, predicate in [
        ("Pen/iPad", is_pen_stream),
        ("Neon gaze", is_continuous_neon_gaze_stream),
        ("EEG", is_eeg_stream),
        ("EDA", is_eda_stream),
        ("ECG", is_ecg_stream),
    ]:
        stream = find_largest_stream(streams, predicate)

        if stream is not None and len(stream.get("time_stamps", [])) >= 2:
            ts = stream.get("time_stamps", [])
            key_rows.append(
                {
                    "label": f"KEY: {label} — {get_stream_name(stream)} ({get_stream_type(stream)})",
                    "start": float(ts[0]),
                    "end": float(ts[-1]),
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

    other_rows = []
    key_label_names = [row["label"] for row in key_rows]
    for row in sorted(rows, key=lambda x: x["start"]):
        if not any(row["label"] in key_label for key_label in key_label_names):
            other_rows.append(row)

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

    save_matplotlib_figure(fig, out_folder / f"{subject_id}_selected_stream_presence_timeline.png")


def find_channel_column(df: pd.DataFrame, wanted: str) -> str | None:
    wanted_lower = wanted.lower()
    for col in df.columns:
        if col.lower() == wanted_lower:
            return col
    for col in df.columns:
        if col.lower().replace(" ", "").replace("_", "") == wanted_lower:
            return col
    return None


def plot_c3_c4_eeg_preview(eeg_stream: dict | None, subject_id: str, out_folder: Path):
    """Keep the C3/C4 EEG PNG requested by the user.

    This only plots C3/C4 from the selected XDF. If selected XDF has no EEG, the
    figure is not made because that would hide synchronization problems.
    """
    if eeg_stream is None or get_n_samples(eeg_stream) == 0:
        logger.info("No C3/C4 EEG preview made for %s because selected XDF has no EEG.", subject_id)
        return

    try:
        df = stream_to_dataframe(eeg_stream)
    except Exception as error:
        logger.info("Could not convert EEG stream to dataframe for %s: %s", subject_id, error)
        return

    c3_col = find_channel_column(df, "C3")
    c4_col = find_channel_column(df, "C4")

    channels_to_plot = []
    if c3_col is not None:
        channels_to_plot.append(c3_col)
    if c4_col is not None:
        channels_to_plot.append(c4_col)

    if len(channels_to_plot) == 0:
        logger.info("No C3/C4 columns found for %s. Available columns: %s", subject_id, list(df.columns))
        return

    max_points = min(15000, len(df))
    plot_df = df.iloc[:max_points].copy()

    t = pd.to_numeric(plot_df["time_stamps"], errors="coerce")
    if t.notna().sum() < 2:
        t = pd.Series(np.arange(len(plot_df)), index=plot_df.index)
    else:
        t = t - t.iloc[0]

    fig, ax = plt.subplots(figsize=(13, 5))

    for col in channels_to_plot:
        y = pd.to_numeric(plot_df[col], errors="coerce")
        if y.notna().sum() < 5:
            continue
        ax.plot(t, y, linewidth=0.8, label=col)

    ax.set_xlabel("Seconds from EEG start in selected XDF")
    ax.set_ylabel("Raw EEG amplitude")
    ax.set_title(f"{subject_id}: raw EEG C3/C4 preview from selected XDF ({get_n_samples(eeg_stream)} samples)")
    ax.legend(loc="best")

    save_matplotlib_figure(fig, out_folder / f"{subject_id}_raw_eeg_C3_C4_selected_xdf.png")


def plot_raw_eeg_preview(eeg_stream: dict | None, subject_id: str, out_folder: Path):
    """Save the older/raw EEG preview PNG style.

    This matches the previous code style: first available EEG channels, scaled and
    vertically offset, so it is easy to see that EEG is present and changing.
    It is made only from the selected XDF so it stays synchronized with Pen/Neon.
    """
    if eeg_stream is None or get_n_samples(eeg_stream) == 0:
        logger.info("No raw EEG preview made for %s because selected XDF has no EEG.", subject_id)
        return

    try:
        df = stream_to_dataframe(eeg_stream)
    except Exception as error:
        logger.info("Could not convert EEG stream to dataframe for %s: %s", subject_id, error)
        return

    eeg_cols = [c for c in df.columns if c != "time_stamps"]
    if len(eeg_cols) == 0:
        logger.info("No EEG columns found for raw EEG preview for %s.", subject_id)
        return

    plot_cols = eeg_cols[: min(8, len(eeg_cols))]
    max_points = min(3000, len(df))
    plot_df = df.iloc[:max_points].copy()

    t = pd.to_numeric(plot_df["time_stamps"], errors="coerce")
    if t.notna().sum() < 2:
        t = pd.Series(np.arange(len(plot_df)), index=plot_df.index)
    else:
        t = t - t.iloc[0]

    fig, ax = plt.subplots(figsize=(12, 6))
    offset = 0.0
    plotted = 0

    for col in plot_cols:
        y = pd.to_numeric(plot_df[col], errors="coerce")
        if y.notna().sum() < 5:
            continue

        y = y - np.nanmedian(y)
        spread = float(np.nanpercentile(np.abs(y), 95))
        if spread <= 0 or not np.isfinite(spread):
            spread = 1.0

        y = y / spread
        ax.plot(t, y + offset, linewidth=0.8, label=col)
        offset += 3.0
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        logger.info("No usable numeric EEG columns found for raw EEG preview for %s.", subject_id)
        return

    ax.set_xlabel("Seconds from EEG start in selected XDF")
    ax.set_ylabel("Channels, scaled and offset")
    ax.set_title(
        f"{subject_id}: raw EEG preview from selected XDF "
        f"({get_n_samples(eeg_stream)} samples, first {max_points} shown)"
    )
    ax.legend(loc="upper right", fontsize=8, ncol=2)

    save_matplotlib_figure(fig, out_folder / f"{subject_id}_raw_eeg_preview.png")


# -----------------------------------------------------------------------------
# Optional heavy processing
# -----------------------------------------------------------------------------

def process_eda_stream(stream: dict, eda_column: str, subject_id: str, output_folder: Path) -> pd.DataFrame:
    eda_raw_timestamped = stream_to_dataframe(stream)

    if eda_column != "EDA":
        eda_raw_timestamped = eda_raw_timestamped.rename(columns={eda_column: "EDA"})

    sampling_rate = get_effective_srate(stream)
    if sampling_rate <= 0:
        sampling_rate = get_nominal_srate(stream)
    if sampling_rate <= 0:
        sampling_rate = 1000

    logger.info("Processing EDA for %s with sampling rate %.3f Hz", subject_id, sampling_rate)

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
        save_plot(fig, str(output_folder), subject_id, f"Subject {subject_id} EDA QC")
    except Exception as error:
        logger.info("Error saving EDA plot for %s: %s", subject_id, error)

    return eda_data_out


def run_optional_processing(streams: list[dict], subject_id: str, xdf_fn: Path, subject_folder: Path) -> pd.DataFrame:
    parts = []

    eda_stream, eda_column = find_eda_stream_and_column(streams)
    eeg_stream = find_largest_stream(streams, is_eeg_stream)

    if eda_stream is not None and eda_column is not None:
        try:
            eda_out = process_eda_stream(eda_stream, eda_column, subject_id, subject_folder)
            parts.append(eda_out.reset_index(drop=True))
            logger.info("Done EDA processing for %s", subject_id)
        except Exception as error:
            logger.warning("Skipping EDA processing for %s because it failed: %s", subject_id, error)
    elif eda_stream is not None:
        logger.info("EDA-like stream found for %s, but no clear EDA column name was found.", subject_id)

    if eeg_stream is not None:
        try:
            eeg_proc_out = run_spiral_eeg_processing(
                eeg_stream=eeg_stream,
                streams=streams,
                subject_id=subject_id,
                show_plots=False,
            )

            eeg_data_out = eeg_proc_out["summary_data"]
            parts.append(eeg_data_out.reset_index(drop=True))

            try:
                save_plot(
                    eeg_proc_out["qc_figure"],
                    str(subject_folder),
                    subject_id,
                    f"Subject {subject_id} Spiral EEG QC",
                )
                save_plot(
                    eeg_proc_out["all_channels_figure"],
                    str(subject_folder),
                    subject_id,
                    f"Subject {subject_id} EEG All Channels Entire Run",
                )
            except Exception as error:
                logger.info("Error saving EEG plots for %s: %s", subject_id, error)

            logger.info("Done spiral EEG processing for %s", subject_id)

        except EEGProcessingError as error:
            logger.warning("Skipping EEG processing for %s because it failed: %s", subject_id, error)
        except Exception as error:
            logger.warning("Skipping EEG processing for %s because it failed: %s", subject_id, error)

    if len(parts) == 0:
        return pd.DataFrame()

    out = pd.concat(parts, axis=1)

    for column in ["Subject_ID", "XDF_File"]:
        if column in out.columns:
            out = out.drop(columns=[column])

    out.insert(0, "XDF_File", xdf_fn.name)
    out.insert(0, "Subject_ID", subject_id)

    return out


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

@click.command()
@click.argument("input_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.argument("output_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.option("--verbose", is_flag=True, help="Give verbose output")
@click.option(
    "--skip-heavy-processing",
    is_flag=True,
    help="Only make selection summaries and simple PNGs; skip EDA/EEG processing.",
)
def main(input_folder: str, output_folder: str, verbose: bool, skip_heavy_processing: bool):
    """Choose best synchronized spiral XDF per participant."""

    root = Path(input_folder)
    output_root = Path(output_folder)
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Looking into input folder: %s", root)
    logger.info("Output folder: %s", output_root)
    logger.info("Selection rule: prefer Pen + Neon gaze + EEG together; else Pen + Neon; else most Pen.")

    candidates_df, streams_by_path = load_all_xdf_candidates(root, verbose=verbose)

    all_candidates_fn = output_root / "spiral_all_xdf_candidates.csv"
    selected_summary_fn = output_root / "spiral_selected_xdf_summary.csv"
    processing_out_fn = output_root / "spiral_selected_processing_out.csv"

    if candidates_df.empty:
        logger.warning("No usable XDF files found.")
        return

    candidates_df = candidates_df.sort_values(
        ["Subject_ID", "Selection_Class", "Pen_Samples", "Neon_Gaze_Samples", "EEG_Samples"],
        ascending=[True, False, False, False, False],
    )
    candidates_df.to_csv(all_candidates_fn, index=False)
    logger.info("Saved all XDF candidates to %s", all_candidates_fn)

    selected_df = choose_best_xdfs(candidates_df)

    if selected_df.empty:
        logger.warning("No selected XDF files.")
        return

    selected_df = add_qc_flags(selected_df)
    selected_df.to_csv(selected_summary_fn, index=False)
    logger.info("Saved selected XDF summary to %s", selected_summary_fn)

    processing_parts = []

    for _, row in selected_df.iterrows():
        subject_id = str(row["Subject_ID"])
        xdf_fn = Path(row["XDF_Path"])
        streams = streams_by_path.get(str(xdf_fn))

        if streams is None:
            try:
                streams = get_and_check_xdf(xdf_fn, verbose=False)
            except Exception as error:
                logger.warning("Skipping selected file %s because reload failed: %s", xdf_fn.name, error)
                continue

        mobi_logging.log_section(logger, f"Selected subject {subject_id}")
        logger.info("Selected XDF: %s", xdf_fn.name)
        logger.info("Selection label: %s", row.get("Selection_Label", ""))
        logger.info("Selection note: %s", row.get("Selection_Note", ""))
        logger.info("Pen samples: %s", row.get("Pen_Samples", 0))
        logger.info("Neon gaze samples: %s", row.get("Neon_Gaze_Samples", 0))
        logger.info("EEG samples: %s", row.get("EEG_Samples", 0))

        subject_folder = ensure_subject_output_folder(output_root, subject_id)
        remove_unwanted_old_pngs(subject_folder, subject_id)

        plot_stream_presence_timeline(streams, subject_id, subject_folder, summary_row=row)

        selected_eeg_stream = find_largest_stream(streams, is_eeg_stream)
        plot_raw_eeg_preview(selected_eeg_stream, subject_id, subject_folder)
        plot_c3_c4_eeg_preview(selected_eeg_stream, subject_id, subject_folder)

        if not skip_heavy_processing:
            participant_out = run_optional_processing(streams, subject_id, xdf_fn, subject_folder)
            if not participant_out.empty:
                processing_parts.append(participant_out)

    if len(processing_parts) > 0:
        processing_out = pd.concat(processing_parts, axis=0)
        processing_out.to_csv(processing_out_fn, index=False)
        logger.info("Saved selected processing output to %s", processing_out_fn)
    else:
        logger.info("No heavy processing output saved. Summary CSVs and PNGs were still created.")


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
