import logging
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from mooi_toolbox import mobi_logging
from mooi_toolbox.cli.crane_convert_to_bids import convert_crane_to_bids, print_conversion_summary
from mooi_toolbox.processing.crane_dummy_data import (
    ERROR_TYPES,
    REFERENCE_ERROR_TYPES,
    generate_dummy_dataset,
    generate_dummy_participant_matching_reference,
)

logger = logging.getLogger(__name__)

EXAMPLES_EPILOG = f"""
Examples:

\b
  5 clean participants, reproducible:
  crane_generate_sample_data examples/crane_templates examples --seed 42

\b
  Also add one participant per known error scenario (missing files, bad
  triggers, ...):
  crane_generate_sample_data examples/crane_templates examples --with-errors --seed 42

\b
  Reproduce one real crane_data/ participant's trigger anomaly, without
  exposing their data (only that file's trigger-pulse timing is ever read).
  --reference-error-type is not an arbitrary label — it must be one of:
  {", ".join(REFERENCE_ERROR_TYPES)}:
  crane_generate_sample_data examples/crane_templates examples \\
    --reference-folder crane_data \\
    --reference-subject-id PID16186 \\
    --reference-error-type missing_initial_trigger

\b
  Same, but choose the generated participant's ID yourself (default is
  REF<reference-subject-id>):
  crane_generate_sample_data examples/crane_templates examples \\
    --reference-folder crane_data \\
    --reference-subject-id PID16186 \\
    --reference-error-type missing_initial_trigger \\
    --reference-output-subject-id DUMMY011

\b
  Also convert the freshly-generated raw data into a BIDS folder in the same
  call, via crane_convert_to_bids.convert_crane_to_bids -- output_folder still
  ends up holding the plain raw CraneOut files either way:
  crane_generate_sample_data examples/crane_templates examples \\
    --with-errors --seed 42 --bids-folder examples_bids
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="mooi-toolbox")
@click.argument(
    "template_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
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
@click.option("--verbose", is_flag=True, help="Give verbose output")
@click.option(
    "--reference-folder",
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    default=None,
    help="Folder holding a real participant's file to copy a trigger anomaly's shape from "
    "(e.g. your local, gitignored crane_data/). Only that file's trigger-pulse timing is ever "
    "read — never its signal values. Requires --reference-subject-id and --reference-error-type.",
)
@click.option(
    "--reference-subject-id",
    default=None,
    help="Real participant ID under --reference-folder to match the trigger anomaly of.",
)
@click.option(
    "--reference-error-type",
    type=click.Choice(REFERENCE_ERROR_TYPES),
    default=None,
    help="Which trigger anomaly --reference-subject-id has.",
)
@click.option(
    "--reference-output-subject-id",
    default=None,
    help="Subject ID for the generated participant (default: REF<reference-subject-id>).",
)
@click.option(
    "--bids-folder",
    type=click.Path(path_type=Path),
    default=None,
    help="If given, also runs the freshly-generated raw data in output_folder through "
    "crane_convert_to_bids into this BIDS folder -- generate and convert in one call instead "
    "of two. output_folder still ends up holding the plain raw CraneOut files either way.",
)
def main(
    template_folder: Path,
    output_folder: Path,
    n_clean: int,
    with_errors: bool,
    seed: int | None,
    verbose: bool,
    reference_folder: Path | None,
    reference_subject_id: str | None,
    reference_error_type: str | None,
    reference_output_subject_id: str | None,
    bids_folder: Path | None,
) -> None:
    """Generate synthetic crane participant data by cloning and perturbing template files."""

    output_folder.mkdir(parents=True, exist_ok=True)

    reference_args = (reference_folder, reference_subject_id, reference_error_type)
    if any(reference_args) and not all(reference_args):
        raise click.UsageError(
            "--reference-folder, --reference-subject-id and --reference-error-type must be "
            "given together."
        )

    if all(reference_args):
        logger.info(
            "Generating one dummy participant matching %s (%s) from %s",
            reference_subject_id,
            reference_error_type,
            reference_folder,
        )
        result = generate_dummy_participant_matching_reference(
            template_folder,
            output_folder,
            reference_folder,
            reference_subject_id,
            reference_error_type,
            subject_id=reference_output_subject_id,
            seed=seed,
        )
        results = [result]
    else:
        logger.info(
            "Generating dummy crane data into %s from templates in %s", output_folder, template_folder
        )
        with Progress() as progress:
            task = progress.add_task("Generating dummy crane data...", total=None)
            results = generate_dummy_dataset(
                template_folder, output_folder, n_clean, with_errors, seed
            )
            progress.update(task, total=1, completed=1)

    table = Table(title="Generated crane dummy data")
    table.add_column("Subject ID")
    table.add_column("Scenario")
    table.add_column("Behaviour file")
    table.add_column("Physiology file")

    for result in results:
        table.add_row(
            result.subject_id,
            result.scenario,
            result.csv_path.name if result.csv_path else "(missing)",
            result.mat_path.name if result.mat_path else "(missing)",
        )

    Console().print(table)
    logger.info("Generated %d dummy participants in %s", len(results), output_folder)

    if bids_folder is not None:
        logger.info("Converting %s into BIDS folder %s", output_folder, bids_folder)
        summary = convert_crane_to_bids(output_folder, bids_folder)
        print_conversion_summary(summary)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
