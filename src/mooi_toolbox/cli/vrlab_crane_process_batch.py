import click
import logging
import os
from pathlib import Path
import pandas as pd
import pyreadstat
from rich.progress import Progress

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import biopac
from mooi_toolbox.processing.crane_pipeline import run_pipeline as run_crane_pipeline
from mooi_toolbox.processing.plot_utils import save_plot
from mooi_toolbox.processing import crane_behaviour_processing as cbp
from mooi_toolbox.processing import crane_debrief_data as debrief

logger = logging.getLogger(__name__)

def get_id_from_mat(mat_fn : str)-> str:
    return mat_fn.split('_')[1]

@click.command()
@click.argument("input_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.argument("behav_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.argument("output_folder", type=click.Path(exists=True, dir_okay=True), required=False)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: str, behav_folder: str ,output_folder: str, verbose: bool):
    """CLI tool for batch processing VRLab crane behaviour and physiology data."""
    
    #TODO: Empty DF out needs to give a warning.
    
    if not output_folder:
        output_folder = input_folder + "_out"

    if not os.path.exists(output_folder):
        os.mkdir(output_folder)

    logger.info("Looking into input folder: %s. Output folder: %s", input_folder, output_folder)

    out_fn = os.path.join(output_folder, "vrlab_crane_process_batch_out.csv")
    behav_fn = os.path.join(output_folder,"vrlab_crane_process_batch_behav_out")

    root = Path(input_folder)
    out_file_parts = []
    behav_out_parts = []

    subject_mat_files = list(root.rglob("*.mat"))
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
            logger.info("Trying to read file %s",biopac_mat_fn)
            try:
                participant_data_out, fig = run_crane_pipeline(
                    biopac_mat_fn,
                    verbose=verbose,
                    show_plots=False,
                )

                try:
                    save_plot(fig, output_folder, subject_id, f"Subject {subject_id} QC")
                    # TODO: This causes issues: need to matplotlib.use("Agg") or similar
                    #plt.close(fig)
                except AttributeError as error:
                    logger.info("Error saving plot.%s", error)

                if participant_data_out.empty:
                    logger.warning("No participant output for subject %s", subject_id)
                    continue

                participant_data_out = participant_data_out.reset_index(drop=True)
                participant_data_out.insert(0, "Subject_ID", subject_id)

                out_file_parts.append(participant_data_out)
                logger.info("Done crane pipeline for subject %s", subject_id)

            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning("Skipping subject %s because processing failed: %s", subject_id, error)
                continue

            try:
                behav_data_out = cbp.main(subject_id,behav_folder)
                behav_data_out.insert(0,"Subject_ID",subject_id)
                behav_out_parts.append(behav_data_out)

                logger.info("Processed behav data for subject %s",behav_fn)

            except ValueError as e:
                logger.warning("Skipping behaviour analysis on %s. %s",subject_id,e)

            try:
                debrief_data_out = debrief.main(subject_id,behav_folder)
                behav_out_parts.append(debrief_data_out)
                logger.info("Processed debrief data for subject %s",subject_id)

            except ValueError as e:
                logger.warning("Skipping debrief analysis on %s. %s",subject_id,e)

    behav_df_out = pd.concat(behav_out_parts,axis=0)
    behav_df_out.to_csv(behav_fn + ".csv")
    # TODO: Do data labels for SPSS out
    pyreadstat.write_sav(behav_df_out,behav_fn + ".sav")

    out_df = pd.concat(out_file_parts, axis=0)
    out_df.to_csv(out_fn)

    logger.info("Saved output to %s", out_fn)

if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
