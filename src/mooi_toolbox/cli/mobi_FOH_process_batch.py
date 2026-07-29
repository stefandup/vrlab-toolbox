import logging
import os
from pathlib import Path

import click
import pandas as pd

from mooi_toolbox import mobi_logging
from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf
from mooi_toolbox.processing.foh_pipeline import run_lsl_pipeline as run_lsl_foh_pipeline
from mooi_toolbox.processing.plot_utils import save_plot
from mooi_toolbox.read_mobi_xdf import xdf_io

logger = logging.getLogger(__name__)


@click.command()
@click.argument("input_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.argument("output_folder", type=click.Path(exists=True, dir_okay=True), required=True)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder, output_folder, verbose):
    """CLI tool for processing and plotting MOBI LSL data for FOH VR task"""

    logger.info(f"Looking into input folder: {input_folder}. Output folder: {output_folder}")

    out_fn = os.path.join(output_folder, "FOH_process_batch_out.csv")

    root = Path(input_folder)
    out_file_parts = []

    for xdf_fn in root.rglob("*.xdf"):
        subject_id = xdf_io.get_subject_id(xdf_fn)
        # hier updated
        try:
            streams = get_and_check_xdf(xdf_fn, verbose=False)
        except Exception as error:
            logger.warning("Skipping %s because XDF could not be loaded: %s", xdf_fn.name, error)
            continue

        streams_to_get = ["FOH_target", "VR_trial_events", "VR_markers"]

        found_counts = {}

        for stream in streams:
            name = stream["info"]["name"][0]

            if name in streams_to_get:
                found_counts[name] = len(stream["time_series"])

        has_foh_markers = (
            found_counts.get("FOH_target", 0) > 0
            and found_counts.get("VR_trial_events", 0) > 0
            and found_counts.get("VR_markers", 0) > 0
        )

        if not has_foh_markers:
            logger.info(
                "Skipping %s because it does not contain FOH markers. Counts: %s",
                xdf_fn.name,
                found_counts,
            )
            continue

        mobi_logging.log_section(logger, f"Subject {subject_id}")
        try:
            participant_data_out, fig = run_lsl_foh_pipeline(xdf_fn, verbose, show_plots=False)

            try:
                save_plot(fig, output_folder, subject_id, f"Subject {subject_id} QC")
            except AttributeError as e:
                logger.info("Error saving plot.%s", e)

            if participant_data_out.empty:
                logger.warning("No participant output for subject %s", subject_id)
                continue

            participant_data_out = participant_data_out.reset_index(drop=True)
            participant_data_out.insert(0, "Subject_ID", subject_id)

            out_file_parts.append(participant_data_out)
            logger.info(f"Done FOH pipeline for subject {subject_id}")

        except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
            logger.warning("Skipping subject %s because processing failed: %s", subject_id, error)
            continue

    out_df = pd.concat(out_file_parts, axis=0)
    out_df.to_csv(out_fn)

    logger.info(f"Saved output to {out_fn}")


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
