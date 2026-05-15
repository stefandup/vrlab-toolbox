import logging
import click
from mooi_toolbox import mobi_logging

from mooi_toolbox.qc.crane_behav_qc import qc_pipeline

logger = logging.getLogger(__name__)

@click.command()
@click.argument("csv_output_file", type=click.Path(exists=True, dir_okay=False), required=True)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(csv_output_file: str, verbose: bool):
    """CLI tool for summarising VRLab crane batch output data."""
    logger.info("Reading CSV output file: %s", csv_output_file)

    if verbose:
        logger.info("Verbose output enabled")

    # TODO: Add summary data processing here.
    qc_pipeline()
    
if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
