import logging
from pathlib import Path

import click

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.crane_redcap import clean_crane_redcap_data
from vrlab_toolbox.processing.redcap import get_token, pull_report

logger = logging.getLogger(__name__)


@click.command()
@click.argument(
    "output_folder",
    type=click.Path(exists=True, dir_okay=True, path_type=Path),
    required=True,
)
def main(output_folder: Path):
    """Pull the REDCap report and save it locally."""
    logger.info("Pulling REDCap report")

    token = get_token()
    df = pull_report(token)

    df = clean_crane_redcap_data(df)

    out_file = output_folder / "Get_all_data.csv"
    df.to_csv(out_file, index=False)

    logger.info("Downloaded %s rows and %s columns", len(df), len(df.columns))
    logger.info("Saved REDCap data to %s", out_file)


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
