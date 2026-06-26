import click
import logging
import os
from pathlib import Path
import pandas as pd
import pyreadstat
from rich.progress import Progress
import pandera.pandas as pa

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import biopac
from mooi_toolbox.processing.crane_pipeline import run_pipeline as run_crane_pipeline
from mooi_toolbox.processing.crane_pipeline import validate_participant_output
from mooi_toolbox.processing.input_data import PipelineInput
from mooi_toolbox.processing.plot_utils import save_plot

logger = logging.getLogger(__name__)

@click.command()
@click.argument("input_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.argument("behav_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.argument("output_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.option("--subject_id", required=False, default="" ,help="Process a single participant")
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: str, behav_folder: str ,output_folder: str, verbose: bool, subject_id : str):
    """CLI tool for batch processing VRLab crane behaviour and physiology data."""
    
    participant_data_out = None
    fig=None

    logger.info("Looking into input folder: %s. Output folder: %s", input_folder, output_folder)

    data_out_fn = os.path.join(output_folder,f"{subject_id}vrlab_crane_process_batch_data_out")

    root = Path(input_folder)
    out_file_parts = []

    subject_mat_files = list(root.rglob(f"*{subject_id}_CraneOut.mat"))

    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=len(subject_mat_files))
        
        for biopac_mat_fn in subject_mat_files:
            #TODO: fix str to path
            subject_id = biopac.get_subject_id_from_mat(str(biopac_mat_fn))

            progress.update(
                        task,
                        description=f"Processing subject {subject_id}",
                        advance=1,
                    )

            mobi_logging.log_section(logger, f"Subject {subject_id}")
            logger.info("Trying to read file %s",biopac_mat_fn)


            #TODO: Fix fn to path
            pipeline_input = PipelineInput(
                subject_id=subject_id,
                biopac_fn=str(biopac_mat_fn),
                behav_folder=behav_folder,
                verbose=verbose,
                show_plots=False
                )

            try:
                pipeline_output = run_crane_pipeline(pipeline_input)
                participant_data_out = pipeline_output.subject_df_out
                fig = pipeline_output.figure_data_out

                if fig is not None:
                        try:
                            save_plot(fig, output_folder, subject_id, f"Subject {subject_id} QC")
                        finally:
                            plt.close(fig)
                        # TODO: This causes issues: need to matplotlib.use("Agg") or similar
                        #plt.close(fig)
                else:
                    logger.info("Error saving plot for %s", subject_id)

                if participant_data_out.empty:
                    logger.warning("No participant output for subject %s", subject_id)
                    continue

                participant_data_out = participant_data_out.reset_index(drop=True)
                #participant_data_out.insert(0, "Subject_ID", subject_id)

                out_file_parts.append(participant_data_out)
                logger.info("Done crane pipeline for subject %s", subject_id)

            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning("Skipping subject %s because processing failed: %s", subject_id, error)
                continue

    participant_df_out = pd.concat(out_file_parts,axis=0)
    
    try:
       participant_df_out_validated = validate_participant_output(participant_df_out)    
    except pa.errors.SchemaErrors as e:
        logger.error("Error validating final output file: %s",e.failure_cases.to_string(index=False))
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
    mobi_logging.init(__file__)
    main()
