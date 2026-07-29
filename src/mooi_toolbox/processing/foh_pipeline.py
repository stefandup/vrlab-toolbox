import logging
from pathlib import Path

import pandas as pd
from matplotlib.figure import Figure

from mooi_toolbox import config as cfg
from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf
from mooi_toolbox.processing import lsl as xdf

from . import ecg, eda
from . import foh_target_behaviour as tp
from . import trial_intervals as trial_intervals

logger = logging.getLogger(__name__)


def has_missing_requirements(missing: set, required: list[str]) -> bool:
    return any(stream in missing for stream in required)


def run_lsl_pipeline(
    xdf_fn: Path, verbose: bool, show_plots: bool
) -> tuple[pd.DataFrame, Figure | None]:
    """Run FOH pipeline for LSL EDA, ECG and Behavioural (i.e. Target) data. Tries to be robust wrt missing data."""
    if not xdf_fn:
        streams = get_and_check_xdf(cfg.get_default_xdf(), verbose=verbose)
    else:
        streams = get_and_check_xdf(xdf_fn, verbose=verbose)

    participant_data_out = []
    vr_intervals = None
    fig = None

    streams_to_get = ["OpenSignals", "VR_markers", "VR_trial_events", "FOH_target"]

    FOH_dfs = xdf.gather_xdf_data_streams(streams, streams_to_get)

    missing_streams = set(streams_to_get) - set(FOH_dfs)
    if missing_streams:
        logger.warning(f"Missing streams: {missing_streams}")

    else:
        logger.info("No missing streams")

    # Create intervals

    if has_missing_requirements(missing_streams, ["VR_markers", "VR_trial_events"]):
        logger.warning("No trial info found in xdf. Cannot create intervals")
    else:
        try:
            vr_intervals = trial_intervals.create_lsl_trial_intervals(
                FOH_dfs["VR_markers"], FOH_dfs["VR_trial_events"]
            )
        except KeyError as e:
            logger.warning("%s", e)

    # Biosignals QC

    if has_missing_requirements(missing_streams, ["OpenSignals"]):
        logger.warning("Missing physiology data. Cannot run QC.")
    else:
        eda_raw_timestamped: pd.DataFrame = FOH_dfs["OpenSignals"]
        eda_raw_timestamped = eda_raw_timestamped.rename(
            columns={cfg.get_opensignals_eda_data_label(): "EDA"}
        )
        fig = eda.run_eda_qc(eda_raw_timestamped)

    if vr_intervals is None:
        logger.warning(
            "No intervals present. Cannot proceed with interval based nor behaviour analysis"
        )
        return (pd.DataFrame(), None)

    # Biosignals processing
    if has_missing_requirements(missing_streams, ["OpenSignals", "VR_markers", "VR_trial_events"]):
        logger.warning(
            "Skipping ECG and EDA because required streams are missing: %s", missing_streams
        )
    else:
        try:
            eda_df_out = eda.run_eda_intervals(eda_raw_timestamped, vr_intervals)
            fig = eda.run_eda_qc(
                eda_raw_timestamped, eda_data_out=eda_df_out, vr_intervals=vr_intervals
            )
            participant_data_out.append(eda_df_out)

        except eda.EDAProcessingError as e:
            logger.exception("EDA failed to process")
            logger.warning("%s", e)

        try:
            ecg_df_out = ecg.run_ecg_pipeline(FOH_dfs["OpenSignals"]["ECG1"], vr_intervals)
            participant_data_out.append(ecg_df_out)
        except ecg.ECGProcessingError as e:
            logger.exception("ECG failed to process")
            logger.warning("%s", e)

    # Behaviour processing
    if has_missing_requirements(missing_streams, ["FOH_target", "VR_markers", "VR_trial_events"]):
        logger.warning("Skipping target behaviour as there are none recorded")
    else:
        try:
            target_data_out, _ = tp.run_processing(FOH_dfs["FOH_target"], vr_intervals)
            participant_data_out.append(target_data_out)
        except tp.TPProcessingError as e:
            logger.warning("Skipping target behaviour as there was a processing error")
            logger.warning("%s", e)
    if len(participant_data_out) != 0:
        # Concatenate row wise
        return (pd.concat(participant_data_out, axis=1), fig)
    else:
        return (pd.DataFrame(), None)
