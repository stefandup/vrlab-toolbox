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

from vrlab_toolbox import mobi_logging
from vrlab_toolbox.processing import biopac
from vrlab_toolbox.processing.bids import (
    is_bids_like_folder,
    is_effectively_empty_folder,
    paths_conflict,
)
from vrlab_toolbox.processing.longwalk_pipeline import build_longwalk_participant_output_schema
from vrlab_toolbox.processing.longwalk_pipeline import run_pipeline as run_longwalk_pipeline
from vrlab_toolbox.processing.plot_utils import save_plot

logger = logging.getLogger(__name__)

# Matches sub-<id>_task-longwalk_acq-physiology..._physio.mat under a BIDS folder -- the
# same pattern `run_batch` globs for below, exposed here so a caller (e.g. the longwalk
# process-results GUI, see longwalk_process_results_gui.py) can discover the same
# subject roster from the BIDS folder itself without duplicating this string.
PHYSIO_GLOB_PATTERN = "sub-*_task-longwalk_acq-physiology*_physio.mat"

# Written into `output_folder` by `run_batch` -- {subject_id: "<when last processed>"},
# see `_load_processed_subjects`/`_save_processed_subjects`. Lets a re-run skip a subject
# that's already been processed (the GUI's "Skip already-processed subjects" checkbox;
# see `run_batch`'s `skip_existing` parameter) instead of always reprocessing everyone.
PROCESSED_SUBJECTS_FILENAME = "processed_subjects.json"


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


def run_batch(
    input_folder: Path,
    output_folder: Path,
    subject_id: str = "",
    progress_callback: Callable[[int, int, str], None] | None = None,
    skip_existing: bool = False,
) -> Path:
    """Batch-processes every longwalk physiology recording found under `input_folder`,
    writing QC plots and per-subject/batch logs into `output_folder`, then the group
    CSV/SAV output. Returns the path to the batch CSV. `subject_id`, if given, only
    changes the output filename prefix (see `main`'s `--subject_id` option) -- it
    doesn't filter which subjects get processed.

    `progress_callback`, if given, is called once per subject as
    `progress_callback(index, total, subject_id)`, *in addition to* (not instead of)
    the `rich.Progress` terminal bar below -- that bar has nowhere to draw when this
    runs inside a windowed (console-less) GUI process, which is exactly when a caller
    needs this callback instead. Plain callable, no Qt import here: the longwalk
    process-results GUI's "Process BIDS Folder" button
    (`longwalk_process_results_gui.py`) is the one that turns this into a progress bar,
    not this function.

    `skip_existing`, if true, skips any subject already recorded in
    `PROCESSED_SUBJECTS_FILENAME` -- reusing their row from the *existing* batch CSV
    (rather than dropping them from the new one) if that row is still there. Every
    subject actually processed this run (skipped or not) is (re-)recorded, so the
    manifest self-heals if it's ever out of step with the CSV. Defaults to False here
    (a plain function call reprocesses everyone, every time) -- `main` below flips that
    default via its own `--rerun` flag, so the CLI skips already-processed subjects
    unless told otherwise, while this function itself stays neutral for any other
    caller that doesn't pass the argument explicitly.

    Shared by the `vrlab_longwalk_process` CLI below and that GUI button -- both call
    this same function rather than one wrapping the other.
    """
    log_folder = Path.joinpath(output_folder, "logs")
    log_folder.mkdir(parents=True, exist_ok=True)
    mobi_logging.init(__file__, log_dir_in=log_folder)
    participant_data_out = None

    logger.info("Looking into input folder: %s. Output folder: %s", input_folder, output_folder)

    data_out_fn = os.path.join(output_folder, f"{subject_id}vrlab_longwalk_process_batch_data_out")
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
                "Could not read existing %s (%s) -- reprocessing everyone",
                existing_csv_path,
                error,
            )

    root = Path(input_folder)
    out_file_parts = []
    subject_mat_files = list(root.rglob(PHYSIO_GLOB_PATTERN))

    total_subjects = len(subject_mat_files)
    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=total_subjects)

        for index, biopac_mat_fn in enumerate(subject_mat_files, start=1):
            subject_id = biopac.get_subject_id_from_mat(biopac_mat_fn)

            progress.update(
                task,
                description=f"Processing subject {subject_id}",
                advance=1,
            )
            if progress_callback is not None:
                progress_callback(index, total_subjects, subject_id)

            if skip_existing and subject_id in processed_subjects and existing_df is not None:
                existing_rows = existing_df.loc[existing_df["Subject_ID"] == subject_id]
                if not existing_rows.empty:
                    out_file_parts.append(existing_rows.head(1).reset_index(drop=True))
                    logger.info(
                        "Skipping subject %s -- already processed at %s",
                        subject_id,
                        processed_subjects[subject_id],
                    )
                    continue
                logger.info(
                    "Subject %s marked processed but missing from %s -- reprocessing",
                    subject_id,
                    existing_csv_path.name,
                )

            mobi_logging.log_section(logger, f"Subject {subject_id}")
            logger.info("Trying to read file %s", biopac_mat_fn)

            try:
                pipeline_output = run_longwalk_pipeline(subject_id, input_folder, output_folder)
                participant_data_out = pipeline_output.subject_df_out
                figures = pipeline_output.figure_data_out

                if figures:
                    for fig_title, fig in figures.items():
                        try:
                            save_plot(
                                fig,
                                output_folder,
                                subject_id,
                                f"Subject {subject_id} - {fig_title}",
                            )
                        finally:
                            plt.close(fig)

                if participant_data_out.empty:
                    logger.warning("No participant output for subject %s", subject_id)
                    continue

                participant_data_out = participant_data_out.reset_index(drop=True)

                out_file_parts.append(participant_data_out)
                processed_subjects[subject_id] = datetime.now().strftime("%Y-%m-%d %H:%M")
                logger.info("Done longwalk pipeline for subject %s", subject_id)

            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Skipping subject %s because processing failed: %s", subject_id, error
                )
                continue
    _save_processed_subjects(output_folder, processed_subjects)

    if out_file_parts is None:
        logger.warning(f"No files found searching for {PHYSIO_GLOB_PATTERN}.")
        raise FileNotFoundError

    participant_df_out = pd.concat(out_file_parts, axis=0)

    try:
        participant_df_out_validated = build_longwalk_participant_output_schema().validate(
            participant_df_out
        )
    except pa.errors.SchemaError as e:
        logger.error(
            "Error validating final output file: %s", e.failure_cases.to_string(index=False)
        )
        raise

    participant_df_out.to_csv(data_out_fn + ".csv")

    logger.info("Successfully validated final output file")

    pyreadstat.write_sav(
        participant_df_out_validated,
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
@click.option("--subject_id", required=False, default="", help="Process a single participant")
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
    """CLI tool for batch processing VRLab longwalk behaviour and physiology data.

    `input_folder` must be a BIDS-formatted folder. This assumes the data has
    already been through the crosscheck tool (i.e. vrlab_longwalk_bids_crosscheck.exe)
    so duplicate runs and id/date corrections are resolved before processing.

    By default, skips any subject already recorded in processed_subjects.json
    (written into `output_folder` the first time it's processed) -- pass --rerun to
    reprocess everyone found instead.
    """
    if paths_conflict(input_folder, output_folder):
        raise click.UsageError(
            "output_folder can't be the same as (or contain, or be contained by) "
            "input_folder -- pick a separate folder for processing output."
        )
    if is_effectively_empty_folder(input_folder):
        raise click.UsageError(
            f"{input_folder} is empty. If you haven't run the crosscheck tool for this "
            "dataset yet (vrlab_longwalk_bids_crosscheck.exe), do that first -- it's what "
            "converts raw data into a BIDS folder."
        )
    if not is_bids_like_folder(input_folder):
        raise click.UsageError(
            f"{input_folder} doesn't look like a BIDS folder (no sub-* subject folders "
            "found) -- input_folder must be a BIDS-formatted folder."
        )
    run_batch(input_folder, output_folder, subject_id, skip_existing=not rerun)


if __name__ == "__main__":
    main()
