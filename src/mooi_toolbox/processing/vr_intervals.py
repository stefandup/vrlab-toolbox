import logging
import pandas as pd
from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import config as cfg
    
logger = logging.getLogger(__name__)

def get_event_time(df_in : pd.DataFrame ,col_id : str = "VR_trial", event_id : str = "RaiseSafetyPlatform") -> float:
    
    try:
        matches = df_in["time_stamps"][df_in[col_id] == event_id]
    except KeyError as e:
        raise KeyError(f"Error in finding {event_id}") from e
    if matches.empty:
        raise ValueError(f"Can not find {col_id} with id {event_id}")
    
    return float(matches.iloc[0])

def get_event_time_from_spec(event_sources : dict, event_spec : dict) -> float:
    event_time = get_event_time(
        event_sources[event_spec["stream"]],
            event_spec["column"],
            event_spec["event"],
            )
    
    return event_time + event_spec.get("offset_seconds", 0)

def get_event_time_with_fallback(event_sources : dict, primary_event : dict , fallback_event : dict | None = None) -> float:
    
    try:
        return get_event_time_from_spec(event_sources, primary_event)
    except ValueError:
        if fallback_event is None:
            raise ValueError(f"No fallback event for {primary_event}!")

        logger.warning(
        "Using fallback event %s because primary event %s was missing",
        fallback_event["event"],
        primary_event["event"],
        )
    try:
        return get_event_time_from_spec(event_sources, fallback_event)
    except ValueError as fallback_error:
        raise ValueError(f"Primary event {primary_event} and fallback event {fallback_event} were both unavailable."
            ) from fallback_error
    
def create_intervals(vr_markers_df : pd.DataFrame, VR_trial_events_df : pd.DataFrame) -> dict[str, tuple[float, float]]:

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

        except ValueError:
            logger.warning(
                "Could not create interval %s from start event %s to end event %s",
                interval_name,
                start_event["event"],
                end_event["event"],
            )
            continue

        vr_intervals[interval_name] = (start_time, end_time)

    return vr_intervals

def slice_data_frame(dataframe_in : pd.DataFrame, vr_intervals : dict[str, tuple[float, float]]) -> dict[str, pd.DataFrame]:

    df_dict_out = {}

    for key,start_end in vr_intervals.items():
        df_dict_out.update({f"{key}" : xdf_io.cut_df_per_interval(start_end,dataframe_in)})

    return df_dict_out
