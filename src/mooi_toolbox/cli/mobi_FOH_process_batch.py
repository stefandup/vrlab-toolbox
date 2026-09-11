import json
import logging
import os
from datetime import datetime
from pathlib import Path

import click
import matplotlib.pyplot as plt
import pandas as pd
import pyreadstat
from rich.progress import Progress

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import lsl
from mooi_toolbox.processing.bids import (
    is_bids_like_folder,
    is_effectively_empty_folder,
    paths_conflict,
)
from mooi_toolbox.processing.foh_pipeline import run_pipeline
from mooi_toolbox.processing.plot_utils import save_plot

logger = logging.getLogger(__name__)

# Matches any recording under a BIDS folder -- the same pattern `run_batch` globs for
# below, named/exposed the same way vrlab_crane_process.py's PHYSIO_GLOB_PATTERN is, for
# a future FOH process-results GUI to reuse without duplicating it.
XDF_GLOB_PATTERN = "*.xdf"

# Written into `output_folder` by `run_batch` -- {subject_id: "<when last processed>"},
# see `_load_processed_subjects`/`_save_processed_subjects`. Lets a re-run skip a subject
# that's already been processed (`main`'s `--rerun` flag flips this off) instead of
# always reprocessing everyone.
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


def run_batch(input_folder: Path, output_folder: Path, skip_existing: bool = False) -> Path | None:
    """Batch-processes every FOH LSL recording found under `input_folder`, writing QC
    plots and per-subject/batch logs into `output_folder`, then the group CSV/SAV
    output. Returns the path to the batch CSV, or None if nothing was processed.

    `skip_existing`, if true, skips any subject already recorded in
    `PROCESSED_SUBJECTS_FILENAME` -- reusing their row from the *existing* batch CSV
    (rather than dropping them from the new one) if that row is still there. Every
    subject actually processed this run (skipped or not) is (re-)recorded, so the
    manifest self-heals if it's ever out of step with the CSV. Defaults to False here
    (a plain function call reprocesses everyone, every time) -- `main` below flips that
    default via its own `--rerun` flag, so the CLI skips already-processed subjects
    unless told otherwise, while this function itself stays neutral for any other
    caller that doesn't pass the argument explicitly.
    """
    log_folder = Path.joinpath(output_folder, "logs")
    log_folder.mkdir(parents=True, exist_ok=True)
    mobi_logging.init(__file__, log_dir_in=log_folder)
    logger.info(f"Looking into input folder: {input_folder}. Output folder: {output_folder}")

    out_fn = os.path.join(output_folder, "FOH_process_batch_out")
    existing_csv_path = Path(out_fn + ".csv")

    processed_subjects = _load_processed_subjects(output_folder)
    existing_df: pd.DataFrame | None = None
    if skip_existing and existing_csv_path.is_file():
        try:
            existing_df = pd.read_csv(existing_csv_path, dtype={"Subject_ID": str})
        except (OSError, pd.errors.ParserError) as error:
            logger.warning(
                "Could not read existing %s (%s) -- reprocessing everyone",
                existing_csv_path,
                error,
            )

    root = input_folder
    out_file_parts = []
    xdf_fns = list(root.rglob(XDF_GLOB_PATTERN))
    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=len(xdf_fns))

        for xdf_fn in xdf_fns:
            subject_id = lsl.get_subject_id(xdf_fn)

            progress.update(
                task,
                description=f"Processing subject {subject_id}",
                advance=1,
            )

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
            try:
                pipeline_output = run_pipeline(subject_id, input_folder, output_folder)
                participant_data_out = pipeline_output.subject_df_out
                # TODO: import and merge the subjective stress measure for this subject
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
                logger.info(f"Done FOH pipeline for subject {subject_id}")
            # TODO Exceptions can be narrowed here
            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Skipping subject %s because processing failed: %s", subject_id, error
                )
                continue
    _save_processed_subjects(output_folder, processed_subjects)

    # TODO TEST
    if len(out_file_parts) == 0:
        logger.warning("No files were successfully processed.")
        return None

    out_df = pd.concat(out_file_parts, axis=0)
    out_df.to_csv(out_fn + ".csv", index=False)

    pyreadstat.write_sav(
        out_df,
        out_fn + ".sav",
        variable_format={"Subject_ID": "A20"},
        variable_measure={"Subject_ID": "nominal"},
    )

    logger.info(f"Saved output to {out_fn}")

    return Path(out_fn + ".csv")


@click.command()
@click.version_option(package_name="mooi-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument(
    "output_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.option("--verbose", is_flag=True, help="Give verbose output")
@click.option(
    "--rerun",
    is_flag=True,
    help=(
        "Reprocess every subject found, even ones already recorded in "
        "processed_subjects.json. Default is to skip those and only process new ones."
    ),
)
def main(input_folder: Path, output_folder: Path, verbose: bool, rerun: bool):
    """CLI tool for processing and plotting MOBI LSL data for FOH VR task.

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
            "dataset yet (vrlab_foh_bids_crosscheck.exe), do that first -- it's what "
            "converts raw data into a BIDS folder."
        )
    if not is_bids_like_folder(input_folder):
        raise click.UsageError(
            f"{input_folder} doesn't look like a BIDS folder (no sub-* subject folders "
            "found) -- input_folder must be a BIDS-formatted folder."
        )
    run_batch(input_folder, output_folder, skip_existing=not rerun)


if __name__ == "__main__":
    main()
