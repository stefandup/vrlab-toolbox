"""Standalone PySide6 tool: human-in-the-loop crosscheck for Spiral XDF recordings."""

import json
import logging
import os
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path

import pyxdf

from vrlab_toolbox.gui.bids_crosscheck_common import CandidateExtras, run_bids_crosscheck_app
from vrlab_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from vrlab_toolbox.processing.graphomotor_xdf import (
    XdfStream,
    find_largest_stream,
    get_effective_srate,
    get_nominal_srate,
    get_pen_drawing_window,
    get_pen_movement_intervals,
    get_stream_coverage_fraction,
    is_continuous_neon_gaze_stream,
    is_current_eeg_xdf,
    is_ecg_stream,
    is_eda_stream,
    is_eeg_stream,
    is_pen_stream,
)
from vrlab_toolbox.processing.spiral import (
    EXPECTED_SPIRAL_COUNT,
    detect_spiral_start_times,
    estimate_spiral_centre,
    estimate_spiral_centre_radius,
    get_spiral_attempt_features,
    get_spiral_attempt_intervals,
    select_completed_spiral_attempts,
)

logger = logging.getLogger(__name__)

CHECK = "✓"
CROSS = "✗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
WARNING_COLOR = "#f39c12"
GOOD_COVERAGE_PCT = 80.0
INFO_CACHE_FILENAME = "spiral_crosscheck_info_cache.json"
INFO_SCHEMA_VERSION = 1

SPIRAL_DATASET_CONFIG = DatasetConfig(
    dataset_name="spiral",
    scan_types=(ScanTypeConfig(name="recording", glob_patterns=("*.xdf",)),),
)


@dataclass
class SpiralCandidateInfo:
    drawing_detected: bool
    detected_attempts: int
    selected_spirals: int
    drawing_active_duration_sec: float
    eda_present: bool
    eda_coverage_pct: float
    ecg_present: bool
    ecg_coverage_pct: float
    neon_present: bool
    neon_coverage_pct: float
    eeg_present: bool
    eeg_coverage_pct: float
    eeg_nominal_srate: float | None
    eeg_effective_srate: float | None
    filename_is_current_eeg_xdf: bool
    parse_error: bool


def rank_spiral_candidate(info: SpiralCandidateInfo) -> tuple:
    coverage = (
        info.eda_coverage_pct,
        info.ecg_coverage_pct,
        info.neon_coverage_pct,
        info.eeg_coverage_pct,
    )
    return (
        int(info.selected_spirals == EXPECTED_SPIRAL_COUNT),
        info.selected_spirals,
        round(min(info.eda_coverage_pct, info.ecg_coverage_pct), 1),
        round(min(info.neon_coverage_pct, info.eeg_coverage_pct), 1),
        round(sum(coverage) / len(coverage), 1),
        int(info.filename_is_current_eeg_xdf),
    )


def _spiral_attempt_counts(pen_stream: XdfStream | None) -> tuple[int, int]:
    movement_intervals, time_stamps, x, y = get_pen_movement_intervals(pen_stream)

    if not movement_intervals or len(time_stamps) == 0 or len(x) == 0 or len(y) == 0:
        return 0, 0

    centre = estimate_spiral_centre(time_stamps, x, y)
    centre_radius = estimate_spiral_centre_radius(
        time_stamps,
        x,
        y,
        centre=centre,
    )
    start_times = detect_spiral_start_times(
        time_stamps,
        x,
        y,
        centre=centre,
        centre_radius=centre_radius,
    )
    attempt_intervals = get_spiral_attempt_intervals(time_stamps, start_times)
    features = get_spiral_attempt_features(
        time_stamps,
        x,
        y,
        centre=centre,
        attempt_intervals=attempt_intervals,
    )
    selected = select_completed_spiral_attempts(features)
    return len(features), len(selected)


def _empty_candidate_info(file: Path) -> SpiralCandidateInfo:
    return SpiralCandidateInfo(
        drawing_detected=False,
        detected_attempts=0,
        selected_spirals=0,
        drawing_active_duration_sec=0.0,
        eda_present=False,
        eda_coverage_pct=0.0,
        ecg_present=False,
        ecg_coverage_pct=0.0,
        neon_present=False,
        neon_coverage_pct=0.0,
        eeg_present=False,
        eeg_coverage_pct=0.0,
        eeg_nominal_srate=None,
        eeg_effective_srate=None,
        filename_is_current_eeg_xdf=is_current_eeg_xdf(file),
        parse_error=True,
    )


def _parse_candidate_info(file: Path) -> SpiralCandidateInfo:
    try:
        streams, _ = pyxdf.load_xdf(str(file))
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, IndexError):
        logger.warning("Could not read Spiral XDF data from %s", file, exc_info=True)
        return _empty_candidate_info(file)

    pen_stream = find_largest_stream(streams, is_pen_stream)
    eda_stream = find_largest_stream(streams, is_eda_stream)
    ecg_stream = find_largest_stream(streams, is_ecg_stream)
    neon_stream = find_largest_stream(streams, is_continuous_neon_gaze_stream)
    eeg_stream = find_largest_stream(streams, is_eeg_stream)

    drawing_detected, drawing_start, drawing_end, drawing_active_duration = get_pen_drawing_window(
        pen_stream
    )

    try:
        detected_attempts, selected_spirals = _spiral_attempt_counts(pen_stream)
    except (ValueError, TypeError, KeyError, IndexError):
        logger.warning("Could not inspect Spiral attempts in %s", file, exc_info=True)
        detected_attempts = 0
        selected_spirals = 0

    eda_coverage = get_stream_coverage_fraction(eda_stream, drawing_start, drawing_end) * 100.0
    ecg_coverage = get_stream_coverage_fraction(ecg_stream, drawing_start, drawing_end) * 100.0
    neon_coverage = get_stream_coverage_fraction(neon_stream, drawing_start, drawing_end) * 100.0
    eeg_coverage = get_stream_coverage_fraction(eeg_stream, drawing_start, drawing_end) * 100.0

    eeg_nominal_srate = get_nominal_srate(eeg_stream) if eeg_stream is not None else None
    eeg_effective_srate = get_effective_srate(eeg_stream) if eeg_stream is not None else None

    return SpiralCandidateInfo(
        drawing_detected=drawing_detected,
        detected_attempts=detected_attempts,
        selected_spirals=selected_spirals,
        drawing_active_duration_sec=float(drawing_active_duration),
        eda_present=eda_stream is not None,
        eda_coverage_pct=eda_coverage,
        ecg_present=ecg_stream is not None,
        ecg_coverage_pct=ecg_coverage,
        neon_present=neon_stream is not None,
        neon_coverage_pct=neon_coverage,
        eeg_present=eeg_stream is not None,
        eeg_coverage_pct=eeg_coverage,
        eeg_nominal_srate=eeg_nominal_srate,
        eeg_effective_srate=eeg_effective_srate,
        filename_is_current_eeg_xdf=is_current_eeg_xdf(file),
        parse_error=False,
    )


def _info_cache_path(bids_folder: Path) -> Path:
    return bids_folder / INFO_CACHE_FILENAME


def _load_info_cache(bids_folder: Path) -> dict[str, dict]:
    path = _info_cache_path(bids_folder)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read info cache at %s -- starting fresh", path)
        return {}


def _save_info_cache(bids_folder: Path, cache: dict[str, dict]) -> None:
    path = _info_cache_path(bids_folder)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        json.dump(cache, tmp_file, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


class SpiralCandidateExtras(CandidateExtras):
    def __init__(self) -> None:
        self._bids_folder: Path | None = None
        self._disk_cache: dict[str, dict] = {}
        self._dirty = False

    def on_bids_folder_changed(self, bids_folder: Path) -> None:
        self._bids_folder = bids_folder
        self._disk_cache = _load_info_cache(bids_folder)
        self._dirty = False

    def bidsignore_patterns(self) -> tuple[str, ...]:
        return (INFO_CACHE_FILENAME,)

    def flush(self) -> None:
        if self._dirty and self._bids_folder is not None:
            _save_info_cache(self._bids_folder, self._disk_cache)
        self._dirty = False

    def describe(self, scan_type: str, file: Path) -> str | None:
        if scan_type != "recording":
            return None

        info = self._candidate_info(file)
        spiral_ok = info.selected_spirals == EXPECTED_SPIRAL_COUNT
        spiral_color = CHECK_COLOR if spiral_ok else CROSS_COLOR
        recommendation = self._recommendation_state(file)

        parts = [
            (
                f'<span style="color:{spiral_color}">'
                f"Spirals: {info.selected_spirals}/{EXPECTED_SPIRAL_COUNT} "
                f"{CHECK if spiral_ok else CROSS}</span>"
            ),
            f"attempts: {info.detected_attempts}",
            f"EEG: {info.eeg_coverage_pct:.0f}%",
            f"EDA: {info.eda_coverage_pct:.0f}%",
            f"ECG: {info.ecg_coverage_pct:.0f}%",
            f"Neon: {info.neon_coverage_pct:.0f}%",
        ]

        if recommendation == "recommended":
            parts.append(f'<span style="color:{CHECK_COLOR}"><b>Recommended</b></span>')
        elif recommendation == "tie":
            parts.append(f'<span style="color:{WARNING_COLOR}"><b>Top-ranked tie</b></span>')

        return " &nbsp;&nbsp; ".join(parts)

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type != "recording":
            return None

        info = self._candidate_info(file)
        current_text = "yes" if info.filename_is_current_eeg_xdf else "no"
        return (
            f"Detected attempts: {info.detected_attempts}\n"
            f"Selected spirals: {info.selected_spirals}/{EXPECTED_SPIRAL_COUNT}\n"
            f"EDA coverage: {info.eda_coverage_pct:.1f}%\n"
            f"ECG coverage: {info.ecg_coverage_pct:.1f}%\n"
            f"Neon coverage: {info.neon_coverage_pct:.1f}%\n"
            f"EEG coverage: {info.eeg_coverage_pct:.1f}%\n"
            f"Current *_eeg.xdf filename: {current_text}\n\n"
            "Recommendation priority: 16 selected spirals first, then EDA/ECG coverage, "
            "then Neon/EEG coverage, then overall coverage. The current *_eeg.xdf name is "
            "only a final tie-breaker. The recommendation is advisory; pick the file manually."
        )

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type != "recording":
            return None

        info = self._candidate_info(file)
        filename = escape(file.name)
        recommendation = self._recommendation_state(file)

        if recommendation == "recommended":
            recommendation_text = (
                f'<span style="color:{CHECK_COLOR}"><b>Recommended candidate</b></span>'
            )
        elif recommendation == "tie":
            recommendation_text = (
                f'<span style="color:{WARNING_COLOR}"><b>Top-ranked tie — inspect manually</b>'
                "</span>"
            )
        else:
            recommendation_text = "Not the top-ranked candidate"

        eeg_rate = "unavailable"
        if info.eeg_nominal_srate is not None and info.eeg_effective_srate is not None:
            eeg_rate = (
                f"{info.eeg_effective_srate:.2f} Hz effective vs "
                f"{info.eeg_nominal_srate:.2f} Hz specified"
            )

        return (
            f"<b>{filename}</b><br>"
            f"{recommendation_text}<br>"
            f"<b>Spiral structure</b> &nbsp; attempts: {info.detected_attempts} &nbsp; "
            f"selected: {info.selected_spirals}/{EXPECTED_SPIRAL_COUNT} &nbsp; "
            f"active drawing: {info.drawing_active_duration_sec:.1f} s<br>"
            f"<b>Coverage</b> &nbsp; EDA {info.eda_coverage_pct:.1f}% &nbsp; "
            f"ECG {info.ecg_coverage_pct:.1f}% &nbsp; Neon {info.neon_coverage_pct:.1f}% "
            f"&nbsp; EEG {info.eeg_coverage_pct:.1f}%<br>"
            f"<b>EEG sampling</b> &nbsp; {eeg_rate}<br>"
            "<b>Selection rule</b> &nbsp; task structure and multimodal coverage outrank the "
            "filename; *_eeg.xdf is only used when candidates are otherwise tied."
        )

    def refreshable(self, scan_type: str) -> bool:
        return scan_type == "recording"

    def refresh(self, scan_type: str, file: Path) -> None:
        if scan_type == "recording":
            self._candidate_info(file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        if scan_type != "recording":
            return False

        info = self._candidate_info(file)
        if info.parse_error or info.selected_spirals != EXPECTED_SPIRAL_COUNT:
            return True

        coverage = (
            info.eda_coverage_pct,
            info.ecg_coverage_pct,
            info.neon_coverage_pct,
            info.eeg_coverage_pct,
        )
        if any(value < GOOD_COVERAGE_PCT for value in coverage):
            return True

        return self._recommendation_state(file) == "tie"

    def _subject_folder(self, file: Path) -> Path:
        for parent in (file.parent, *file.parents):
            if parent.name.startswith("sub-"):
                return parent
        return file.parent

    def _subject_candidates(self, file: Path) -> list[Path]:
        subject_folder = self._subject_folder(file)
        return sorted(path for path in subject_folder.rglob("*.xdf") if path.is_file())

    def _recommendation_state(self, file: Path) -> str:
        candidates = self._subject_candidates(file)
        if not candidates:
            return "other"

        ranked = [
            (candidate, rank_spiral_candidate(self._candidate_info(candidate)))
            for candidate in candidates
        ]
        best_rank = max(rank for _, rank in ranked)
        best_files = [candidate for candidate, rank in ranked if rank == best_rank]

        if file not in best_files:
            return "other"
        if len(best_files) > 1:
            return "tie"
        return "recommended"

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _candidate_info(self, file: Path, force: bool = False) -> SpiralCandidateInfo:
        key = self._cache_key(file)
        stat = file.stat()
        cached = self._disk_cache.get(key)

        if not force and cached is not None:
            if (
                cached.get("mtime") == stat.st_mtime
                and cached.get("size") == stat.st_size
                and cached.get("info_version") == INFO_SCHEMA_VERSION
            ):
                try:
                    return SpiralCandidateInfo(**cached["info"])
                except (TypeError, KeyError):
                    logger.warning("Stale info-cache entry for %s -- reparsing", file)

        info = _parse_candidate_info(file)
        self._disk_cache[key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "info_version": INFO_SCHEMA_VERSION,
            "info": asdict(info),
        }
        self._dirty = True
        return info


def main() -> None:
    run_bids_crosscheck_app(
        SPIRAL_DATASET_CONFIG,
        "Spiral BIDS Crosscheck",
        SpiralCandidateExtras(),
        settings_app_name="SpiralBidsCrosscheck",
    )


if __name__ == "__main__":
    main()
