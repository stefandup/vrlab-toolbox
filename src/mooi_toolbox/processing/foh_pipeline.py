import pandas as pd

from mooi_toolbox import config as cfg
from mooi_toolbox import read_mobi_xdf as xdf
from . import eda
from . import foh_target_processing as tp
from . import vr_intervals as vri

from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf

def run_pipeline(xdf_fn,verbose,show_plots):

    if not xdf_fn:
        streams = get_and_check_xdf(cfg.get_default_xdf(),verbose=verbose)
    else:
        streams = get_and_check_xdf(xdf_fn,verbose=verbose)

    participant_data_out = []

    FOH_dfs = xdf.gather_xdf_data_streams(streams,['OpenSignals','VR_markers','VR_trial_events','FOH_target'])

    eda_out = eda.run_eda_processing(FOH_dfs['OpenSignals'][cfg.get_eda_data_label()])

    eda.plot_eda(eda_out,interval_label='Complete',show_plots=show_plots)

    eda_data_out = eda.get_eda_data_out(eda_out,interval_label='')

    participant_data_out.append(eda_data_out)
    
    vr_intervals = vri.create_intervals(FOH_dfs['VR_markers'],FOH_dfs['VR_trial_events'])

    biosignals_dfs_dict = vri.slice_data_frame(FOH_dfs['OpenSignals'],vr_intervals)

    eda_parts = []

    for key,biosignal_df in biosignals_dfs_dict.items():
        eda_info_out = eda.run_eda_processing(biosignal_df[cfg.get_eda_data_label()])
        #TODO: Better label for data out
        eda_data_out = eda.get_eda_data_out(eda_info_out,interval_label=f'{key}_')
        eda_parts.append(eda_data_out)

    #List to df
    eda_df_out = pd.concat(eda_parts, axis=1)
    participant_data_out.append(eda_df_out)

    target_data_out,_ = tp.run_processing(FOH_dfs['FOH_target'],vr_intervals)
    participant_data_out.append(target_data_out)

    return participant_data_out
