import pandas as pd
from matplotlib.figure import Figure
import logging

from mooi_toolbox.processing import biopac
from mooi_toolbox import config as cfg
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.vr_intervals import get_trigger_intervals

logger = logging.getLogger(__name__)

def run_pipeline(biopac_fn : str,verbose : bool = False,show_plots : bool = False) -> tuple[pd.DataFrame,Figure]:
    
    fig : Figure = None

    try:
        eda_raw_timestamped : pd.DataFrame = biopac.load_biopac_data(biopac_fn,cfg.get_biopac_eda_data_label())
    except ValueError as e:
        logger.warning("Error loading biopac eda data. %s",e)
        raise

    vr_intervals = get_trigger_intervals(biopac.load_biopac_data(biopac_fn,'Trigger'))

    scr_df_out = eda.run_eda_intervals(eda_raw_timestamped,vr_intervals)
    fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,vr_intervals)

    return tuple([scr_df_out,fig])