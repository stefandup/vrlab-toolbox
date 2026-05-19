import pandas as pd
from matplotlib.figure import Figure
import logging

from mooi_toolbox.processing import biopac
from mooi_toolbox import config as cfg
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.vr_intervals import get_trigger_intervals
from mooi_toolbox.processing.vr_intervals import match_behav_intervals_with_trigger_intervals
from mooi_toolbox.processing import crane_behaviour_processing as cbp
from mooi_toolbox.processing import crane_debrief_data as debrief

logger = logging.getLogger(__name__)

def run_pipeline(subject_id : str,biopac_fn : str,behav_folder : str,verbose : bool = False,show_plots : bool = False) -> tuple[pd.DataFrame,Figure]:
    
    fig : Figure = None

    try:
        eda_raw_timestamped : pd.DataFrame = biopac.load_biopac_data(biopac_fn,cfg.get_biopac_eda_data_label())
    except ValueError as e:
        logger.warning("Error loading biopac eda data. %s",e)
        raise

    participant_data_out = []
            
    try:
        behav_data_out,validated_behav_df = cbp.main(subject_id,behav_folder)
        behav_data_out.insert(0,"Subject_ID",subject_id)
        behav_data_out = behav_data_out.reset_index(drop=True)
        participant_data_out.append(behav_data_out)
        logger.info("Processed behav data for subject %s",subject_id)

    except ValueError as e:
        logger.warning("Skipping behaviour analysis on %s. %s",subject_id,e)

    try:
        debrief_data_out = debrief.main(subject_id,behav_folder)
        debrief_data_out = debrief_data_out.reset_index(drop=True)
        participant_data_out.append(debrief_data_out)

        logger.info("Processed debrief data for subject %s",subject_id)

    except ValueError as e:
        logger.warning("Skipping debrief analysis on %s. %s",subject_id,e)
    

    # Do QC

    vr_intervals = get_trigger_intervals(biopac.load_biopac_data(biopac_fn,'Trigger'))
    scr_df_out = eda.run_eda_intervals(eda_raw_timestamped,vr_intervals)
    
    # Do labeled Physiology
    try:
        labeled_vr_intervals = match_behav_intervals_with_trigger_intervals(vr_intervals,validated_behav_df)
        scr_interval_df_out = eda.run_eda_intervals(eda_raw_timestamped,labeled_vr_intervals)
        scr_interval_df_out = scr_interval_df_out.reset_index(drop=True)
        fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,labeled_vr_intervals)
        participant_data_out.append(scr_interval_df_out)
    except ValueError as e:
            logger.warning("Skipping physiology analysis on %s. %s",subject_id,e)

    if fig is None:
        fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,vr_intervals)

    if len(participant_data_out) != 0:
        # Concatenate row wise
        return (pd.concat(participant_data_out, axis = 1),fig)
    else:
        return (pd.DataFrame(),None)