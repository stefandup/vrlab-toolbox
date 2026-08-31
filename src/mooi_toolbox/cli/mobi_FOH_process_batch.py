import logging
import os
from pathlib import Path

import click
import matplotlib.pyplot as plt
import pandas as pd
import pyreadstat
from rich.progress import Progress

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing import lsl
from mooi_toolbox.processing.foh_pipeline import run_pipeline
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
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(input_folder: Path, output_folder: Path, verbose: bool):
    """CLI tool for processing and plotting MOBI LSL data for FOH VR task"""

    logger.info(f"Looking into input folder: {input_folder}. Output folder: {output_folder}")

    out_fn = os.path.join(output_folder, "FOH_process_batch_out")

    root = input_folder
    out_file_parts = []
    xdf_fns = list(root.rglob("*.xdf"))
    with Progress() as progress:
        task = progress.add_task("Processing subjects", total=len(xdf_fns))

        for xdf_fn in xdf_fns:
            subject_id = lsl.get_subject_id(xdf_fn)

            progress.update(
                task,
                description=f"Processing subject {subject_id}",
                advance=1,
            )

            mobi_logging.log_section(logger, f"Subject {subject_id}")
            try:
                pipeline_output = run_pipeline(subject_id, input_folder, output_folder)
                participant_data_out = pipeline_output.subject_df_out
                # TODO: import and merge the subjective stress measure for this subject
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

                out_file_parts.append(participant_data_out)
                logger.info(f"Done FOH pipeline for subject {subject_id}")
            # TODO Exceptions can be narrowed here
            except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
                logger.warning(
                    "Skipping subject %s because processing failed: %s", subject_id, error
                )
                continue
    # TODO TEST
    if len(out_file_parts) == 0:
        logger.warning("No files were successfully processed.")
        return

    out_df = pd.concat(out_file_parts, axis=0)
    out_df.to_csv(out_fn + ".csv", index=False)

    pyreadstat.write_sav(
        out_df,
        out_fn + ".sav",
        variable_format={"Subject_ID": "A20"},
        variable_measure={"Subject_ID": "nominal"},
    )

    logger.info(f"Saved output to {out_fn}")


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
