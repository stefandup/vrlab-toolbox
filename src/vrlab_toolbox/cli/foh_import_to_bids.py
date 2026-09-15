"""CLI: copy-only importer from FOH's raw recording folder into the BIDS folder
`gui/foh_bids_crosscheck_gui.py` points at.

See docs/bids_converter_plan.md. Never touches `raw_folder` -- only ever copies into
`bids_folder`. Unlike `cli/crane_convert_to_bids.py`, there's no reshaping or renaming to
do: FOH's recording software already writes each subject's `.xdf` files straight into a
real `sub-XXX/ses-.../eeg/` BIDS layout at the point of recording (filenames like
`sub-00024_ses-S001_task-Default_run-001_eeg.xdf`, duplicates/re-recordings suffixed
`_old1`, `_old2`, ...). So importing is just: find `sub-XXX/` folders in `raw_folder` not
already in `bids_folder`, and copy each one across whole, untouched -- the crosscheck
tool's own duplicate handling deals with the `_oldN` files exactly like any other
candidate, same as it already does today when pointed directly at a raw folder.

Incremental by subject, same contract as crane's converter: a `sub-XXX/` already present
in `bids_folder` (converted by an earlier run, possibly since crosschecked/corrected by
hand) is left completely alone and skipped -- re-running against a raw folder that's
since gained new subjects only ever adds those.
"""

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.bids_crosscheck import (
    SUBJECT_FOLDER_PREFIX,
    existing_subject_ids,
    iter_subject_folders,
)

logger = logging.getLogger(__name__)

EXAMPLES_EPILOG = """
Examples:

\\b
  Copy new subjects from a raw FOH recording folder into the BIDS folder the crosscheck
  tool points at:
  foh_import_to_bids C:\\raw\\FOH_local C:\\bids\\FOH_bids
"""


@dataclass
class FohImportSummary:
    """Everything a caller (the CLI's `main()` below, or the crosscheck GUI's "Refresh
    BIDS" button) needs to report what an `import_foh_raw_to_bids()` call actually did."""

    new_subject_ids: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)


def import_foh_raw_to_bids(raw_folder: Path, bids_folder: Path) -> FohImportSummary:
    """Core, UI-agnostic import logic -- see module docstring for why this is a plain copy
    rather than a real conversion. Progress/problems are reported via the standard
    `logger`, not print/rich, so both the CLI below and the crosscheck GUI's "Refresh
    BIDS" button can drive this and display the result their own way.
    """
    bids_folder.mkdir(parents=True, exist_ok=True)
    already_present = existing_subject_ids(bids_folder)

    new_subject_ids = []
    skipped_ids = []
    for subject_id, subject_folder in iter_subject_folders(raw_folder):
        if subject_id in already_present:
            skipped_ids.append(subject_id)
            continue
        destination = bids_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}"
        shutil.copytree(subject_folder, destination)
        new_subject_ids.append(subject_id)

    if skipped_ids:
        logger.info(
            "Skipped %d subject(s) already present in %s: %s",
            len(skipped_ids),
            bids_folder,
            ", ".join(sorted(skipped_ids)),
        )
    logger.info(
        "Copied %d new subject folder(s) from %s to %s.",
        len(new_subject_ids),
        raw_folder,
        bids_folder,
    )

    return FohImportSummary(new_subject_ids=sorted(new_subject_ids), already_present=skipped_ids)


def print_import_summary(summary: FohImportSummary) -> None:
    """Rich console/table rendering of a `FohImportSummary` -- the CLI's own output format,
    factored out so `main()` stays a thin wrapper around `import_foh_raw_to_bids()`."""
    console = Console()
    if not summary.new_subject_ids:
        console.print("No new subjects found -- everything in the raw folder is already imported.")
        return

    table = Table(title="FOH raw -> BIDS import")
    table.add_column("Subject ID")
    for subject_id in summary.new_subject_ids:
        table.add_row(subject_id)
    console.print(table)


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "raw_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("bids_folder", type=click.Path(path_type=Path), required=True)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(raw_folder: Path, bids_folder: Path, verbose: bool) -> None:
    """Copy-only importer: raw FOH recording folder -> BIDS folder.

    Incremental: subjects that already have a sub-XXX/ folder under bids_folder are
    skipped entirely (not re-copied, not touched) -- safe to re-run against a raw folder
    that's gained new subjects since the last run.
    """
    summary = import_foh_raw_to_bids(raw_folder, bids_folder)
    print_import_summary(summary)


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
