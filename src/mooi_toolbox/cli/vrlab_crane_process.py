import logging
import os
from pathlib import Path

import click
import matplotlib
import pandas as pd
import pandera.pandas as pa
import pyreadstat
from rich.progress import Progress

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import biopac
from mooi_toolbox.processing.crane_pipeline import build_crane_participant_output_schema
from mooi_toolbox.processing.crane_pipeline import run_pipeline as run_crane_pipeline
from mooi_toolbox.processing.plot_utils import save_plot

logger = logging.getLogger(__name__)


@click.command()
@click.version_option(package_name="mooi-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument(
    "output_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.option("--subject_id", required=False, default="", help="Process a single participant")
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: Path, output_folder: Path, verbose: bool, subject_id: str):
    """CLI tool for batch processing VRLab crane behaviour and physiology data.

    `input_folder` must be a BIDS-formatted folder. This assumes the data has
    already been through the crosscheck tool (i.e. vrlab_crane_bids_crosscheck.exe)
    so duplicate runs and id/date corrections are resolved before processing.
    """
    log_folder = Path.joinpath(output_folder, "logs")
    log_folder.mkdir(parents=True, exist_ok=True)
    mobi_logging.init(__file__, log_dir_in=log_folder)
    participant_data_out = None

    logger.info("Looking into input folder: %s. Output folder: %s", input_folder, output_folder)

    data_out_fn = os.path.join(output_folder, f"{subject_id}vrlab_crane_process_batch_data_out")

    root = Path(input_folder)
    out_file_parts = []
    physio_glob_str = "sub-*_task-crane_acq-physiology*_physio.mat"
    subject_mat_files = list(root.rglob(physio_glob_str))

    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=len(subject_mat_files))

        for biopac_mat_fn in subject_mat_files:
            subject_id = biopac.get_subject_id_from_mat(biopac_mat_fn)

            progress.update(
                task,
                description=f"Processing subject {subject_id}",
                advance=1,
            )

            mobi_logging.log_section(logger, f"Subject {subject_id}")
            logger.info("Trying to read file %s", biopac_mat_fn)

            try:
                pipeline_output = run_crane_pipeline(subject_id, input_folder, output_folder)
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
                # participant_data_out.insert(0, "Subject_ID", subject_id)

                out_file_parts.append(participant_data_out)
                logger.info("Done crane pipeline for subject %s", subject_id)

            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Skipping subject %s because processing failed: %s", subject_id, error
                )
                continue
    if out_file_parts is None:
        logger.warning(f"No files found searching for {physio_glob_str}.")
        raise FileNotFoundError

    participant_df_out = pd.concat(out_file_parts, axis=0)

    try:
        participant_df_out_validated = build_crane_participant_output_schema().validate(
            participant_df_out
        )
    except pa.errors.SchemaError as e:
        logger.error(
            "Error validating final output file: %s", e.failure_cases.to_string(index=False)
        )
        raise

    participant_df_out.to_csv(data_out_fn + ".csv")
    # TODO: Do data labels for SPSS out

    logger.info("Successfully validated final output file")

    pyreadstat.write_sav(
        participant_df_out_validated,
        data_out_fn + ".sav",
        variable_format={"Subject_ID": "A20"},
        variable_measure={"Subject_ID": "nominal"},
    )

    logger.info("Saved final SPSS output file to %s", data_out_fn + ".sav")


if __name__ == "__main__":
    main()
