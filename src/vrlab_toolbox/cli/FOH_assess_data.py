import logging
from dataclasses import dataclass, field
from pathlib import Path

import click
import pandas as pd
import pyxdf
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing import lsl

logger = logging.getLogger(__name__)

# The LSL streams processing/foh_pipeline.py needs to run the FOH pipeline end to end: OpenSignals
# for EDA/ECG, VR_markers + VR_trial_events for trial intervals, FOH_target for behaviour.
REQUIRED_STREAMS = ["OpenSignals", "VR_markers", "VR_trial_events", "FOH_target"]

EXAMPLES_EPILOG = """
Examples:

\b
  Assess every .xdf file under a study's data folder:
  mobi_foh_assess_data local_lsl_data

\b
  Also save the assessment as a CSV, and log which extra streams each file
  has beyond the ones the pipeline requires:
  mobi_foh_assess_data local_lsl_data --output-csv assessment.csv --verbose

\b
  '*_old*.xdf' files are skipped by default; include them too:
  mobi_foh_assess_data local_lsl_data --all
"""


@dataclass(frozen=True)
class XdfAssessment:
    subject_id: str
    file_path: Path
    present_streams: list[str] = field(default_factory=list)
    missing_streams: list[str] = field(default_factory=list)
    other_streams: list[str] = field(default_factory=list)
    recorded_at: str | None = None
    load_error: str | None = None


def assess_xdf_file(xdf_fn: Path) -> XdfAssessment:
    """Load one xdf file and report which of REQUIRED_STREAMS it has and lacks."""
    subject_id = lsl.get_subject_id(xdf_fn)

    try:
        streams, header = pyxdf.load_xdf(xdf_fn)
    except Exception as error:
        logger.warning("Could not load %s: %s", xdf_fn.name, error)
        return XdfAssessment(
            subject_id=subject_id,
            file_path=xdf_fn,
            missing_streams=REQUIRED_STREAMS,
            load_error=str(error),
        )

    try:
        recorded_at = lsl.get_start_time(header).strftime("%Y-%m-%d %H:%M:%S")

    except (KeyError, IndexError, ValueError) as error:
        logger.warning("No recording date in %s: %s", xdf_fn.name, error)
        recorded_at = None

    # A stream can be present by name but still empty (0 samples) -- that's as unusable as
    # if it were missing entirely, so only count streams with actual data as present.
    sample_counts = {stream["info"]["name"][0]: len(stream["time_series"]) for stream in streams}
    present_stream_names = {name for name, count in sample_counts.items() if count > 0}

    return XdfAssessment(
        subject_id=subject_id,
        file_path=xdf_fn,
        present_streams=[name for name in REQUIRED_STREAMS if name in present_stream_names],
        missing_streams=[name for name in REQUIRED_STREAMS if name not in present_stream_names],
        other_streams=sorted(present_stream_names - set(REQUIRED_STREAMS)),
        recorded_at=recorded_at,
    )


def assess_data_folder(data_folder: Path, include_old: bool = False) -> list[XdfAssessment]:
    """Recursively find every .xdf file under data_folder and assess it."""
    xdf_paths = sorted(data_folder.rglob("*.xdf"))

    if not include_old:
        old_paths = [xdf_path for xdf_path in xdf_paths if "_old" in xdf_path.stem.lower()]
        for old_path in old_paths:
            logger.info(
                "Skipping %s (matches '*_old*.xdf'; pass --all to include it)", old_path.name
            )
        xdf_paths = [xdf_path for xdf_path in xdf_paths if xdf_path not in old_paths]

    results = []
    with Progress() as progress:
        task = progress.add_task("Assessing xdf files...", total=len(xdf_paths))
        for xdf_fn in xdf_paths:
            results.append(assess_xdf_file(xdf_fn))
            progress.advance(task)

    # recorded_at is "%Y-%m-%d %H:%M:%S", so lexicographic order is chronological order.
    # Files with an unknown date (load error or missing header) sort last, not first.
    results.sort(key=lambda result: (result.recorded_at is None, result.recorded_at))

    return results


def build_assessment_table(results: list[XdfAssessment]) -> Table:
    table = Table(title="FOH data availability")
    table.add_column("Subject ID")
    table.add_column("File")
    table.add_column("Recorded At")
    for stream_name in REQUIRED_STREAMS:
        table.add_column(stream_name, justify="center")

    for result in results:
        recorded_at = result.recorded_at or "[red]unknown[/red]"

        if result.load_error:
            table.add_row(
                result.subject_id,
                result.file_path.name,
                recorded_at,
                *("[red]could not load[/red]" for _ in REQUIRED_STREAMS),
            )
            continue

        cells = [
            "[green]present[/green]" if name in result.present_streams else "[red]absent[/red]"
            for name in REQUIRED_STREAMS
        ]
        table.add_row(result.subject_id, result.file_path.name, recorded_at, *cells)

    return table


def save_assessment_csv(results: list[XdfAssessment], output_csv: Path) -> None:
    rows = [
        {
            "Subject_ID": result.subject_id,
            "File": result.file_path.name,
            "Path": str(result.file_path),
            "Recorded_At": result.recorded_at or "",
            **{name: name in result.present_streams for name in REQUIRED_STREAMS},
            "Other_Streams": ";".join(result.other_streams),
            "Load_Error": result.load_error or "",
        }
        for result in results
    ]

    output_csv.unlink(missing_ok=True)
    pd.DataFrame(rows).to_csv(output_csv, index=False)


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "data_folder", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True
)
@click.option(
    "--output-csv",
    type=click.Path(path_type=Path),
    default=None,
    help="Also save the assessment as a CSV file at this path.",
)
@click.option(
    "--verbose", is_flag=True, help="Also log any streams found beyond what the pipeline requires."
)
@click.option(
    "--all",
    "include_old",
    is_flag=True,
    help="Also include '*_old*.xdf' files, which are skipped by default.",
)
def main(data_folder: Path, output_csv: Path | None, verbose: bool, include_old: bool) -> None:
    """Recursively scan DATA_FOLDER for .xdf files and report, per subject and file, which
    streams the FOH pipeline (processing/foh_pipeline.py) needs are present or absent."""

    logger.info("Scanning %s for .xdf files...", data_folder)
    results = assess_data_folder(data_folder, include_old=include_old)

    if not results:
        logger.warning("No .xdf files found under %s", data_folder)
        return

    Console().print(build_assessment_table(results))

    if verbose:
        for result in results:
            if result.other_streams:
                logger.info(
                    "%s (%s) also has: %s",
                    result.subject_id,
                    result.file_path.name,
                    ", ".join(result.other_streams),
                )

    complete_count = sum(1 for result in results if not result.missing_streams)
    logger.info("%d of %d files have all required streams", complete_count, len(results))

    if output_csv is not None:
        save_assessment_csv(results, output_csv)
        logger.info("Saved assessment to %s", output_csv)


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
