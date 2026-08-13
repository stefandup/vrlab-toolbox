"""Standalone PySide6 tool: human-in-the-loop crosscheck for the FOH BIDS folder.

See docs/bids_crosscheck_plan.md. The `*.xdf` recording pattern is the one glob
pattern the plan pins down explicitly (crosscheck does its own broad `.xdf` scan
rather than reusing `from_lsl_data`'s `_eeg.xdf`-only filter).
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import pyxdf

from mooi_toolbox.gui.bids_crosscheck_common import CandidateExtras, run_bids_crosscheck_app
from mooi_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from mooi_toolbox.processing.lsl import (
    extract_single_stream,
    gather_xdf_data_streams,
    get_start_time,
    xdfIOException,
)

logger = logging.getLogger(__name__)

FOH_STREAMS = ("OpenSignals", "VR_markers", "VR_trial_events", "FOH_target")
OPENSIGNALS_STREAM = "OpenSignals"
CHECK = "✓"
CROSS = "✗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
# Same relative-difference threshold pyxdf itself uses to warn about a stream's
# effective vs. nominal sampling rate (see pyxdf.pyxdf._clock_reset).
SRATE_MISMATCH_THRESHOLD = 0.1

FOH_DATASET_CONFIG = DatasetConfig(
    dataset_name="foh",
    scan_types=(ScanTypeConfig(name="recording", glob_patterns=("*.xdf",)),),
    task_correction_scan_type="recording",
    task_correction_label="FOH",
)


@dataclass
class FohCandidateInfo:
    streams: dict[str, bool]
    recorded_at: str | None
    duration_minutes: float | None
    opensignals_columns: list[str] | None
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


class FohCandidateExtras(CandidateExtras):
    """Advisory FOH recording timestamp + stream-presence indicator; never gates renaming."""

    def __init__(self) -> None:
        self._info_cache: dict[Path, FohCandidateInfo] = {}

    def describe(self, scan_type: str, file: Path) -> str | None:
        if scan_type != FOH_DATASET_CONFIG.task_correction_scan_type:
            return None
        info = self._candidate_info(file)
        stream_html = " ".join(
            f'{name}<span style="color:{CHECK_COLOR if present else CROSS_COLOR}">'
            f"{CHECK if present else CROSS}</span>"
            for name, present in info.streams.items()
        )
        prefix_parts = []
        if info.recorded_at is not None:
            prefix_parts.append(info.recorded_at)
        if info.duration_minutes is not None:
            prefix_parts.append(f"Total Time: {info.duration_minutes:.1f} min")
        if not prefix_parts:
            return stream_html
        return f"{' &nbsp;'.join(prefix_parts)} &nbsp;&nbsp; {stream_html}"

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type != FOH_DATASET_CONFIG.task_correction_scan_type:
            return None
        info = self._candidate_info(file)
        if info.opensignals_columns is None:
            return f"<b>{OPENSIGNALS_STREAM}</b> &nbsp; not found in this recording"

        columns_text = ", ".join(info.opensignals_columns)
        nominal = info.opensignals_nominal_srate
        effective = info.opensignals_effective_srate
        if nominal is not None and effective is not None:
            rate_text = f"{effective:.4f} Hz effective vs {nominal:.4f} Hz specified"
            if nominal > 0 and abs(nominal - effective) / nominal > SRATE_MISMATCH_THRESHOLD:
                rate_text = f'<span style="color:{CROSS_COLOR}">{rate_text}</span>'
        else:
            rate_text = "sampling rate unavailable"

        return (
            f"<b>{OPENSIGNALS_STREAM}</b> &nbsp; columns: {columns_text} "
            f"&nbsp;&nbsp; {rate_text}"
        )

    def task_correction_available(self, scan_type: str) -> bool:
        return scan_type == FOH_DATASET_CONFIG.task_correction_scan_type

    def _candidate_info(self, file: Path) -> FohCandidateInfo:
        if file not in self._info_cache:
            try:
                streams, header = pyxdf.load_xdf(str(file))
                found = gather_xdf_data_streams(streams, list(FOH_STREAMS))
                stream_presence = {name: name in found for name in FOH_STREAMS}
                duration_minutes = _recording_duration_minutes(streams)
                try:
                    recorded_at = get_start_time(header).strftime("%Y-%m-%d %H:%M:%S")
                except (KeyError, IndexError, ValueError):
                    recorded_at = None
                opensignals_columns = None
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
                    opensignals_nominal_srate = float(
                        opensignals_stream["info"]["nominal_srate"][0]
                    )
                    opensignals_effective_srate = float(
                        opensignals_stream["info"]["effective_srate"]
                    )
            except Exception:
                logger.warning("Could not read XDF data from %s", file, exc_info=True)
                stream_presence = dict.fromkeys(FOH_STREAMS, False)
                recorded_at = None
                duration_minutes = None
                opensignals_columns = None
                opensignals_nominal_srate = None
                opensignals_effective_srate = None
            self._info_cache[file] = FohCandidateInfo(
                streams=stream_presence,
                recorded_at=recorded_at,
                duration_minutes=duration_minutes,
                opensignals_columns=opensignals_columns,
                opensignals_nominal_srate=opensignals_nominal_srate,
                opensignals_effective_srate=opensignals_effective_srate,
            )
        return self._info_cache[file]


def main() -> None:
    run_bids_crosscheck_app(
        FOH_DATASET_CONFIG,
        "FOH BIDS Crosscheck",
        FohCandidateExtras(),
        settings_app_name="FohBidsCrosscheck",
    )


if __name__ == "__main__":
    main()
