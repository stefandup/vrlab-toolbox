import logging
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing.crane_dummy_data import ERROR_TYPES, generate_dummy_dataset

logger = logging.getLogger(__name__)


@click.command()
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
def main(
    template_folder: Path,
    output_folder: Path,
    n_clean: int,
    with_errors: bool,
    seed: int | None,
    verbose: bool,
) -> None:
    """Generate synthetic crane participant data by cloning and perturbing template files."""

    output_folder.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Generating dummy crane data into %s from templates in %s", output_folder, template_folder
    )

    with Progress() as progress:
        task = progress.add_task("Generating dummy crane data...", total=None)
        results = generate_dummy_dataset(template_folder, output_folder, n_clean, with_errors, seed)
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


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
