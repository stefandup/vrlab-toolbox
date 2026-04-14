import click

from mooi_toolbox.processing.foh_pipeline import run_pipeline as run_foh_pipeline

@click.command()
@click.argument("xdf_fn", type=click.Path(exists=True,dir_okay=True),required=False)
@click.option("--verbose",is_flag=True,help="Give verbose output")
@click.option("--show-plots",is_flag=True,help="Show complete plots. Default is to save plots.")
def main(xdf_fn,verbose,show_plots):
    
    print("Running mobi FOH pipeline...")
    participant_data_out = run_foh_pipeline(xdf_fn,verbose,show_plots)
    print(participant_data_out)

if __name__ == "__main__":
    main()
