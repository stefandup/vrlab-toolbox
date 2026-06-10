import click
import logging
import os

from mooi_toolbox.processing.crane_pipeline import run_pipeline as run_crane_pipeline
from mooi_toolbox.processing.crane_pipeline import CranePipelineInput
from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import biopac
from mooi_toolbox.processing.plot_utils import save_plot

logger = logging.getLogger(__name__)

@click.command()
@click.argument("biopac_mat_fn", type=click.Path(exists=True,dir_okay=True),required=True)
@click.argument("output_folder",type=click.Path(exists=True,dir_okay=True),required=True)
@click.argument("behav_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.option("--verbose",is_flag=True,help="Give verbose output")
@click.option("--show-plots",is_flag=True,help="Show complete plots. Default is to save plots.")

def main(biopac_mat_fn  : str , behav_folder: str , output_folder : str,verbose : bool,show_plots : bool):
    """Handles one individuals CLI crane behaviour and physiology data processing"""

    if not os.path.exists(output_folder):
        os.mkdir(output_folder)

    subject_id = biopac.get_subject_id_from_mat(biopac_mat_fn)

    logger.info("Looking at subject %s",subject_id)
    pipeline_input = CranePipelineInput(
                subject_id=subject_id,
                biopac_fn=biopac_mat_fn,
                behav_folder=behav_folder,
                verbose=verbose,
                show_plots=False
                )
    
    pipeline_output = run_crane_pipeline(pipeline_input)
    participant_data_out = pipeline_output.subject_df_out
    fig = pipeline_output.figure_data_out
    
    print(participant_data_out)
    save_plot(fig,output_folder,subject_id,f"Subject {subject_id} QC")

if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()

