"""CLI: copy-only converter from longwalkV3's raw flat data folder into a BIDS-shaped output
folder.

Thin wrapper around `processing/longwalk3_bids.py` -- see that module's docstring for the real
conversion logic and output-layout rationale.
"""

from pathlib import Path

import click

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.longwalk3_bids import (
    convert_longwalkv3_to_bids,
    print_longwalkv3_conversion_summary,
)

EXAMPLES_EPILOG = """
Examples:

\\b
  Convert a raw longwalkV3 data folder into a BIDS-shaped folder:
  longwalk3_convert_to_bids C:\\raw\\longwalkv3_local C:\\bids\\longwalkv3_bids
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: Path, output_folder: Path, verbose: bool) -> None:
    """Copy-only converter: raw longwalkV3 data folder -> BIDS-shaped output folder.

    Incremental: subjects that already have a sub-XXX/ folder under output_folder are
    skipped entirely (not re-copied, not touched) -- safe to re-run against a source folder
    that's gained new subjects since the last run.
    """
    summary = convert_longwalkv3_to_bids(input_folder, output_folder)
    print_longwalkv3_conversion_summary(summary)


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
