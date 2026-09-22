"""Standalone PySide6 tool: human-in-the-loop crosscheck for the FOH BIDS folder.

See docs/bids_crosscheck_plan.md and docs/bids_converter_plan.md. The `*.xdf` recording
pattern is the one glob pattern the plan pins down explicitly (crosscheck does its own
broad `.xdf` scan rather than reusing `from_lsl_data`'s `_eeg.xdf`-only filter).
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pyxdf

from vrlab_toolbox.cli.foh_import_to_bids import FohImportSummary, import_foh_raw_to_bids
from vrlab_toolbox.gui.bids_crosscheck_common import CandidateExtras, run_bids_crosscheck_app
from vrlab_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from vrlab_toolbox.processing.biodata import ACCEPTED_LABEL_PATTERN, CANONICAL_LABEL_SPELLING
from vrlab_toolbox.processing.lsl import (
    extract_single_stream,
    gather_xdf_data_streams,
    get_start_time,
    xdfIOException,
)

logger = logging.getLogger(__name__)

FOH_STREAMS = ("OpenSignals", "VR_markers", "VR_trial_events", "FOH_target")
OPENSIGNALS_STREAM = "OpenSignals"
# The physiology channels the FOH pipeline reads out of the OpenSignals stream (see
# processing/foh_pipeline.py and processing/biodata.py). Presence is checked via
# ACCEPTED_LABEL_PATTERN/CANONICAL_LABEL_SPELLING below, not an exact-name match, since
# BITalino sometimes appends a trailing channel number (e.g. "EDA0", "ECG1").
EXPECTED_PHYSIO_CHANNELS = ("EDA", "ECG")
CHECK = "✓"
CROSS = "✗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
# Same relative-difference threshold pyxdf itself uses to warn about a stream's
# effective vs. nominal sampling rate (see pyxdf.pyxdf._clock_reset).
SRATE_MISMATCH_THRESHOLD = 0.1
INFO_CACHE_FILENAME = "crosscheck_info_cache.json"
# Bumped whenever _parse_candidate_info's output shape or derivation changes, so a cached
# entry that still matches the file's mtime/size (nothing to re-read) but was computed by
# older logic gets reparsed anyway instead of silently serving stale info forever.
INFO_SCHEMA_VERSION = 2

FOH_DATASET_CONFIG = DatasetConfig(
    dataset_name="foh",
    scan_types=(ScanTypeConfig(name="recording", glob_patterns=("*.xdf",)),),
    task_tag_scan_type="recording",
    # Lowercase, matching BIDS's own entity/suffix convention -- "FOH" the study name stays
    # capitalized everywhere else, this is just the filename tag. Tagging now writes real BIDS
    # entities/suffix (see record_task_tag) instead of a bare non-BIDS "_foh" label: a
    # `task-foh` entity (this recording is FOH's task), an `acq-lsl` entity (collected over
    # Lab Streaming Layer -- there may eventually be non-LSL FOH files too, so this isn't
    # redundant), and a real `beh` suffix. "beh" (behavioural data) is the closest fit in
    # BIDS's own suffix vocabulary for this physiology-plus-sometimes-behaviour-over-LSL
    # recording, unlike "foh" itself, which isn't a real BIDS term.
    task_tag_task="foh",
    task_tag_acq="lsl",
    task_tag_suffix="beh",
    # The raw collection folder is literally named "eeg" regardless of what's actually in it.
    # Only takes effect once a recording's confirmed and tagged (see record_task_tag).
    task_tag_folder_name="beh",
)


@dataclass
class FohCandidateInfo:
    streams: dict[str, bool]
    recorded_at: str | None
    duration_minutes: float | None
    opensignals_columns: list[str] | None
    opensignals_channels: dict[str, bool]
    opensignals_nominal_srate: float | None
    opensignals_effective_srate: float | None


def _recording_duration_minutes(streams: list) -> float | None:
    """Total span of the recording, across every stream in the file (not just FOH_STREAMS).

    The xdf file header has no duration field, only a start `datetime` (see
    `get_start_time`) -- so duration has to be derived from timestamps, same as
    `processing/eeg.py` and `cli/mobi_spiral_process_batch.py` already do per-stream.
    Using every stream rather than just OpenSignals/VR_trial_events means this still
    resolves even when neither of those happens to be present.
    """
    starts = []
    ends = []
    for stream in streams:
        time_stamps = stream["time_stamps"]
        if len(time_stamps):
            starts.append(time_stamps[0])
            ends.append(time_stamps[-1])
    if not starts:
        return None
    return (max(ends) - min(starts)) / 60


def _present_physio_channels(columns: list[str]) -> dict[str, bool]:
    """Which of EXPECTED_PHYSIO_CHANNELS appear in `columns`, matched the same way
    `biodata.normalize_data_labels` matches them for the actual pipeline (case-insensitive,
    optional trailing digit) -- so this reports exactly what the pipeline would accept.
    """
    canonical_found = set()
    for column in columns:
        match = ACCEPTED_LABEL_PATTERN.match(column)
        if match is not None:
            canonical_found.add(CANONICAL_LABEL_SPELLING[match.group("base").lower()])
    return {channel: channel in canonical_found for channel in EXPECTED_PHYSIO_CHANNELS}


def _srate_mismatch(info: FohCandidateInfo) -> bool:
    nominal = info.opensignals_nominal_srate
    effective = info.opensignals_effective_srate
    if nominal is None or effective is None or nominal == 0:
        return False
    return abs(nominal - effective) / nominal > SRATE_MISMATCH_THRESHOLD


def _parse_candidate_info(file: Path) -> FohCandidateInfo:
    try:
        streams, header = pyxdf.load_xdf(str(file))
        found = gather_xdf_data_streams(streams, list(FOH_STREAMS))
        stream_presence = {name: name in found for name in FOH_STREAMS}
        duration_minutes = _recording_duration_minutes(streams)
        try:
            recorded_at = get_start_time(header).strftime("%Y-%m-%d %H:%M")
        except (KeyError, IndexError, ValueError):
            recorded_at = None
        opensignals_columns = None
        opensignals_channels = dict.fromkeys(EXPECTED_PHYSIO_CHANNELS, False)
        opensignals_nominal_srate = None
        opensignals_effective_srate = None
        try:
            _, opensignals_stream = extract_single_stream(streams, OPENSIGNALS_STREAM)
        except xdfIOException:
            pass
        else:
            if OPENSIGNALS_STREAM in found:
                opensignals_columns = [
                    column
                    for column in found[OPENSIGNALS_STREAM].columns
                    if column != "time_stamps"
                ]
                opensignals_channels = _present_physio_channels(opensignals_columns)
            opensignals_nominal_srate = float(opensignals_stream["info"]["nominal_srate"][0])
            opensignals_effective_srate = float(opensignals_stream["info"]["effective_srate"])
    except Exception:
        logger.warning("Could not read XDF data from %s", file, exc_info=True)
        stream_presence = dict.fromkeys(FOH_STREAMS, False)
        recorded_at = None
        duration_minutes = None
        opensignals_columns = None
        opensignals_channels = dict.fromkeys(EXPECTED_PHYSIO_CHANNELS, False)
        opensignals_nominal_srate = None
        opensignals_effective_srate = None

    return FohCandidateInfo(
        streams=stream_presence,
        recorded_at=recorded_at,
        duration_minutes=duration_minutes,
        opensignals_columns=opensignals_columns,
        opensignals_channels=opensignals_channels,
        opensignals_nominal_srate=opensignals_nominal_srate,
        opensignals_effective_srate=opensignals_effective_srate,
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


class FohCandidateExtras(CandidateExtras):
    """Advisory FOH recording timestamp + stream-presence indicator; never gates renaming.

    Every parse result is cached on disk (see INFO_CACHE_FILENAME), keyed by the file's
    path relative to the BIDS folder plus its mtime/size, so a fresh launch or re-Browse
    doesn't have to re-parse every "ok" recording's .xdf again -- only files that are new
    or have actually changed. See docs/bids_crosscheck_plan.md#todo-deferred-not-scoped-now.
    """

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
        if scan_type != FOH_DATASET_CONFIG.task_tag_scan_type:
            return None
        info = self._candidate_info(file)
        found_streams = sum(info.streams.values())
        total_streams = len(info.streams)
        complete = found_streams == total_streams
        streams_text = (
            f'<span style="color:{CHECK_COLOR if complete else CROSS_COLOR}">'
            f"Streams: {found_streams}/{total_streams} {CHECK if complete else CROSS}</span>"
        )

        parts = []
        if info.recorded_at is not None:
            parts.append(info.recorded_at)
        if info.duration_minutes is not None:
            parts.append(f"{round(info.duration_minutes)} min")
        parts.append(streams_text)
        return " &nbsp;&nbsp; ".join(parts)

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type != FOH_DATASET_CONFIG.task_tag_scan_type:
            return None
        info = self._candidate_info(file)
        lines = ["Streams found in this recording:"]
        lines.extend(
            f"{CHECK if present else CROSS} {name}" for name, present in info.streams.items()
        )
        if info.streams.get(OPENSIGNALS_STREAM):
            lines.append("")
            lines.append("OpenSignals channels the pipeline needs:")
            lines.extend(
                f"{CHECK if present else CROSS} {label}"
                for label, present in info.opensignals_channels.items()
            )
        return "\n".join(lines)

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type != FOH_DATASET_CONFIG.task_tag_scan_type:
            return None
        info = self._candidate_info(file)
        streams_text = " ".join(
            f'{name}<span style="color:{CHECK_COLOR if present else CROSS_COLOR}">'
            f"{CHECK if present else CROSS}</span>"
            for name, present in info.streams.items()
        )
        streams_line = f"<b>Streams</b> &nbsp; {streams_text}"
        if info.opensignals_columns is None:
            return f"{streams_line}<br>{OPENSIGNALS_STREAM} not found in this recording"

        columns_text = ", ".join(info.opensignals_columns)
        channels_text = " ".join(
            f'{label}<span style="color:{CHECK_COLOR if present else CROSS_COLOR}">'
            f"{CHECK if present else CROSS}</span>"
            for label, present in info.opensignals_channels.items()
        )
        nominal = info.opensignals_nominal_srate
        effective = info.opensignals_effective_srate
        if nominal is not None and effective is not None:
            rate_text = f"{effective:.4f} Hz effective vs {nominal:.4f} Hz specified"
            if _srate_mismatch(info):
                rate_text = f'<span style="color:{CROSS_COLOR}">{rate_text}</span>'
        else:
            rate_text = "sampling rate unavailable"

        return (
            f"{streams_line}<br>"
            f"<b>{OPENSIGNALS_STREAM}</b> &nbsp; columns: {columns_text} "
            f"&nbsp;&nbsp; {channels_text} &nbsp;&nbsp; {rate_text}"
        )

    def task_tag_available(self, scan_type: str) -> bool:
        return scan_type == FOH_DATASET_CONFIG.task_tag_scan_type

    def refreshable(self, scan_type: str) -> bool:
        return scan_type == FOH_DATASET_CONFIG.task_tag_scan_type

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force a reparse for one candidate. Caller batches the disk write via `flush()`
        (e.g. once after refreshing every subject in a bulk selection, not once per file)."""
        if scan_type != FOH_DATASET_CONFIG.task_tag_scan_type:
            return
        self._candidate_info(file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        if scan_type != FOH_DATASET_CONFIG.task_tag_scan_type:
            return False
        info = self._candidate_info(file)
        if _srate_mismatch(info):
            return True
        if info.streams.get(OPENSIGNALS_STREAM) and not all(info.opensignals_channels.values()):
            return True
        return False

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _candidate_info(self, file: Path, force: bool = False) -> FohCandidateInfo:
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
                    return FohCandidateInfo(**cached["info"])
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


class _ListLogHandler(logging.Handler):
    """Captures formatted log records into a list instead of printing them -- used to relay
    `import_foh_raw_to_bids`'s `logger.info` calls into the crosscheck GUI's status dialog,
    since that function reports progress via the standard logger rather than a GUI-specific
    callback (see its own docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {self.format(record)}")


def _format_import_summary(summary: FohImportSummary) -> str:
    if not summary.new_subject_ids:
        return "No new subjects found -- everything in the raw folder is already imported."
    return (
        "Added "
        + str(len(summary.new_subject_ids))
        + " new subject(s):\n\n"
        + "\n".join(f"sub-{subject_id}" for subject_id in summary.new_subject_ids)
    )


def _run_foh_import(raw_folder: Path, bids_folder: Path, _override_file: Path | None) -> list[str]:
    """The FOH-specific `raw_converter` callback `BidsCrosscheckWindow` calls when the
    "Refresh BIDS" button is clicked. FOH has no override-file concept (unlike crane's
    debrief-export picker), so the third argument is always None and ignored -- kept only
    to match the shared `raw_converter` call signature.
    """
    handler = _ListLogHandler()
    importer_logger = logging.getLogger("vrlab_toolbox.cli.foh_import_to_bids")
    importer_logger.addHandler(handler)
    try:
        summary = import_foh_raw_to_bids(raw_folder, bids_folder)
    finally:
        importer_logger.removeHandler(handler)

    return [*handler.lines, "", _format_import_summary(summary)]


def main() -> None:
    run_bids_crosscheck_app(
        FOH_DATASET_CONFIG,
        "FOH BIDS Crosscheck",
        FohCandidateExtras(),
        settings_app_name="FohBidsCrosscheck",
        raw_converter=_run_foh_import,
        window_icon_path=Path("assets") / "FOH_icon.png",
    )


if __name__ == "__main__":
    main()
