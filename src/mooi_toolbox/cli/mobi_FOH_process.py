import click
import logging
from pathlib import Path
import os

from mooi_toolbox.processing.foh_pipeline import run_pipeline as run_foh_pipeline
from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import mobi_logging
from mooi_toolbox.processing.plot_utils import save_plot

@click.command()
@click.argument("xdf_fn", type=click.Path(exists=True,dir_okay=True),required=False)
@click.argument("output_folder",type=click.Path(exists=True,dir_okay=True),required=False)
@click.option("--verbose",is_flag=True,help="Give verbose output")
@click.option("--show-plots",is_flag=True,help="Show complete plots. Default is to save plots.")
def main(xdf_fn : str,output_folder : str,verbose : bool,show_plots : bool):
    
    if not output_folder:
        output_folder = os.path.join(Path(xdf_fn).resolve().parents[3],'_out')

    if not os.path.exists(output_folder):
        os.mkdir(output_folder)

    subject_id = xdf_io.get_subject_id(xdf_fn)

    logging.info(f"Starting FOH pipeline for subject {subject_id}")

    print("Running mobi FOH pipeline...")
    participant_data_out,fig = run_foh_pipeline(xdf_fn,verbose,show_plots)
    
    try:
        save_plot(fig,output_folder,subject_id,plot_label=f"Subject {subject_id} QC")
    except AttributeError as e:
        logging.info("Error saving plot.%s",e)

    logging.info(f"FOH pipeline done for subject {subject_id}")

    return participant_data_out

if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
