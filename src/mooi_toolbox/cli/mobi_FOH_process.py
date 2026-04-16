import click
import logging

from mooi_toolbox.processing.foh_pipeline import run_pipeline as run_foh_pipeline
from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import mobi_logging

@click.command()
@click.argument("xdf_fn", type=click.Path(exists=True,dir_okay=True),required=False)
@click.option("--verbose",is_flag=True,help="Give verbose output")
@click.option("--show-plots",is_flag=True,help="Show complete plots. Default is to save plots.")
def main(xdf_fn,verbose,show_plots):
    
    mobi_logging.init(__file__)
    
    subject_id = xdf_io.get_subject_id(xdf_fn)

    logging.info(f"Starting FOH pipeline for subject {subject_id}")

    print("Running mobi FOH pipeline...")
    participant_data_out = run_foh_pipeline(xdf_fn,verbose,show_plots)

    logging.info(f"FOH pipeline done for subject {subject_id}")

    return participant_data_out

if __name__ == "__main__":
    main()
