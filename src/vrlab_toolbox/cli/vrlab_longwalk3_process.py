"""CLI: batch-process a crosschecked LongwalkV3 BIDS folder into one wide row per subject.

Thin wrapper around `processing/longwalk3_pipeline.run_pipeline_all_sessions` -- same shape as
`vrlab_crane_process` (QC plots + logs + processed_subjects.json in the output folder, then a
group CSV/SAV), see that module for the shared conventions.
"""

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import click
import matplotlib
import pandas as pd
import pandera.pandas as pa
import pyreadstat
from rich.progress import Progress

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.bids import (
    is_bids_like_folder,
    is_effectively_empty_folder,
    paths_conflict,
)
from vrlab_toolbox.processing.longwalk3_pipeline import (
    build_longwalkv3_participant_output_schema,
    run_pipeline_all_sessions,
)
from vrlab_toolbox.processing.plot_utils import save_plot

logger = logging.getLogger(__name__)

# Every physiology recording longwalk3_bids.py writes -- sub-<id>/ses-NN/beh/
# sub-<id>_ses-NN_task-longwalkv3_run-001_physio.acq. A subject is processed if it has any.
PHYSIO_GLOB_PATTERN = "sub-*_task-longwalkv3_*_physio*.acq"
PROCESSED_SUBJECTS_FILENAME = "processed_subjects.json"
BATCH_OUTPUT_STEM = "vrlab_longwalk3_process_batch_data_out"


def _load_processed_subjects(output_folder: Path) -> dict[str, str]:
    path = output_folder / PROCESSED_SUBJECTS_FILENAME
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as processed_file:
            return json.load(processed_file)
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read %s -- treating as empty", path)
        return {}


def _save_processed_subjects(output_folder: Path, processed: dict[str, str]) -> None:
    path = output_folder / PROCESSED_SUBJECTS_FILENAME
    with path.open("w", encoding="utf-8") as processed_file:
        json.dump(processed, processed_file, indent=2, sort_keys=True)


def find_subject_ids(input_folder: Path) -> list[str]:
    """Subjects with at least one physiology recording, from their `sub-<id>` folder name."""
    subject_ids = set()
    for physio_file in input_folder.rglob(PHYSIO_GLOB_PATTERN):
        subject_folder = next(
            (p for p in physio_file.relative_to(input_folder).parts if p.startswith("sub-")), None
        )
        if subject_folder is not None:
            subject_ids.add(subject_folder.removeprefix("sub-"))
    return sorted(subject_ids)


def run_batch(
    input_folder: Path,
    output_folder: Path,
    subject_id: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    skip_existing: bool = False,
) -> Path:
    """Processes every LongwalkV3 subject under `input_folder` (all their sessions, one wide
    row each), writing QC plots and logs into `output_folder`, then the group CSV/SAV.
    Returns the path to the batch CSV. Same contract as `vrlab_crane_process.run_batch`:
    `subject_id` only prefixes the output filename, `progress_callback(index, total, id)` is
    called once per subject, and `skip_existing` reuses rows of subjects already recorded in
    PROCESSED_SUBJECTS_FILENAME.
    """
    log_folder = output_folder / "logs"
    log_folder.mkdir(parents=True, exist_ok=True)
    vrlab_logging.init(__file__, log_dir_in=log_folder)
    logger.info("Looking into input folder: %s. Output folder: %s", input_folder, output_folder)

    data_out_fn = os.path.join(output_folder, f"{subject_id}{BATCH_OUTPUT_STEM}")
    existing_csv_path = Path(data_out_fn + ".csv")

    processed_subjects = _load_processed_subjects(output_folder)
    existing_df: pd.DataFrame | None = None
    if skip_existing and existing_csv_path.is_file():
        try:
            existing_df = pd.read_csv(existing_csv_path, dtype={"Subject_ID": str})
            existing_df = existing_df.drop(
                columns=[c for c in existing_df.columns if c.startswith("Unnamed")],
                errors="ignore",
            )
        except (OSError, pd.errors.ParserError) as error:
            logger.warning(
                "Could not read existing %s (%s) -- reprocessing everyone", existing_csv_path, error
            )

    subject_ids = find_subject_ids(Path(input_folder))
    out_file_parts: list[pd.DataFrame] = []
    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=len(subject_ids))
        for index, current_id in enumerate(subject_ids, start=1):
            progress.update(task, description=f"Processing subject {current_id}", advance=1)
            if progress_callback is not None:
                progress_callback(index, len(subject_ids), current_id)

            if skip_existing and current_id in processed_subjects and existing_df is not None:
                existing_rows = existing_df.loc[existing_df["Subject_ID"] == current_id]
                if not existing_rows.empty:
                    out_file_parts.append(existing_rows.head(1).reset_index(drop=True))
                    logger.info(
                        "Skipping subject %s -- already processed at %s",
                        current_id,
                        processed_subjects[current_id],
                    )
                    continue

            vrlab_logging.log_section(logger, f"Subject {current_id}")
            try:
                pipeline_output = run_pipeline_all_sessions(current_id, input_folder, output_folder)
            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Skipping subject %s because processing failed: %s", current_id, error
                )
                continue

            for fig_title, fig in pipeline_output.figure_data_out.items():
                try:
                    save_plot(fig, output_folder, current_id, f"Subject {current_id} - {fig_title}")
                finally:
                    plt.close(fig)

            out_file_parts.append(pipeline_output.subject_df_out.reset_index(drop=True))
            processed_subjects[current_id] = datetime.now().strftime("%Y-%m-%d %H:%M")
            logger.info("Done longwalkV3 pipeline for subject %s", current_id)

    _save_processed_subjects(output_folder, processed_subjects)

    if not out_file_parts:
        logger.warning("No subjects processed -- nothing matching %s found.", PHYSIO_GLOB_PATTERN)
        raise FileNotFoundError(f"No processable LongwalkV3 subjects found in {input_folder}")

    participant_df_out = pd.concat(out_file_parts, axis=0, ignore_index=True)
    try:
        validated = build_longwalkv3_participant_output_schema().validate(participant_df_out)
    except pa.errors.SchemaError as e:
        logger.error("Error validating final output file: %s", e)
        raise

    participant_df_out.to_csv(data_out_fn + ".csv")
    logger.info("Successfully validated final output file")

    pyreadstat.write_sav(
        validated,
        data_out_fn + ".sav",
        variable_format={"Subject_ID": "A20"},
        variable_measure={"Subject_ID": "nominal"},
    )
    logger.info("Saved final SPSS output file to %s", data_out_fn + ".sav")
    return Path(data_out_fn + ".csv")


@click.command()
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument(
    "output_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.option("--subject_id", required=False, default="", help="Prefix for the output filenames")
@click.option("--verbose", is_flag=True, help="Give verbose output")
@click.option(
    "--rerun",
    is_flag=True,
    help=(
        "Reprocess every subject found, even ones already recorded in "
        "processed_subjects.json. Default is to skip those and only process new ones."
    ),
)
def main(input_folder: Path, output_folder: Path, verbose: bool, subject_id: str, rerun: bool):
    """Batch-process LongwalkV3 physiology + behaviour: one wide row per subject, every
    session's columns prefixed sesNN_.

    `input_folder` must be a BIDS folder that has been through the crosscheck tool
    (vrlab_longwalk3_bids_crosscheck) -- aborted runs and wrong-city starts removed, dates
    corrected -- before processing.
    """
    if paths_conflict(input_folder, output_folder):
        raise click.UsageError(
            "output_folder can't be the same as (or contain, or be contained by) "
            "input_folder -- pick a separate folder for processing output."
        )
    if is_effectively_empty_folder(input_folder):
        raise click.UsageError(
            f"{input_folder} is empty. Run the crosscheck tool first "
            "(vrlab_longwalk3_bids_crosscheck) -- it converts raw data into a BIDS folder."
        )
    if not is_bids_like_folder(input_folder):
        raise click.UsageError(
            f"{input_folder} doesn't look like a BIDS folder (no sub-* subject folders found)."
        )
    run_batch(input_folder, output_folder, subject_id, skip_existing=not rerun)


if __name__ == "__main__":
    main()
