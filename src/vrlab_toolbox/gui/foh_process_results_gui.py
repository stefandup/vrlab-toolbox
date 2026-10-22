"""Standalone PySide6 tool: read-only viewer for a vrlab_foh_process output folder.

See process_results_common.py -- this file only supplies FOH's config, plus the
"Process BIDS Folder" callback, which just calls the CLI's own `run_batch` (the same
function `vrlab_foh_process`'s `main()` calls) rather than re-implementing it.

Unlike crane_process_results_gui.py/longwalk_process_results_gui.py, there's no
dataset-specific `build_group_dashboard` here yet: FOH's own behavioural pipeline
(`ProcessFohBehaviouralDataStrateyStep` in `foh_behaviour.py`) is still under
construction, so there aren't real output columns yet to build a fixed dashboard
layout from. This window still works as a generic viewer in the meantime --
`process_results_common.py`'s plain "pick any numeric column" Summary Stats tab
covers whatever `foh_pipeline.py` does produce (currently the target hit-latency and
EDA/SCR columns).
"""

from pathlib import Path

from vrlab_toolbox.cli.vrlab_foh_process import PHYSIO_GLOB_PATTERN
from vrlab_toolbox.cli.vrlab_foh_process import run_batch as _run_foh_batch
from vrlab_toolbox.gui.process_results_common import (
    ProcessResultsConfig,
    ProgressCallback,
    run_process_results_app,
)
from vrlab_toolbox.processing.lsl import get_subject_id


def _process_bids_folder(
    bids_folder: Path,
    output_folder: Path,
    progress_callback: ProgressCallback | None,
    skip_existing: bool,
) -> list[str]:
    csv_path = _run_foh_batch(
        bids_folder,
        output_folder,
        progress_callback=progress_callback,
        skip_existing=skip_existing,
    )
    if csv_path is None:
        return ["No subjects were successfully processed."]
    return [f"Wrote {csv_path.name}"]


FOH_PROCESS_RESULTS_CONFIG = ProcessResultsConfig(
    dataset_name="foh",
    window_title="FOH Process Results",
    csv_glob="FOH_process_batch_out.csv",
    process_bids_folder=_process_bids_folder,
    bids_physio_glob=PHYSIO_GLOB_PATTERN,
    bids_subject_id_from_path=get_subject_id,
    window_icon_path=Path("assets") / "FOH_icon.png",
)


def main() -> None:
    run_process_results_app(FOH_PROCESS_RESULTS_CONFIG, settings_app_name="FohProcessResults")


if __name__ == "__main__":
    main()
