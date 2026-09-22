from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.longwalk3_dummy_data import (
    DEFAULT_CITY_LABELS,
    ERROR_TYPES,
    generate_dummy_longwalkv3_dataset,
)

EXAMPLES_EPILOG = f"""
Examples:

\b
  1 clean dummy participant ("dummy01"), reproducible, one city per session (ses-01=city1,
  ses-02=city2, ses-03=city3) -- cloned from the templates in longwalkv3_examples/ with date
  and worldLocation columns reshaped (see longwalk3_dummy_data.py):
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy

\b
  Also add one participant per known error scenario: {", ".join(ERROR_TYPES)}:
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy --with-errors

\b
  5 clean dummy participants, only city1/city2:
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy \\
    --n-clean 5 --cities city1 --cities city2
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "template_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--n-clean", default=1, show_default=True, help="Number of well-formed dummy participants"
)
@click.option(
    "--with-errors",
    is_flag=True,
    help=f"Also generate one participant per known error scenario: {', '.join(ERROR_TYPES)}",
)
@click.option(
    "--cities",
    multiple=True,
    default=DEFAULT_CITY_LABELS,
    show_default=True,
    help="Task labels to generate a behaviour/actor-log file set for, repeatable "
    "(--cities city1 --cities city2 ...).",
)
@click.option("--seed", type=int, default=None, help="Seed for reproducible generation")
def main(
    template_folder: Path,
    output_folder: Path,
    n_clean: int,
    with_errors: bool,
    cities: tuple[str, ...],
    seed: int | None,
) -> None:
    """Generate synthetic longwalkV3 participant data from the raw file set in template_folder
    (see longwalkv3_examples/): one .acq physiology file per session (sessions are different
    days, so physiology can't span them -- see longwalk3_dummy_data.py), plus one behaviour.csv
    and one actor-location log per city per session.

    A well-formed ("clean") participant gets one city's file set per session (longwalkV3 has 3
    planned sessions -- ses-01=city_labels[0], ses-02=city_labels[1], ...). --with-errors also
    adds one participant per known error scenario -- currently just
    "multiple_cities_per_session", which still has the standard number of sessions, but one
    randomly chosen session gets two runs instead of one: the wrong city first (as if that city
    was started by mistake), then that session's actually-planned city. Both are written as
    run-000, the same as the real Unreal-side export always does -- exercising detection of a
    session with more than one run/city, without it always being the same session.

    Each actor-location log's year/month/day/hour/minute/second/millisecond columns are combined
    into a single "date" column (concatenated yyyyMMddHHmmssSSS, e.g. "20260916175501873" -- the
    millisecond part is randomly generated per row, reproducibly under --seed, since the
    template CSVs don't carry a real recorded value yet), and its
    worldLocationX/Y/Z columns into a single "worldLocation" column formatted the way an Unreal
    FVector prints via ToString() (e.g. "X=1.0 Y=2.0 Z=3.0"). Repeated header rows in a template
    are preserved as-is.
    """

    output_folder.mkdir(parents=True, exist_ok=True)

    dataset_result = generate_dummy_longwalkv3_dataset(
        template_folder, output_folder, n_clean, with_errors, cities, seed
    )

    table = Table(title="Generated longwalkV3 dummy data")
    table.add_column("Subject ID")
    table.add_column("Scenario")
    table.add_column("Physiology files")
    table.add_column("Behaviour files")
    table.add_column("Actor-log files")

    for result in dataset_result.participant_results:
        table.add_row(
            result.subject_id,
            result.scenario,
            str(len(result.acq_paths)),
            str(len(result.behaviour_paths)),
            str(len(result.actor_log_paths)),
        )

    console = Console()
    console.print(table)

    if dataset_result.redcap_debrief_path is not None:
        console.print(
            f"[green]Dummy REDCap debrief file written for "
            f"{len(dataset_result.participant_results)} subject(s):[/green] "
            f"{dataset_result.redcap_debrief_path}"
        )
    else:
        console.print(
            "[yellow]No REDCap debrief export template found -- skipped dummy debrief "
            "file.[/yellow]"
        )


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
