from mooi_toolbox import config as cfg
from mooi_toolbox import read_mobi_xdf as xdf
from . import eda
from . import foh_target_processing as tp
from . import vr_intervals as vri

from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf

import pandas as pd
import logging
    
logger = logging.getLogger(__name__)

def run_foh_eda_qc(opensignals_df):
    '''Runs optional QC which includes plotting the whole timeseries and outputting basic info'''
    # TODO: Include multiple info runs here.
    eda_info_out = eda.run_eda_processing(opensignals_df[cfg.get_eda_data_label()])
    eda_data_out = eda.get_eda_data_out(eda_info_out,interval_label='')
    eda.plot_eda(eda_data_out)

def run_foh_eda_pipeline(opensignals_df,vr_intervals,show_plots=False):

    biosignals_dfs_dict = vri.slice_data_frame(opensignals_df,vr_intervals)
    eda_parts = []

    for key,biosignal_df in biosignals_dfs_dict.items():
        try:
            eda_info_out = eda.run_eda_processing(biosignal_df[cfg.get_eda_data_label()])
            eda_data_out = eda.get_eda_data_out(eda_info_out,interval_label=f'{key}_')
            eda_parts.append(eda_data_out)
        except eda.EDAProcessingError:
            logger.warning("Skipping EDA for interval %s", key)
            continue

    return pd.concat(eda_parts, axis=1)

def has_missing_requirements(missing,required):
    return any(stream in missing for stream in required)

def run_foh_ecg_pipeline(opensignals_df,vr_intervals,show_plots=False):
    return pd.DataFrame()

def run_pipeline(xdf_fn,verbose,show_plots):

    if not xdf_fn:
        streams = get_and_check_xdf(cfg.get_default_xdf(),verbose=verbose)
    else:
        streams = get_and_check_xdf(xdf_fn,verbose=verbose)

    participant_data_out = []
    vr_intervals = None

    streams_to_get = ['OpenSignals','VR_markers','VR_trial_events','FOH_target']

    FOH_dfs = xdf.gather_xdf_data_streams(streams,streams_to_get)

    missing_streams = set(streams_to_get) - set(FOH_dfs)
    if missing_streams:
        print(f"Missing streams: {missing_streams}")
    else:
        print("No missing streams")

    if has_missing_requirements(missing_streams,['VR_markers','VR_trial_events']):
        logger.warning("No trial info found in xdf. Cannot create intervals")
    else:
        try:
            vr_intervals = vri.create_intervals(FOH_dfs['VR_markers'],FOH_dfs['VR_trial_events'])
        except KeyError as e:
            logger.warning("%s",e)


    # Biosignals QC

    if has_missing_requirements(missing_streams,['OpenSignals']):
        logger.warning("Missing physiology data. Cannot run QC.")
    else:
        run_foh_eda_qc(FOH_dfs['OpenSignals'])

    if vr_intervals is None:
        return pd.DataFrame()

    # Biosignals processing 
    if has_missing_requirements(missing_streams,['OpenSignals','VR_markers','VR_trial_events']):
        logger.warning("Skipping ECG and EDA because required streams are missing: %s", missing_streams)
    else:
        try:
            eda_df_out = run_foh_eda_pipeline(FOH_dfs['OpenSignals'],vr_intervals)
            participant_data_out.append(eda_df_out)

        except eda.EDAProcessingError as e:
            logger.exception("EDA failed to process")
            logger.warning("%s",e)

        try: 
            ecg_df_out = run_foh_ecg_pipeline(FOH_dfs['OpenSignals'],vr_intervals)
            participant_data_out.append(ecg_df_out)
        except eda.ECGProcessingError as e:
            logger.exception("ECG failed to process")
            logger.warning("%s",e)

    # behaviour processing
    if has_missing_requirements(missing_streams,['FOH_target','VR_markers','VR_trial_events']):
        logger.warning("Skipping target behaviour as there are none recorded")
    else:
        try:
            target_data_out,_ = tp.run_processing(FOH_dfs['FOH_target'],vr_intervals)
            participant_data_out.append(target_data_out)
        except tp.TPProcessingError as e:
            logger.warning("Skipping target behaviour as there was a processing error")
            logger.warning("%s",e)
    if len(participant_data_out) != 0:
        return pd.concat(participant_data_out, axis = 1)
    else:
        return pd.DataFrame()