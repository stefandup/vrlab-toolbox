
from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import config as cfg

def get_event_time(df_in,col_id = "VR_trial",event_id = "RaiseSafetyPlatform"):
    return df_in["time_stamps"][df_in[col_id] == event_id].iloc[0]

def create_intervals(vr_markers_df,VR_trial_events_df):
    
    event_sources = {
        "VR_markers" : vr_markers_df,
        "VR_trial_events" : VR_trial_events_df
    }

    vr_intervals = {}

    for interval_name , interval_events in cfg.get_vr_intervals().items():
        start_event = interval_events["start"]
        end_event = interval_events["end"]

        start_time = get_event_time(
            event_sources[start_event["stream"]],
            start_event["column"],
            start_event["event"])

        end_time = get_event_time(
            event_sources[end_event["stream"]],
            end_event["column"],
            end_event["event"])

        vr_intervals.update({interval_name: (start_time, end_time)})
        
    return vr_intervals      

def slice_data_frame(dataframe_in,vr_intervals):

    df_dict_out = {}

    for key,start_end in vr_intervals.items():
        print(f"Interval {key}: {start_end}. Data type: {type(start_end)}")
        df_dict_out.update({f"{key}" : xdf_io.cut_df_per_interval(start_end,dataframe_in)})

    return df_dict_out
