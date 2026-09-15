from __future__ import annotations

import logging
from pathlib import Path

import click
import matplotlib.pyplot as plt
import pandas as pd
from rich.progress import Progress

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.graphomotor_pipeline import run_pipeline
from vrlab_toolbox.processing.graphomotor_xdf import find_subject_ids
from vrlab_toolbox.processing.plot_utils import save_plot
from vrlab_toolbox.processing.spiral import SpiralTaskProcessor

logger = logging.getLogger(__name__)


def remove_unwanted_old_pngs(
    subject_folder: Path,
    subject_id: str,
) -> None:
    """Remove figures produced by older Spiral versions."""

    unwanted_names = (
        f"{subject_id}_selected_stream_sample_counts.png",
        f"{subject_id}_pen_spiral_xy.png",
        f"{subject_id}_neon_gaze_xy.png",
    )

    for filename in unwanted_names:
        path = subject_folder / filename

        try:
            path.unlink()
        except FileNotFoundError:
            continue


def remove_legacy_csvs(output_folder: Path) -> None:
    """Remove CSVs produced by the older three-file Spiral output."""

    legacy_files = (
        "spiral_all_xdf_candidates.csv",
        "spiral_selected_xdf_summary.csv",
        "spiral_selected_processing_out.csv",
    )

    for filename in legacy_files:
        path = output_folder / filename

        try:
            path.unlink()
        except FileNotFoundError:
            continue


def clean_final_output(output_df: pd.DataFrame) -> pd.DataFrame:
    """Keep only useful participant-level Spiral output columns.

    Selection/debugging information required internally by the pipeline is
    deliberately excluded from the final analysis CSV.
    """

    # Core fields we explicitly want in the final CSV.
    preferred_columns = [
        # Participant / selected recording
        "Subject_ID",
        "XDF_File",
        # Selection QC
        "Selection_Status",
        "Selection_Reason",
        # Spiral drawing
        "Drawing_Detected",
        "Drawing_Window_Duration_sec",
        "Drawing_Active_Duration_sec",
        # EDA / ECG
        "EDA_Present",
        "EDA_Coverage_pct",
        "ECG_Present",
        "ECG_Coverage_pct",
        # Eye tracking
        "Neon_Gaze_Present",
        "Neon_Gaze_Coverage_pct",
        # EEG
        "EEG_Present",
        "EEG_Coverage_pct",
        # Spiral hand switch
        "Switch_Time_sec",
        # C3 motor EEG
        "C3_dominant_alpha",
        "C3_nondominant_alpha",
        "C3_dominant_beta",
        "C3_nondominant_beta",
        # C4 motor EEG
        "C4_dominant_alpha",
        "C4_nondominant_alpha",
        "C4_dominant_beta",
        "C4_nondominant_beta",
    ]

    debug_columns = {
        "Selected_XDF",
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
        # Pen diagnostic fields
        "Pen_Present",
        "Pen_Samples",
        "Pen_Stream_Name",
        "Pen_Stream_Type",
        "Pen_Effective_SRate",
        "Pen_Duration_sec",
        # Neon diagnostic fields
        "Neon_Gaze_Samples",
        "Neon_Gaze_Stream_Name",
        "Neon_Gaze_Stream_Type",
        "Neon_Gaze_Effective_SRate",
        "Neon_Gaze_Duration_sec",
        "Any_Neon_Present",
        "Any_Neon_Samples",
        "Any_Neon_Stream_Name",
        "Any_Neon_Stream_Type",
        # EEG diagnostic fields
        "EEG_Samples",
        "EEG_Stream_Name",
        "EEG_Stream_Type",
        "EEG_Effective_SRate",
        "EEG_Duration_sec",
        # EDA / ECG diagnostic fields
        "EDA_Samples",
        "EDA_Stream_Name",
        "ECG_Samples",
        "ECG_Stream_Name",
        # Generic XDF diagnostics
        "Total_Streams",
        "Total_NonEmpty_Streams",
        "Total_Samples_All_Streams",
    }

    final_columns = [column for column in preferred_columns if column in output_df.columns]

    additional_processed_columns = [
        column
        for column in output_df.columns
        if column not in final_columns and column not in debug_columns
    ]

    final_columns += additional_processed_columns

    # Protect against duplicate column names.
    final_columns = list(dict.fromkeys(final_columns))

    return output_df.loc[:, final_columns].copy()


@click.command()
@click.argument(
    "input_folder",
    type=click.Path(
        exists=True,
        file_okay=False,
        path_type=Path,
    ),
    required=True,
)
@click.argument(
    "output_folder",
    type=click.Path(
        exists=True,
        file_okay=False,
        path_type=Path,
    ),
    required=True,
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Give verbose output.",
)
@click.option(
    "--skip-heavy-processing",
    is_flag=True,
    help=("Only make stream/QC summaries and PNGs; skip EDA/EEG processing."),
)
def main(
    input_folder: Path,
    output_folder: Path,
    verbose: bool,
    skip_heavy_processing: bool,
):
    """Batch-process the Spiral graphomotor task."""

    logger.info(
        "Looking into input folder: %s",
        input_folder,
    )
    logger.info(
        "Output folder: %s",
        output_folder,
    )

    remove_legacy_csvs(output_folder)

    subject_ids = find_subject_ids(input_folder)

    if not subject_ids:
        logger.warning(
            "No XDF files found under %s.",
            input_folder,
        )
        return

    participant_parts: list[pd.DataFrame] = []

    task_processor = SpiralTaskProcessor()

    with Progress() as progress:
        task = progress.add_task(
            "Processing subjects",
            total=len(subject_ids),
        )

        for subject_id in subject_ids:
            progress.update(
                task,
                description=f"Processing subject {subject_id}",
                advance=1,
            )

            vrlab_logging.log_section(
                logger,
                f"Subject {subject_id}",
            )

            try:
                pipeline_output = run_pipeline(
                    participant_id_in=subject_id,
                    data_folder_in=input_folder,
                    output_folder_in=output_folder,
                    task_processor=task_processor,
                    skip_heavy_processing=skip_heavy_processing,
                    verbose=verbose,
                )

            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
            ) as error:
                logger.warning(
                    "Skipping subject %s because Spiral processing failed: %s",
                    subject_id,
                    error,
                )

                continue

            if pipeline_output.selected_df_out.empty:
                logger.warning(
                    "No selected XDF output for %s.",
                    subject_id,
                )

                continue

            participant_df = pipeline_output.selected_df_out.reset_index(drop=True).copy()

            if not pipeline_output.processing_df_out.empty:
                processing_df = pipeline_output.processing_df_out.reset_index(drop=True).copy()

                # Already contained in the selected dataframe.
                processing_df = processing_df.drop(
                    columns=[
                        "Subject_ID",
                        "XDF_File",
                    ],
                    errors="ignore",
                )

                participant_df = pd.concat(
                    [
                        participant_df,
                        processing_df,
                    ],
                    axis=1,
                )

            participant_parts.append(participant_df)

            subject_output_folder = output_folder / subject_id

            subject_output_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            remove_unwanted_old_pngs(
                subject_output_folder,
                subject_id,
            )

            for (
                figure_label,
                figure,
            ) in pipeline_output.figure_data_out.items():
                try:
                    save_plot(
                        figure,
                        subject_output_folder,
                        subject_id,
                        figure_label,
                    )

                finally:
                    plt.close(figure)

            if verbose:
                selected_row = pipeline_output.selected_df_out.iloc[0]

                logger.info(
                    "Selected XDF: %s",
                    selected_row.get(
                        "XDF_File",
                        "",
                    ),
                )

                logger.info(
                    "Selection status: %s",
                    selected_row.get(
                        "Selection_Status",
                        "",
                    ),
                )

                logger.info(
                    "Selection reason: %s",
                    selected_row.get(
                        "Selection_Reason",
                        "",
                    ),
                )

                logger.info(
                    "Drawing window: %.1f sec",
                    float(
                        selected_row.get(
                            "Drawing_Window_Duration_sec",
                            0,
                        )
                        or 0
                    ),
                )

                logger.info(
                    "Active drawing: %.1f sec",
                    float(
                        selected_row.get(
                            "Drawing_Active_Duration_sec",
                            0,
                        )
                        or 0
                    ),
                )

                logger.info(
                    ("Coverage: EDA %.1f%% | ECG %.1f%% | Neon %.1f%% | EEG %.1f%%"),
                    float(
                        selected_row.get(
                            "EDA_Coverage_pct",
                            0,
                        )
                        or 0
                    ),
                    float(
                        selected_row.get(
                            "ECG_Coverage_pct",
                            0,
                        )
                        or 0
                    ),
                    float(
                        selected_row.get(
                            "Neon_Gaze_Coverage_pct",
                            0,
                        )
                        or 0
                    ),
                    float(
                        selected_row.get(
                            "EEG_Coverage_pct",
                            0,
                        )
                        or 0
                    ),
                )

    if not participant_parts:
        logger.warning("No participant output was produced.")

        return

    output_df = pd.concat(
        participant_parts,
        axis=0,
        ignore_index=True,
    )

    output_df = clean_final_output(output_df)

    out_fn = output_folder / "spiral_process_batch_out.csv"

    output_df.to_csv(
        out_fn,
        index=False,
    )

    logger.info(
        "Saved Spiral batch output to %s",
        out_fn,
    )

    logger.info(
        "Final CSV contains %d participants and %d columns.",
        len(output_df),
        len(output_df.columns),
    )


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
