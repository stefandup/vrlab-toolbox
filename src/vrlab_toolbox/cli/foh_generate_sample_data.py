import logging
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from vrlab_toolbox import mobi_logging
from vrlab_toolbox.processing.foh_dummy_data import (
    DUMMY_DATA_LOG_FILENAME,
    ERROR_TYPES,
    generate_dummy_foh_dataset,
)

logger = logging.getLogger(__name__)

EXAMPLES_EPILOG = f"""
Examples:

\\b
  5 clean participants, reproducible:
  foh_generate_sample_data foh_examples --seed 42

\\b
  Also add one participant per known error scenario (missing streams, a
  sampling-rate mismatch, ...):
  foh_generate_sample_data foh_examples --with-errors --seed 42

\\b
  Every run writes/updates "{DUMMY_DATA_LOG_FILENAME}" inside output_folder --
  a plain-text, one-line-per-participant explanation of what each generated
  participant's scenario is for. Open it any time to see what's in a given
  dummy folder without reading this tool's source.
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="mooi-toolbox")
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--n-clean", default=5, show_default=True, help="Number of well-formed dummy participants"
)
@click.option(
    "--with-errors",
    is_flag=True,
    help=f"Also generate one participant per known error scenario: {', '.join(ERROR_TYPES)}",
)
@click.option("--seed", type=int, default=None, help="Seed for reproducible generation")
def main(output_folder: Path, n_clean: int, with_errors: bool, seed: int | None) -> None:
    """Generate synthetic FOH LSL recordings from scratch (no template files needed --
    unlike crane_generate_sample_data, FOH's raw recording is a single multi-stream .xdf
    file, built here rather than cloned and perturbed from a real one).

    Writes straight into the already-BIDS-shaped layout FOH's own recording software
    produces (`sub-XXX/ses-S001/beh/..._task-foh_run-001_beh.xdf`) -- the same layout
    ParticipantConfig.from_lsl_data and vrlab_foh_batch_process expect, so output_folder can
    be pointed at directly, with no separate conversion step.
    """
    output_folder.mkdir(parents=True, exist_ok=True)

    logger.info("Generating dummy FOH data into %s", output_folder)
    with Progress() as progress:
        task = progress.add_task("Generating dummy FOH data...", total=None)
        results = generate_dummy_foh_dataset(output_folder, n_clean, with_errors, seed)
        progress.update(task, total=1, completed=1)

    table = Table(title="Generated FOH dummy data")
    table.add_column("Subject ID")
    table.add_column("Scenario")
    table.add_column("Recording file")

    for result in results:
        table.add_row(result.subject_id, result.scenario, result.xdf_path.name)

    Console().print(table)
    logger.info("Generated %d dummy participants in %s", len(results), output_folder)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
