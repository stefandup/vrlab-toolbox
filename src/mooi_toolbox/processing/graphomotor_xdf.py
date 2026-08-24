from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf
from mooi_toolbox.processing import lsl

logger = logging.getLogger(__name__)

EDA_COLUMN_NAMES = {"eda", "eda0", "gsr", "gsr0"}
ECG_COLUMN_NAMES = {"ecg", "ecg0", "ecg1", "ekg", "ekg0"}

EEG_LABELS = {
    "fp1",
    "fp2",
    "f3",
    "f4",
    "f7",
    "f8",
    "fz",
    "c3",
    "c4",
    "cz",
    "t3",
    "t4",
    "t5",
    "t6",
    "t7",
    "t8",
    "p3",
    "p4",
    "pz",
    "o1",
    "o2",
    "oz",
}

MIN_DRAWING_INTERVAL_SEC = 2.0
MAX_DRAWING_GAP_SEC = 2.0
MOVEMENT_EPSILON = 1e-6
GOOD_COVERAGE_FRACTION = 0.80

XdfStream = dict[str, Any]
StreamPredicate = Callable[[XdfStream], bool]


def safe_first(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        if not value:
            return default
        return str(value[0])
    return str(value)


def get_stream_name(stream: XdfStream | None) -> str:
    if stream is None:
        return ""
    return safe_first(stream.get("info", {}).get("name", [""]))


def get_stream_type(stream: XdfStream | None) -> str:
    if stream is None:
        return ""
    return safe_first(stream.get("info", {}).get("type", [""]))


def get_nominal_srate(stream: XdfStream | None) -> float:
    if stream is None:
        return 0.0

    value = safe_first(stream.get("info", {}).get("nominal_srate", [0]), "0")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def get_n_samples(stream: XdfStream | None) -> int:
    if stream is None:
        return 0
    return len(stream.get("time_series", []))


def get_effective_srate(stream: XdfStream | None) -> float:
    if stream is None:
        return 0.0

    time_stamps = stream.get("time_stamps", [])
    if len(time_stamps) < 2:
        return 0.0

    try:
        duration = float(time_stamps[-1] - time_stamps[0])
    except (TypeError, ValueError):
        return 0.0

    if duration <= 0:
        return 0.0

    return float(len(time_stamps) / duration)


def get_duration_sec(stream: XdfStream | None) -> float:
    if stream is None:
        return 0.0

    time_stamps = stream.get("time_stamps", [])
    if len(time_stamps) < 2:
        return 0.0

    try:
        duration = float(time_stamps[-1] - time_stamps[0])
    except (TypeError, ValueError):
        return 0.0

    return max(duration, 0.0)


def get_column_names_from_stream(stream: XdfStream | None) -> list[str]:
    if stream is None:
        return []

    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        labels = []
        for i, channel in enumerate(channels):
            label = safe_first(channel.get("label", [f"channel_{i}"]))
            labels.append(label if label else f"channel_{i}")
        return labels
    except (KeyError, TypeError, IndexError):
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
    unique_columns = []

    for column in columns:
        base = str(column)
        if base not in seen:
            seen[base] = 0
            unique_columns.append(base)
            continue

        seen[base] += 1
        unique_columns.append(f"{base}_{seen[base]}")

    return unique_columns


def stream_to_dataframe(stream: XdfStream) -> pd.DataFrame:
    column_names = make_unique_columns(get_column_names_from_stream(stream))
    time_series = stream.get("time_series", [])
    time_stamps = stream.get("time_stamps", [])

    if not column_names:
        raise ValueError("Stream has no channel names.")
    if len(time_series) == 0:
        raise ValueError("Stream has no samples.")
    if len(time_stamps) != len(time_series):
        raise ValueError("Stream sample count does not match timestamp count.")

    dataframe = pd.DataFrame(time_series, columns=column_names)
    dataframe.insert(0, "time_stamps", time_stamps)
    return dataframe


def stream_text(stream: XdfStream) -> str:
    name = get_stream_name(stream).lower()
    stream_type = get_stream_type(stream).lower()
    columns = " ".join(get_column_names_from_stream(stream)).lower()
    return f"{name} {stream_type} {columns}"


def is_eeg_stream(stream: XdfStream) -> bool:
    if get_n_samples(stream) == 0:
        return False

    name = get_stream_name(stream).lower()
    stream_type = get_stream_type(stream).lower()
    text = stream_text(stream)
    columns = [column.lower() for column in get_column_names_from_stream(stream)]

    if name == "eeg" or stream_type == "eeg":
        return True
    if "eeg" in name or "eeg" in stream_type or "dsi" in name or "dsi" in text:
        return True

    n_eeg_like_columns = sum(column in EEG_LABELS for column in columns)
    return n_eeg_like_columns >= 4


def is_pen_stream(stream: XdfStream) -> bool:
    if get_n_samples(stream) == 0:
        return False

    name = get_stream_name(stream).lower().strip()
    stream_type = get_stream_type(stream).lower().strip()
    text = stream_text(stream).lower()

    # Strong identifiers used by the iPad / MindLogger drawing stream.
    strong_keys = (
        "mindlogger",
        "live_event",
        "drawing",
        "draw",
        "spiral",
        "ipad",
        "apple_pencil",
        "pencil",
        "touch",
    )

    if any(key in text for key in strong_keys):
        return True

    # Allow "pen" only as a standalone stream name/type.
    # Do NOT use `"pen" in text`, because "OpenSignals"
    # contains the letters "pen".
    if name == "pen" or stream_type == "pen":
        return True

    return False


def is_continuous_neon_gaze_stream(stream: XdfStream) -> bool:
    if get_n_samples(stream) == 0:
        return False

    name = get_stream_name(stream).lower()
    stream_type = get_stream_type(stream).lower()
    text = stream_text(stream)
    n_samples = get_n_samples(stream)
    n_channels = len(get_column_names_from_stream(stream))

    if any(bad in text for bad in ("event", "marker", "scene camera marker")):
        if "gaze" not in text:
            return False

    if "gaze" in name or "gaze" in stream_type or "gaze" in text:
        return n_samples > 5

    if any(key in text for key in ("neon", "pupil", "eye", "fixation", "saccade")):
        return n_samples > 100 and n_channels >= 2

    return False


def is_any_neon_stream(stream: XdfStream) -> bool:
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)
    return any(
        key in text
        for key in (
            "neon",
            "gaze",
            "pupil",
            "eye",
            "fixation",
            "saccade",
            "scene camera",
            "scenecamera",
        )
    )


def is_eda_stream(stream: XdfStream) -> bool:
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)
    columns = {column.lower() for column in get_column_names_from_stream(stream)}
    return bool(columns.intersection(EDA_COLUMN_NAMES)) or any(
        key in text for key in ("eda", "gsr", "electrodermal")
    )


def is_ecg_stream(stream: XdfStream) -> bool:
    if get_n_samples(stream) == 0:
        return False

    text = stream_text(stream)
    columns = {column.lower() for column in get_column_names_from_stream(stream)}
    return bool(columns.intersection(ECG_COLUMN_NAMES)) or any(
        key in text for key in ("ecg", "ekg", "cardio")
    )


def find_streams(streams: list[XdfStream], predicate: StreamPredicate) -> list[XdfStream]:
    return [stream for stream in streams if predicate(stream)]


def find_largest_stream(
    streams: list[XdfStream],
    predicate: StreamPredicate,
) -> XdfStream | None:
    candidates = find_streams(streams, predicate)
    if not candidates:
        return None
    return max(candidates, key=get_n_samples)


def find_eda_stream_and_column(
    streams: list[XdfStream],
) -> tuple[XdfStream | None, str | None]:
    candidates = find_streams(streams, is_eda_stream)

    for stream in sorted(candidates, key=get_n_samples, reverse=True):
        for column in get_column_names_from_stream(stream):
            if column.lower() in EDA_COLUMN_NAMES:
                return stream, column

    if candidates:
        return candidates[0], None

    return None, None


def _safe_numeric_array(values: Any) -> np.ndarray:
    output = []
    for value in values:
        try:
            output.append(float(value))
        except (TypeError, ValueError):
            output.append(np.nan)
    return np.asarray(output, dtype=float)


def get_pen_movement_intervals(
    pen_stream: XdfStream | None,
) -> tuple[
    list[tuple[float, float]],
    np.ndarray,
    np.ndarray,
    np.ndarray,
]:
    """Detect actual Pen movement using changes in x/y coordinates.

    Repeated non-zero coordinates are NOT treated as drawing. Consecutive
    movement samples are grouped into one interval when they are no more than
    MAX_DRAWING_GAP_SEC apart.
    """
    if pen_stream is None:
        return [], np.asarray([]), np.asarray([]), np.asarray([])

    data = np.asarray(pen_stream.get("time_series", []))
    timestamps = np.asarray(pen_stream.get("time_stamps", []), dtype=float)

    if data.ndim != 2 or data.shape[1] < 2:
        return [], timestamps, np.asarray([]), np.asarray([])
    if len(timestamps) != len(data) or len(timestamps) < 2:
        return [], timestamps, np.asarray([]), np.asarray([])

    x = _safe_numeric_array(data[:, 0])
    y = _safe_numeric_array(data[:, 1])

    dx = np.diff(x, prepend=x[0])
    dy = np.diff(y, prepend=y[0])
    movement_distance = np.sqrt(dx**2 + dy**2)

    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(movement_distance)
    moving = valid & (movement_distance > MOVEMENT_EPSILON)

    moving_idx = np.where(moving)[0]
    if len(moving_idx) == 0:
        return [], timestamps, x, y

    intervals: list[tuple[float, float]] = []

    start_time = float(timestamps[moving_idx[0]])
    previous_time = start_time

    for idx in moving_idx[1:]:
        current_time = float(timestamps[idx])
        gap = current_time - previous_time

        if gap > MAX_DRAWING_GAP_SEC:
            if previous_time - start_time >= MIN_DRAWING_INTERVAL_SEC:
                intervals.append((start_time, previous_time))
            start_time = current_time

        previous_time = current_time

    if previous_time - start_time >= MIN_DRAWING_INTERVAL_SEC:
        intervals.append((start_time, previous_time))

    return intervals, timestamps, x, y


def get_pen_drawing_window(
    pen_stream: XdfStream | None,
) -> tuple[bool, float | None, float | None, float]:
    """Return valid drawing flag, task window, and active movement duration."""
    intervals, _, _, _ = get_pen_movement_intervals(pen_stream)

    if not intervals:
        return False, None, None, 0.0

    drawing_start = intervals[0][0]
    drawing_end = intervals[-1][1]
    drawing_active_duration = sum(end - start for start, end in intervals)

    return (
        True,
        drawing_start,
        drawing_end,
        max(drawing_active_duration, 0.0),
    )


def get_stream_coverage_fraction(
    stream: XdfStream | None,
    window_start: float | None,
    window_end: float | None,
) -> float:
    """Fraction of the Spiral window covered by a stream's timestamps."""
    if stream is None or window_start is None or window_end is None:
        return 0.0
    if window_end <= window_start:
        return 0.0

    timestamps = np.asarray(stream.get("time_stamps", []), dtype=float)
    if len(timestamps) < 2:
        return 0.0

    stream_start = float(timestamps[0])
    stream_end = float(timestamps[-1])

    overlap_start = max(stream_start, window_start)
    overlap_end = min(stream_end, window_end)
    overlap = max(0.0, overlap_end - overlap_start)

    return min(1.0, overlap / (window_end - window_start))


def summarise_xdf_candidate(xdf_fn: Path, streams: list[XdfStream]) -> dict[str, Any]:
    subject_id = lsl.get_subject_id(xdf_fn)

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

    drawing_detected, drawing_start, drawing_end, drawing_active_duration = (
        get_pen_drawing_window(pen_stream)
    )

    drawing_window_duration = (
        float(drawing_end - drawing_start)
        if drawing_start is not None and drawing_end is not None
        else 0.0
    )

    eda_coverage = get_stream_coverage_fraction(eda_stream, drawing_start, drawing_end)
    ecg_coverage = get_stream_coverage_fraction(ecg_stream, drawing_start, drawing_end)
    neon_coverage = get_stream_coverage_fraction(
        neon_gaze_stream,
        drawing_start,
        drawing_end,
    )
    eeg_coverage = get_stream_coverage_fraction(eeg_stream, drawing_start, drawing_end)

    has_pen = pen_samples > 0
    has_neon_gaze = neon_gaze_samples > 0
    has_eeg = eeg_samples > 0
    has_eda = eda_samples > 0
    has_ecg = ecg_samples > 0

    # Ranking deliberately prioritises genuine drawing and physiological
    # coverage over filename or raw sample counts.
    physio_min_coverage = min(eda_coverage, ecg_coverage)
    neuro_min_coverage = min(neon_coverage, eeg_coverage)
    mean_coverage = (
        eda_coverage + ecg_coverage + neon_coverage + eeg_coverage
    ) / 4.0

    is_current_eeg = is_current_eeg_xdf(xdf_fn)

    selection_tuple = (
        int(drawing_detected),
        round(physio_min_coverage, 6),
        round(neuro_min_coverage, 6),
        round(mean_coverage, 6),
        int(is_current_eeg),
        pen_samples,
        total_samples,
    )

    if drawing_detected and all(
        coverage >= GOOD_COVERAGE_FRACTION
        for coverage in (eda_coverage, ecg_coverage, neon_coverage, eeg_coverage)
    ):
        selection_class = 4
        selection_label = "BEST: valid Spiral drawing with strong multimodal coverage"
    elif drawing_detected and (
        eda_coverage >= GOOD_COVERAGE_FRACTION
        and ecg_coverage >= GOOD_COVERAGE_FRACTION
    ):
        selection_class = 3
        selection_label = "GOOD: valid Spiral drawing with strong EDA/ECG coverage"
    elif drawing_detected:
        selection_class = 2
        selection_label = "CHECK: valid drawing but incomplete multimodal coverage"
    elif has_pen:
        selection_class = 1
        selection_label = "LOW: Pen stream present but valid Spiral drawing not detected"
    else:
        selection_class = 0
        selection_label = "LOW: No Pen/iPad stream detected"

    return {
        "Subject_ID": subject_id,
        "XDF_File": xdf_fn.name,
        "XDF_Path": str(xdf_fn),
        "Selection_Class": selection_class,
        "Selection_Label": selection_label,
        "Selection_Tuple": str(selection_tuple),
        "Selected_By": (
            "Valid Spiral drawing first; then EDA/ECG task coverage; then Neon/EEG "
            "coverage; then overall coverage; *_eeg.xdf only as a tie-breaker; "
            "sample counts last."
        ),
        "Filename_Is_Current_EEG_XDF": is_current_eeg,
        "Drawing_Detected": drawing_detected,
        "Drawing_Start_XDF_Time": drawing_start,
        "Drawing_End_XDF_Time": drawing_end,
        "Drawing_Window_Duration_sec": round(drawing_window_duration, 3),
        "Drawing_Active_Duration_sec": round(drawing_active_duration, 3),
        "Pen_Present": has_pen,
        "Pen_Samples": pen_samples,
        "Pen_Stream_Name": get_stream_name(pen_stream),
        "Pen_Stream_Type": get_stream_type(pen_stream),
        "Pen_Effective_SRate": round(get_effective_srate(pen_stream), 3),
        "Pen_Duration_sec": round(get_duration_sec(pen_stream), 3),
        "Neon_Gaze_Present": has_neon_gaze,
        "Neon_Gaze_Samples": neon_gaze_samples,
        "Neon_Gaze_Stream_Name": get_stream_name(neon_gaze_stream),
        "Neon_Gaze_Stream_Type": get_stream_type(neon_gaze_stream),
        "Neon_Gaze_Effective_SRate": round(get_effective_srate(neon_gaze_stream), 3),
        "Neon_Gaze_Duration_sec": round(get_duration_sec(neon_gaze_stream), 3),
        "Neon_Gaze_Coverage_pct": round(neon_coverage * 100.0, 2),
        "Any_Neon_Present": any_neon_samples > 0,
        "Any_Neon_Samples": any_neon_samples,
        "Any_Neon_Stream_Name": get_stream_name(any_neon_stream),
        "Any_Neon_Stream_Type": get_stream_type(any_neon_stream),
        "EEG_Present": has_eeg,
        "EEG_Samples": eeg_samples,
        "EEG_Stream_Name": get_stream_name(eeg_stream),
        "EEG_Stream_Type": get_stream_type(eeg_stream),
        "EEG_Effective_SRate": round(get_effective_srate(eeg_stream), 3),
        "EEG_Duration_sec": round(get_duration_sec(eeg_stream), 3),
        "EEG_Coverage_pct": round(eeg_coverage * 100.0, 2),
        "EDA_Present": has_eda,
        "EDA_Samples": eda_samples,
        "EDA_Stream_Name": get_stream_name(eda_stream),
        "EDA_Coverage_pct": round(eda_coverage * 100.0, 2),
        "ECG_Present": has_ecg,
        "ECG_Samples": ecg_samples,
        "ECG_Stream_Name": get_stream_name(ecg_stream),
        "ECG_Coverage_pct": round(ecg_coverage * 100.0, 2),
        "Total_Streams": len(streams),
        "Total_NonEmpty_Streams": sum(get_n_samples(stream) > 0 for stream in streams),
        "Total_Samples_All_Streams": total_samples,
    }


def is_current_eeg_xdf(xdf_fn: Path) -> bool:
    """Return True for the current Lab Recorder *_eeg.xdf filename convention."""
    return xdf_fn.name.endswith("_eeg.xdf")


def find_subject_ids(root: Path) -> list[str]:
    """Find subjects represented by any XDF under the input folder."""
    return sorted(
        {
            lsl.get_subject_id(xdf_fn)
            for xdf_fn in root.rglob("*.xdf")
        }
    )


def find_subject_xdf_files(root: Path, subject_id: str) -> list[Path]:
    """Return all XDF candidates belonging to one participant."""
    return sorted(
        xdf_fn
        for xdf_fn in root.rglob("*.xdf")
        if lsl.get_subject_id(xdf_fn) == subject_id
    )


def load_subject_xdf_candidates(
    root: Path,
    subject_id: str,
    verbose: bool = False,
) -> tuple[pd.DataFrame, dict[Path, list[XdfStream]]]:
    rows: list[dict[str, Any]] = []
    streams_by_path: dict[Path, list[XdfStream]] = {}

    for xdf_fn in find_subject_xdf_files(root, subject_id):
        try:
            streams = get_and_check_xdf(xdf_fn, verbose=False)
            row = summarise_xdf_candidate(xdf_fn, streams)
        except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError) as error:
            logger.warning(
                "Skipping %s because the XDF could not be inspected: %s",
                xdf_fn.name,
                error,
            )
            continue

        rows.append(row)
        streams_by_path[xdf_fn] = streams

        if verbose:
            logger.info(
                (
                    "Candidate subject=%s file=%s drawing=%s "
                    "EDA=%.1f%% ECG=%.1f%% Neon=%.1f%% EEG=%.1f%% label=%s"
                ),
                row["Subject_ID"],
                row["XDF_File"],
                row["Drawing_Detected"],
                row["EDA_Coverage_pct"],
                row["ECG_Coverage_pct"],
                row["Neon_Gaze_Coverage_pct"],
                row["EEG_Coverage_pct"],
                row["Selection_Label"],
            )

    return pd.DataFrame(rows), streams_by_path


def _candidate_sort_key(row: pd.Series) -> tuple:
    return (
        int(bool(row.get("Drawing_Detected", False))),
        min(
            float(row.get("EDA_Coverage_pct", 0.0) or 0.0),
            float(row.get("ECG_Coverage_pct", 0.0) or 0.0),
        ),
        min(
            float(row.get("Neon_Gaze_Coverage_pct", 0.0) or 0.0),
            float(row.get("EEG_Coverage_pct", 0.0) or 0.0),
        ),
        (
            float(row.get("EDA_Coverage_pct", 0.0) or 0.0)
            + float(row.get("ECG_Coverage_pct", 0.0) or 0.0)
            + float(row.get("Neon_Gaze_Coverage_pct", 0.0) or 0.0)
            + float(row.get("EEG_Coverage_pct", 0.0) or 0.0)
        )
        / 4.0,
        int(bool(row.get("Filename_Is_Current_EEG_XDF", False))),
        int(row.get("Pen_Samples", 0) or 0),
        int(row.get("Total_Samples_All_Streams", 0) or 0),
    )


def choose_best_xdfs(candidates_df: pd.DataFrame) -> pd.DataFrame:
    """Select the most complete task-valid XDF for each participant."""

    if candidates_df.empty:
        return candidates_df.copy()

    selected_rows = []

    for subject_id, group in candidates_df.groupby("Subject_ID", sort=True):
        ranked = sorted(
            [row for _, row in group.iterrows()],
            key=_candidate_sort_key,
            reverse=True,
        )

        selected = ranked[0].copy()
        selected_key = _candidate_sort_key(selected)

        ties = [row for row in ranked if _candidate_sort_key(row) == selected_key]
        candidate_files = group["XDF_File"].tolist()

        selected["Selection_Note"] = (
            "Selected from all participant XDFs using drawing validity and temporal "
            "coverage of EDA, ECG, Neon gaze and EEG."
        )
        selected["Candidate_Count"] = len(group)
        selected["Candidate_Files"] = "; ".join(candidate_files)
        selected["Selection_Ambiguous"] = len(ties) > 1
        selected["Subject_Has_Any_EEG_XDF"] = bool(
            group["EEG_Present"].fillna(False).astype(bool).any()
        )
        selected["Selected_XDF_Has_EEG"] = bool(selected.get("EEG_Present", False))

        selected_rows.append(selected)

    selected_df = pd.DataFrame(selected_rows)
    selected_df.insert(0, "Selected_XDF", True)

    return selected_df.reset_index(drop=True)


def add_qc_flags(selected_df: pd.DataFrame) -> pd.DataFrame:
    if selected_df.empty:
        return selected_df.copy()

    out = selected_df.copy()
    missing_items = []
    qc_status = []
    selection_status = []
    selection_reason = []

    for _, row in out.iterrows():
        problems = []

        if not bool(row.get("Drawing_Detected", False)):
            problems.append("NO_VALID_SPIRAL_DRAWING")

        for label, present_col, coverage_col in (
            ("EDA", "EDA_Present", "EDA_Coverage_pct"),
            ("ECG", "ECG_Present", "ECG_Coverage_pct"),
            ("Neon_Gaze", "Neon_Gaze_Present", "Neon_Gaze_Coverage_pct"),
            ("EEG", "EEG_Present", "EEG_Coverage_pct"),
        ):
            present = bool(row.get(present_col, False))
            coverage = float(row.get(coverage_col, 0.0) or 0.0)

            if not present:
                problems.append(f"{label}_MISSING")
            elif coverage < GOOD_COVERAGE_FRACTION * 100.0:
                problems.append(f"{label}_LOW_COVERAGE_{coverage:.1f}%")

        if bool(row.get("Selection_Ambiguous", False)):
            problems.append("MULTIPLE_CANDIDATES_TIED")

        if (
            not bool(row.get("Filename_Is_Current_EEG_XDF", False))
            and bool(row.get("Subject_Has_Any_EEG_XDF", False))
        ):
            problems.append("NON_EEG_FILENAME_SELECTED_OVER_EEG_FILE")

        missing_items.append("; ".join(problems))

        if not bool(row.get("Drawing_Detected", False)):
            selection_status.append("NO_VALID_SPIRAL_FOUND")
        elif problems:
            selection_status.append("AUTO_SELECTED_CHECK")
        else:
            selection_status.append("AUTO_SELECTED_HIGH_CONFIDENCE")

        reason = "; ".join(problems) if problems else "Valid drawing with strong multimodal coverage"
        selection_reason.append(reason)
        qc_status.append("OK" if not problems else "CHECK: " + ", ".join(problems))

    out.insert(1, "Selection_Status", selection_status)
    out.insert(2, "Selection_Reason", selection_reason)
    out.insert(3, "QC_Status", qc_status)
    out.insert(4, "Missing_Items", missing_items)

    priority = [
        "Selected_XDF",
        "Selection_Status",
        "Selection_Reason",
        "QC_Status",
        "Missing_Items",
        "Subject_ID",
        "XDF_File",
        "XDF_Path",
        "Candidate_Count",
        "Candidate_Files",
        "Selection_Ambiguous",
        "Selection_Class",
        "Selection_Label",
        "Selection_Note",
        "Drawing_Detected",
        "Drawing_Window_Duration_sec",
        "Drawing_Active_Duration_sec",
        "EDA_Present",
        "EDA_Coverage_pct",
        "ECG_Present",
        "ECG_Coverage_pct",
        "Neon_Gaze_Present",
        "Neon_Gaze_Coverage_pct",
        "EEG_Present",
        "EEG_Coverage_pct",
        "Filename_Is_Current_EEG_XDF",
        "Subject_Has_Any_EEG_XDF",
        "Selected_XDF_Has_EEG",
        "Pen_Present",
        "Pen_Samples",
        "Neon_Gaze_Samples",
        "EEG_Samples",
        "EDA_Samples",
        "ECG_Samples",
    ]
    remaining = [column for column in out.columns if column not in priority]
    ordered_columns = [column for column in priority if column in out.columns] + remaining
    return out[ordered_columns]
