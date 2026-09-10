from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing.longwalk_bids import (
    convert_longwalk_to_bids,
    print_longwalk_conversion_summary,
)
from mooi_toolbox.processing.longwalk_dummy_data import generate_dummy_longwalk_dataset

EXAMPLES_EPILOG = """
Examples:

\b
  5 clean participants, reproducible:
  longwalk_generate_sample_data longwalk_examples --seed 42

\b
  Generate straight into a BIDS-shaped folder in the same call, via
  longwalk_bids.convert_longwalk_to_bids -- output_folder still ends up holding the plain raw
  {subject}_{date}.mat files either way, this just also converts them into --bids-folder for you:
  longwalk_generate_sample_data longwalk_examples --seed 42 \\
    --bids-folder longwalk_examples/longwalk_bids_dummy
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="mooi-toolbox")
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--n-subjects", default=5, show_default=True, help="Number of dummy participants to generate"
)
@click.option("--seed", type=int, default=None, help="Seed for reproducible generation")
@click.option(
    "--bids-folder",
    type=click.Path(path_type=Path),
    default=None,
    help="If given, also runs the freshly-generated raw data in output_folder through "
    "longwalk_convert_to_bids into this BIDS folder -- generate and convert in one call instead "
    "of two. output_folder still ends up holding the plain raw {subject}_{date}.mat files either "
    "way.",
)
def main(
    output_folder: Path,
    n_subjects: int,
    seed: int | None,
    bids_folder: Path | None,
) -> None:
    """Generate synthetic longwalk participant physiology data from scratch (no template files
    needed -- unlike crane_generate_sample_data, longwalk's raw behaviour is a fixed 11-marker
    schedule with no per-subject file of its own, see longwalk_behaviour.py).

    Each participant is a synthetic Biopac .mat file with a Trigger channel carrying 12 evenly
    spaced pulses (11 equal-length green-marker/end-marker intervals) and an EDA channel from
    neurokit2.eda_simulate().
    """

    output_folder.mkdir(parents=True, exist_ok=True)

    with Progress() as progress:
        task = progress.add_task("Generating dummy longwalk data...", total=None)
        results = generate_dummy_longwalk_dataset(output_folder, n_subjects, seed)
        progress.update(task, total=1, completed=1)

    table = Table(title="Generated longwalk dummy data")
    table.add_column("Subject ID")
    table.add_column("Physiology file")

    for result in results:
        table.add_row(result.subject_id, result.mat_path.name)

    Console().print(table)

    if bids_folder is not None:
        summary = convert_longwalk_to_bids(output_folder, bids_folder)
        print_longwalk_conversion_summary(summary)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
