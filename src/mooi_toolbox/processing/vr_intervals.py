import logging
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import config as cfg
from mooi_toolbox.processing.processing_status import ProcessingStatus

logger = logging.getLogger(__name__)

def get_event_time(xdf_df_in : pd.DataFrame ,col_id : str = "VR_trial", event_id : str = "RaiseSafetyPlatform") -> float:
    """Takes xdf marker streams in and extracts timestaps based on predefined markers. See pyproject.toml for event definitions"""
    try:
        matches = xdf_df_in["time_stamps"][xdf_df_in[col_id] == event_id]
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
    """Sometimes the first markers are missing. Here we use a fallback."""
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
    """Takes marker info from VR LSL streams vr_markers and VR_trial_events and creates intervals."""
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

def slice_data_frame(timestamped_df_in : pd.DataFrame, vr_intervals : dict[str, tuple[float, float]]) -> dict[str, pd.DataFrame]:
    """Takes any dataframe in and subdivides into intervals given."""
    df_dict_out = {}

    for key,start_end in vr_intervals.items():
        df_dict_out.update({f"{key}" : xdf_io.cut_df_per_interval(start_end,timestamped_df_in)})

    return df_dict_out

def get_trigger_intervals(trigger_df_in : pd.DataFrame) -> dict[str,tuple[float,float]]:
    """Uses the biopac intervals and gets all the intervals and assigns a TP nr to them regardless of nr"""
    trigger_times = trigger_df_in['time_stamps'][trigger_df_in['Trigger'].diff() > 0.47]
    trigger_events_df = trigger_times.to_frame(name = "trigger_times")
    interval_pairs = list(zip(trigger_events_df['trigger_times'].iloc[:-1], trigger_events_df['trigger_times'].iloc[1:]))
    
    return {f"TP{i}" : (float(start),float(end))
            for i,(start,end) in enumerate(interval_pairs)}

def get_crane_behav_intervals(validated_behav_df : pd.DataFrame) -> dict[str,tuple[float,float]]:
    
    intervals_out = {}

    for index, row in validated_behav_df.iterrows():
        if row["Training"]:
            intervals_out.update({f"{row["BlockType"]}_{row["TrialType"]}_{row["TrialNr"]}_Training" : tuple([row["TrialStartTime"],row["TrialEndTime"]])})
        else:    
            intervals_out.update({f"{row["BlockType"]}_{row["TrialType"]}_{row["TrialNr"]}" : tuple([row["TrialStartTime"],row["TrialEndTime"]])})

    return intervals_out

def get_predicted_trigger_times(behav_intervals : dict[str, tuple[float, float]]) -> np.ndarray:

    reference_df = pd.read_parquet(r"C:\\Users\\stefan\\mobi_mooi_toolbox\\matched_debug_df_testa.parquet")

    # Control for the relative start difference.
    X = (reference_df["behav_start"].loc[1:len(behav_intervals)] - reference_df["behav_start"].iloc[0]).values.reshape(-1,1)
    y = (reference_df["trigger_start"].loc[1:len(behav_intervals)] - reference_df["trigger_start"].iloc[0]).values.reshape(-1,1)
    model = LinearRegression()
    model.fit(X,y)
    newX = np.array([start_end_time[0] for start_end_time in behav_intervals.values()]).reshape(-1,1)
    newX_rel = newX - newX[0]

    return model.predict(newX_rel)

def match_behav_intervals_with_trigger_intervals(trigger_intervals : dict[str,tuple[float,float]],validated_behav_df) -> tuple[dict[str,tuple[float,float]],ProcessingStatus]:
    #TODO: Make more robust
    behav_intervals = get_crane_behav_intervals(validated_behav_df)
    predicted_trigger_times = get_predicted_trigger_times(behav_intervals)
    status = ProcessingStatus.OK
    
    remaining_trigger_intervals = trigger_intervals.copy()
    matched_intervals = {}
    unmatched_behav_keys = set(behav_intervals.keys())
    max_start_delta=6.0
    best_deltas = []
    best_signed_deltas = []
    matched_debug_rows = []

    for behav_key, behav_interval in behav_intervals.items():

        behav_start = behav_interval[0]
        best_trigger_key = None
        #
        #matched_intervals = trigger_intervals

        best_delta = float("inf")
        #print(f"Behav start {behav_start}")
        for trigger_key,trigger_interval in remaining_trigger_intervals.items():
            trigger_start = trigger_interval[0]
            
            delta = abs(behav_start - trigger_start)
            signed_delta = behav_start - trigger_start
            print(f"Trigger {trigger_key} : Time {trigger_interval[0]} :  Delta: {delta}")
            if delta < best_delta:
                best_trigger_key = trigger_key
                best_delta = delta
                best_signed_delta = signed_delta

        if best_trigger_key is None:
            continue

        if best_delta > max_start_delta:
            continue
        
        #logger.info("Max behav offset is %.2f",best_delta)
        matched_intervals[behav_key] = remaining_trigger_intervals.pop(best_trigger_key)

        matched_debug_rows.append(
            {
                "behav_key": behav_key,
                "trigger_key": best_trigger_key,
                "behav_start": behav_start,
                "behav_end" : behav_interval[1],
                "trigger_start": matched_intervals[behav_key][0],
                "trigger_end" : matched_intervals[behav_key][1],
                "behav_dur" : behav_interval[1] - behav_interval[0],
                "trigger_dur" : matched_intervals[behav_key][1] - matched_intervals[behav_key][0],
                "dur_diff" : (matched_intervals[behav_key][1] - matched_intervals[behav_key][0]) - (behav_interval[1] - behav_interval[0]),
                "trigger_behav_start_diff": behav_start - matched_intervals[behav_key][0],
            }
        )
        unmatched_behav_keys.remove(behav_key)

        print(f"Selected: {best_trigger_key} with best delta: {best_delta} as best match for {behav_key}")
        best_deltas.append(best_delta)
        best_signed_deltas.append(best_signed_delta)
    matched_debug_df = pd.DataFrame(matched_debug_rows)
    matched_debug_df.to_parquet("matched_debug_df_20.parquet")
    print(f"Best deltas: {best_deltas} Signed: {best_signed_deltas}")
    # TODO: Out df for debugging
    debug_rows = []
    for previous_row, current_row in zip(matched_debug_rows[:-1], matched_debug_rows[1:]):
        behav_spacing = current_row["behav_start"] - previous_row["behav_start"]
        trigger_spacing = current_row["trigger_start"] - previous_row["trigger_start"]
        spacing_error = behav_spacing - trigger_spacing
        debug_rows.append({"First_Block_behav" : current_row['behav_key'],
                           "Previous_Block_behav" : previous_row['behav_key'],
                           "Behav_spacing" : behav_spacing,
                           "Trigger_spacing" : trigger_spacing,
                           "Spacing_Error" : spacing_error
                           })
        print(
            f"{previous_row['behav_key']} -> {current_row['behav_key']}: "
            f"behav_spacing={behav_spacing:.3f}, "
            f"trigger_spacing={trigger_spacing:.3f}, "
            f"spacing_error={spacing_error:.3f}"
        )
    debug_df = pd.DataFrame(debug_rows)
    debug_df.to_parquet("vr_debug_out.parquet", index=False)

    if len(unmatched_behav_keys) != 0:
        logger.warning("Could not match %s",unmatched_behav_keys)
        status = ProcessingStatus.ERROR

    return (matched_intervals,status)