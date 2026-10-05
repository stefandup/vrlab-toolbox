from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import click
import matplotlib.pyplot as plt
import pandas as pd
import pandera.pandas as pa
import pyreadstat
from rich.progress import Progress

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.bids import (
    is_bids_like_folder,
    is_effectively_empty_folder,
    paths_conflict,
)
from vrlab_toolbox.processing.plot_utils import save_plot
from vrlab_toolbox.processing.spiral_pipeline import (
    build_spiral_participant_output_schema,
    run_pipeline,
)

logger = logging.getLogger(__name__)

PHYSIO_GLOB_PATTERN = "*.xdf"
PROCESSED_SUBJECTS_FILENAME = "processed_subjects.json"
OUTPUT_BASENAME = "spiral_process_batch_out"


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


def find_spiral_subject_ids(input_folder: Path) -> list[str]:
    subject_ids = []

    for subject_folder in sorted(input_folder.glob("sub-*")):
        if not subject_folder.is_dir():
            continue
        if not any(subject_folder.rglob("*.xdf")):
            continue
        subject_ids.append(subject_folder.name.removeprefix("sub-"))

    return subject_ids


def clean_final_output(output_df: pd.DataFrame) -> pd.DataFrame:
    preferred_columns = [
        "Subject_ID",
        "XDF_File",
        "Spiral_Attempts_Detected",
        "Spiral_Selected_Count",
        "Switch_Time_sec",
        "Dominant_SCR_per_min",
        "NonDominant_SCR_per_min",
        "C3_dominant_alpha",
        "C3_nondominant_alpha",
        "C3_dominant_beta",
        "C3_nondominant_beta",
        "C4_dominant_alpha",
        "C4_nondominant_alpha",
        "C4_dominant_beta",
        "C4_nondominant_beta",
        "Cz_dominant_alpha",
        "Cz_nondominant_alpha",
        "Cz_dominant_beta",
        "Cz_nondominant_beta",
        "O1_dominant_alpha",
        "O1_nondominant_alpha",
        "O2_dominant_alpha",
        "O2_nondominant_alpha",
        "Processing_Status",
    ]

    legacy_debug_columns = {
        "Selected_XDF",
        "Selection_Status",
        "Selection_Reason",
        "QC_Status",
        "Missing_Items",
        "XDF_Path",
        "Candidate_Count",
        "Candidate_Files",
        "Selection_Ambiguous",
        "Selection_Class",
        "Selection_Label",
        "Selection_Note",
        "Selection_Tuple",
        "Selected_By",
        "Filename_Is_Current_EEG_XDF",
        "Subject_Has_Any_EEG_XDF",
        "Selected_XDF_Has_EEG",
        "Drawing_Start_XDF_Time",
        "Drawing_End_XDF_Time",
        "Pen_Present",
        "Pen_Samples",
        "Pen_Stream_Name",
        "Pen_Stream_Type",
        "Pen_Effective_SRate",
        "Pen_Duration_sec",
        "Neon_Gaze_Samples",
        "Neon_Gaze_Stream_Name",
        "Neon_Gaze_Stream_Type",
        "Neon_Gaze_Effective_SRate",
        "Neon_Gaze_Duration_sec",
        "Any_Neon_Present",
        "Any_Neon_Samples",
        "Any_Neon_Stream_Name",
        "Any_Neon_Stream_Type",
        "EEG_Samples",
        "EEG_Stream_Name",
        "EEG_Stream_Type",
        "EEG_Effective_SRate",
        "EEG_Duration_sec",
        "EDA_Samples",
        "EDA_Stream_Name",
        "ECG_Samples",
        "ECG_Stream_Name",
        "Total_Streams",
        "Total_NonEmpty_Streams",
        "Total_Samples_All_Streams",
    }

    final_columns = [column for column in preferred_columns if column in output_df.columns]
    final_columns.extend(
        column
        for column in output_df.columns
        if column not in final_columns and column not in legacy_debug_columns
    )

    return output_df.loc[:, list(dict.fromkeys(final_columns))].copy()


def run_batch(
    input_folder: Path,
    output_folder: Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
    skip_existing: bool = False,
) -> Path | None:
    log_folder = output_folder / "logs"
    log_folder.mkdir(parents=True, exist_ok=True)
    vrlab_logging.init(__file__, log_dir_in=log_folder)

    logger.info(
        "Looking into input folder: %s. Output folder: %s",
        input_folder,
        output_folder,
    )

    csv_path = output_folder / f"{OUTPUT_BASENAME}.csv"
    sav_path = output_folder / f"{OUTPUT_BASENAME}.sav"

    processed_subjects = _load_processed_subjects(output_folder)
    existing_df: pd.DataFrame | None = None

    if skip_existing and csv_path.is_file():
        try:
            existing_df = pd.read_csv(csv_path, dtype={"Subject_ID": str})
        except (OSError, pd.errors.ParserError) as error:
            logger.warning(
                "Could not read existing %s (%s) -- reprocessing everyone",
                csv_path,
                error,
            )

    subject_ids = find_spiral_subject_ids(input_folder)
    out_file_parts: list[pd.DataFrame] = []

    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=len(subject_ids))

        for index, subject_id in enumerate(subject_ids, start=1):
            progress.update(
                task,
                description=f"Processing subject {subject_id}",
                advance=1,
            )

            if progress_callback is not None:
                progress_callback(index, len(subject_ids), subject_id)

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

            vrlab_logging.log_section(logger, f"Subject {subject_id}")

            try:
                pipeline_output = run_pipeline(
                    participant_id_in=subject_id,
                    data_folder_in=input_folder,
                    output_folder_in=output_folder,
                )
            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Skipping subject %s because Spiral processing failed: %s",
                    subject_id,
                    error,
                )
                continue

            participant_data = pipeline_output.subject_df_out.reset_index(drop=True)
            if participant_data.empty:
                logger.warning("No participant output for subject %s", subject_id)
                continue

            out_file_parts.append(participant_data)
            processed_subjects[subject_id] = datetime.now().strftime("%Y-%m-%d %H:%M")

            for figure_label, figure in pipeline_output.figure_data_out.items():
                try:
                    save_plot(
                        figure,
                        output_folder,
                        subject_id,
                        f"Subject {subject_id} - {figure_label}",
                    )
                finally:
                    plt.close(figure)

            logger.info("Done Spiral pipeline for subject %s", subject_id)

    _save_processed_subjects(output_folder, processed_subjects)

    if not out_file_parts:
        logger.warning("No files were successfully processed.")
        return None

    output_df = pd.concat(out_file_parts, axis=0, ignore_index=True)
    output_df = clean_final_output(output_df)

    try:
        validated = build_spiral_participant_output_schema().validate(output_df)
    except pa.errors.SchemaError as error:
        logger.error(
            "Error validating final output file: %s",
            error.failure_cases.to_string(index=False),
        )
        raise

    output_df.to_csv(csv_path, index=False)

    pyreadstat.write_sav(
        validated,
        str(sav_path),
        variable_format={"Subject_ID": "A20"},
        variable_measure={"Subject_ID": "nominal"},
    )

    logger.info("Saved Spiral output to %s and %s", csv_path, sav_path)
    return csv_path


@click.command()
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "input_folder",
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    required=True,
)
@click.argument(
    "output_folder",
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    required=True,
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
def main(input_folder: Path, output_folder: Path, verbose: bool, rerun: bool) -> None:
    """Batch-process Spiral data from a crosschecked BIDS folder."""
    del verbose

    if paths_conflict(input_folder, output_folder):
        raise click.UsageError(
            "output_folder can't be the same as (or contain, or be contained by) "
            "input_folder -- pick a separate folder for processing output."
        )
    if is_effectively_empty_folder(input_folder):
        raise click.UsageError(f"{input_folder} is empty. Run the Spiral BIDS crosscheck first.")
    if not is_bids_like_folder(input_folder):
        raise click.UsageError(
            f"{input_folder} doesn't look like a BIDS folder (no sub-* subject folders "
            "found) -- input_folder must be a BIDS-formatted folder."
        )

    run_batch(
        input_folder,
        output_folder,
        skip_existing=not rerun,
    )


if __name__ == "__main__":
    main()
