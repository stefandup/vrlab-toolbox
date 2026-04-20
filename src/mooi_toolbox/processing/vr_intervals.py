import logging

from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import config as cfg
    
logger = logging.getLogger(__name__)
class IntervalException(Exception):
    """Raised when error in inverval creation occurs"""

def get_event_time(df_in,col_id = "VR_trial",event_id = "RaiseSafetyPlatform"):
    matches = df_in["time_stamps"][df_in[col_id] == event_id]
    if matches.empty:
        raise IntervalException(f"Can not find {col_id} with id {event_id}")
    
    return matches.iloc[0]

def get_event_time_from_spec(event_sources, event_spec):
    event_time = get_event_time(
        event_sources[event_spec["stream"]],
            event_spec["column"],
            event_spec["event"],
            )
    
    return event_time + event_spec.get("offset_seconds", 0)

def get_event_time_with_fallback(event_sources, primary_event, fallback_event=None):
    
    try:
        return get_event_time_from_spec(event_sources, primary_event)
    except IntervalException:
        if fallback_event is None:
            logger.warning("No fallback event for this!")
            raise IntervalException("No fallback measure for this found.")

        logger.warning(
        "Using fallback event %s because primary event %s was missing",
        fallback_event["event"],
        primary_event["event"],
        )

        return get_event_time_from_spec(event_sources, fallback_event)

def create_intervals(vr_markers_df,VR_trial_events_df):

    logger.info("Creating intervals.")

    event_sources = {
        "VR_markers" : vr_markers_df,
        "VR_trial_events" : VR_trial_events_df
    }

    vr_intervals = {}

    for interval_name, interval_events in cfg.get_vr_intervals().items():
        start_event = interval_events["start"]
        start_fallback = interval_events.get("start_fallback")

        end_event = interval_events["end"]
        end_fallback = interval_events.get("end_fallback")

        try:
            start_time = get_event_time_with_fallback(
                event_sources,
                start_event,
                start_fallback,
            )

            end_time = get_event_time_with_fallback(
                event_sources,
                end_event,
                end_fallback,
            )

        except IntervalException:
            logger.warning(
                "Could not create interval %s from start event %s to end event %s",
                interval_name,
                start_event["event"],
                end_event["event"],
            )
            continue

        vr_intervals[interval_name] = (start_time, end_time)

    return vr_intervals

def slice_data_frame(dataframe_in,vr_intervals):

    df_dict_out = {}

    for key,start_end in vr_intervals.items():
        print(f"Interval {key}: {start_end}. Data type: {type(start_end)}")
        df_dict_out.update({f"{key}" : xdf_io.cut_df_per_interval(start_end,dataframe_in)})

    return df_dict_out
