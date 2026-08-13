"""Standalone PySide6 tool: human-in-the-loop crosscheck for the FOH BIDS folder.

See docs/bids_crosscheck_plan.md. The `*.xdf` recording pattern is the one glob
pattern the plan pins down explicitly (crosscheck does its own broad `.xdf` scan
rather than reusing `from_lsl_data`'s `_eeg.xdf`-only filter).
"""

import logging
from pathlib import Path

import pyxdf

from mooi_toolbox.gui.bids_crosscheck_common import CandidateExtras, run_bids_crosscheck_app
from mooi_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from mooi_toolbox.processing.lsl import gather_xdf_data_streams

logger = logging.getLogger(__name__)

FOH_STREAMS = ("OpenSignals", "VR_markers", "VR_trial_events", "FOH_target")
CHECK = "✓"
CROSS = "✗"

FOH_DATASET_CONFIG = DatasetConfig(
    dataset_name="foh",
    scan_types=(ScanTypeConfig(name="recording", glob_patterns=("*.xdf",)),),
    task_correction_scan_type="recording",
    task_correction_label="FOH",
)


class FohCandidateExtras(CandidateExtras):
    """Advisory FOH stream-presence indicator; never gates the rename action."""

    def __init__(self) -> None:
        self._stream_cache: dict[Path, dict[str, bool]] = {}

    def describe(self, scan_type: str, file: Path) -> str | None:
        if scan_type != FOH_DATASET_CONFIG.task_correction_scan_type:
            return None
        presence = self._stream_presence(file)
        return " ".join(
            f"{name}{CHECK if present else CROSS}" for name, present in presence.items()
        )

    def task_correction_available(self, scan_type: str) -> bool:
        return scan_type == FOH_DATASET_CONFIG.task_correction_scan_type

    def _stream_presence(self, file: Path) -> dict[str, bool]:
        if file not in self._stream_cache:
            try:
                streams, _ = pyxdf.load_xdf(str(file))
                found = gather_xdf_data_streams(streams, list(FOH_STREAMS))
                self._stream_cache[file] = {name: name in found for name in FOH_STREAMS}
            except Exception:
                logger.warning("Could not read XDF streams from %s", file, exc_info=True)
                self._stream_cache[file] = dict.fromkeys(FOH_STREAMS, False)
        return self._stream_cache[file]


def main() -> None:
    run_bids_crosscheck_app(FOH_DATASET_CONFIG, "FOH BIDS Crosscheck", FohCandidateExtras())


if __name__ == "__main__":
    main()
