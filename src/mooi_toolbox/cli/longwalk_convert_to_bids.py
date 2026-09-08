"""CLI: copy-only converter from longwalk's raw flat data folder into a BIDS-shaped output
folder that `gui/longwalk_bids_crosscheck_gui.py` can point at.

Thin wrapper around `processing/longwalk_bids.py` -- see that module's docstring for the real
conversion logic and output-layout rationale, and docs/bids_converter_plan.md for history.
"""

from pathlib import Path

import click

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing.longwalk_bids import (
    convert_longwalk_to_bids,
    print_longwalk_conversion_summary,
)

EXAMPLES_EPILOG = """
Examples:

\\b
  Convert a raw longwalk data folder into a BIDS-shaped folder the crosscheck tool can point at:
  longwalk_convert_to_bids C:\\raw\\MscFiles_longwalk_local C:\\bids\\MscFiles_longwalk_bids
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="mooi-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--debrief-export",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Override the shared REDCAP group export auto-detection -- use when there's more "
    "than one file matching GROUP_REDCAP_GLOB.",
)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(
    input_folder: Path, output_folder: Path, debrief_export: Path | None, verbose: bool
) -> None:
    """Copy-only converter: raw longwalk data folder -> BIDS-shaped output folder.

    Incremental: subjects that already have a sub-XXX/ folder under output_folder are
    skipped entirely (not re-copied, not touched) -- safe to re-run against a source folder
    that's gained new subjects since the last run.
    """
    summary = convert_longwalk_to_bids(input_folder, output_folder, debrief_export)
    print_longwalk_conversion_summary(summary)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
