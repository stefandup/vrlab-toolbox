from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.longwalk3_dummy_data import (
    DEFAULT_CITY_LABELS,
    generate_dummy_longwalkv3_dataset,
)

EXAMPLES_EPILOG = """
Examples:

\b
  1 dummy participant ("dummy01"), reproducible, one behaviour/actor-log set per city -
  cloned from the templates in longwalkv3_examples/ with date and worldLocation columns
  reshaped (see longwalk3_dummy_data.py):
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy

\b
  5 dummy participants, only city1/city2:
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy \\
    --n-subjects 5 --cities city1 --cities city2
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "template_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--n-subjects", default=1, show_default=True, help="Number of dummy participants to generate"
)
@click.option(
    "--cities",
    multiple=True,
    default=DEFAULT_CITY_LABELS,
    show_default=True,
    help="Task labels to generate a behaviour/actor-log file set for, repeatable "
    "(--cities city1 --cities city2 ...).",
)
def main(
    template_folder: Path,
    output_folder: Path,
    n_subjects: int,
    cities: tuple[str, ...],
) -> None:
    """Generate synthetic longwalkV3 participant data from the raw file set in template_folder
    (see longwalkv3_examples/): one .acq physiology file per participant, plus one
    behaviour.csv and one actor-location log per city per participant.

    Each actor-location log's year/month/day/hour/minute/second columns are combined into a
    single ISO 8601 "date" column, and its worldLocationX/Y/Z columns into a single
    "worldLocation" column formatted the way an Unreal FVector prints via ToString() (e.g.
    "X=1.0 Y=2.0 Z=3.0"). Repeated header rows in a template are preserved as-is.
    """

    output_folder.mkdir(parents=True, exist_ok=True)

    results = generate_dummy_longwalkv3_dataset(template_folder, output_folder, n_subjects, cities)

    table = Table(title="Generated longwalkV3 dummy data")
    table.add_column("Subject ID")
    table.add_column("Physiology file")
    table.add_column("Behaviour files")
    table.add_column("Actor-log files")

    for result in results:
        table.add_row(
            result.subject_id,
            result.acq_path.name,
            str(len(result.behaviour_paths)),
            str(len(result.actor_log_paths)),
        )

    Console().print(table)


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
