"""Standalone PySide6 tool: read-only viewer for a vrlab_longwalk_process output folder.

See process_results_common.py -- this file only supplies longwalk's config, plus the
"Process BIDS Folder" callback, which just calls the CLI's own `run_batch` (the same
function `vrlab_longwalk_process`'s `main()` calls) rather than re-implementing it.
"""

from pathlib import Path

from vrlab_toolbox.cli.vrlab_longwalk_process import PHYSIO_GLOB_PATTERN
from vrlab_toolbox.cli.vrlab_longwalk_process import run_batch as _run_longwalk_batch
from vrlab_toolbox.gui.process_results_common import (
    ProcessResultsConfig,
    ProgressCallback,
    run_process_results_app,
)


def _process_bids_folder(
    bids_folder: Path,
    output_folder: Path,
    progress_callback: ProgressCallback | None,
    skip_existing: bool,
) -> list[str]:
    csv_path = _run_longwalk_batch(
        bids_folder,
        output_folder,
        progress_callback=progress_callback,
        skip_existing=skip_existing,
    )
    return [f"Wrote {csv_path.name}"]


LONGWALK_PROCESS_RESULTS_CONFIG = ProcessResultsConfig(
    dataset_name="longwalk",
    window_title="Longwalk Process Results",
    csv_glob="*vrlab_longwalk_process_batch_data_out.csv",
    process_bids_folder=_process_bids_folder,
    bids_physio_glob=PHYSIO_GLOB_PATTERN,
    window_icon_path=Path("assets") / "longwalk_icon.png",
)


def main() -> None:
    run_process_results_app(
        LONGWALK_PROCESS_RESULTS_CONFIG, settings_app_name="LongwalkProcessResults"
    )


if __name__ == "__main__":
    main()
