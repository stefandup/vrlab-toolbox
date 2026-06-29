import logging
import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

from mooi_toolbox.read_mobi_xdf import xdf_io
from mooi_toolbox import config as cfg
from mooi_toolbox.processing.processing_status import ProcessingStatus
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

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

def remove_known_false_triggers(trigger_interval_pairs : list[tuple[float,float]]) -> tuple[list[tuple[float,float]],ProcessingStatus]:
    #TODO: Improve! This needs to update with an partial
    #[start_end[1] - start_end[0] for start_end in trigger_interval_pairs]
    if not trigger_interval_pairs:
        return (trigger_interval_pairs, ProcessingStatus.ERROR)

    tolerance = 0.1
    valid_trigger_interval_pairs = []

    status_out = ProcessingStatus.OK
    for pair_nr, (start_time, end_time) in enumerate(trigger_interval_pairs):


        if pair_nr == 0 and np.isclose(start_time, 0.0, atol=tolerance):
            logger.warning(
                "Removed first interval because its start is likely a false start: %s",
                start_time,
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        if np.isclose(end_time - start_time, 0.0, atol=tolerance):
            logger.warning(
                "Removed interval %.3f to %.3f because its duration is close to zero",
                start_time,
                end_time,
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        if end_time - start_time < 10.0:
            logger.warning(
                "Removed interval %.3f to %.3f because its duration is too short: %.3f (s)",
                start_time,
                end_time,
                end_time - start_time
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        valid_trigger_interval_pairs.append((start_time, end_time))

    return (valid_trigger_interval_pairs,status_out)

def get_trigger_intervals(trigger_df_in : pd.DataFrame) -> tuple[dict[str,tuple[float,float]],ProcessingStatus]:
    """Uses the biopac intervals and gets all the intervals and assigns a TP nr to them regardless of nr"""
    trigger_times = trigger_df_in['time_stamps'][trigger_df_in['Trigger'].diff() > 0.47]
    trigger_events_df = trigger_times.to_frame(name = "trigger_times")
    interval_pairs = list(zip(trigger_events_df['trigger_times'].iloc[:-1], trigger_events_df['trigger_times'].iloc[1:]))
    interval_pairs,status = remove_known_false_triggers(interval_pairs) 

    trigger_intervals_out = {
        f"TP{i}" : (float(start),float(end))for i,(start,end) in enumerate(interval_pairs)
        }
    
    return (trigger_intervals_out,status)

def get_crane_behav_intervals(validated_behav_df : pd.DataFrame) -> dict[str,tuple[float,float]]:
    
    intervals_out = {}

    for index, row in validated_behav_df.iterrows():
        if row["Training"]:
            intervals_out.update({f"{row["BlockType"]}_{row["TrialType"]}_{row["TrialNr"]}_Training" : tuple([row["TrialStartTime"],row["TrialEndTime"]])})
        else:    
            intervals_out.update({f"{row["BlockType"]}_{row["TrialType"]}_{row["TrialNr"]}" : tuple([row["TrialStartTime"],row["TrialEndTime"]])})

    return intervals_out

def get_predicted_trigger_intervals(behav_intervals : dict[str, tuple[float, float]]) -> tuple[dict[str,tuple[float,float]],float]:
    #TODO incorporate
    reference_df = pd.read_parquet(r"references/matched_debug_df_testa.parquet")

    # Control for the relative start difference.
    X = (reference_df["behav_start"].loc[1:len(behav_intervals)] - reference_df["behav_start"].iloc[0]).values.reshape(-1,1)
    y = (reference_df["trigger_start"].loc[1:len(behav_intervals)] - reference_df["trigger_start"].iloc[0]).values.reshape(-1,1)

    model = make_pipeline(
    PolynomialFeatures(degree=2, include_bias=False),
    LinearRegression()
    )

    model.fit(X,y)
    newX = np.array([start_end_time[0] for start_end_time in behav_intervals.values()]).reshape(-1,1)
    newX_rel = newX - newX[0]
    mean_trial_len = np.mean([start_end_times[1] - start_end_times[0] for start_end_times in behav_intervals.values()])
    train_pred_y = model.predict(X)
    absolute_errors = np.abs(np.ravel(y) - np.ravel(train_pred_y))
    max_expected_delta = np.percentile(absolute_errors, 95) * 10

    pred_trigger_y = model.predict(newX_rel)

    pred_trigger_intervals = {
        key : (pred_trigger_y[nr].item(),pred_trigger_y[nr].item() + mean_trial_len) 
        for nr,key in enumerate(behav_intervals.keys())
        }
    return (pred_trigger_intervals,max_expected_delta)


def match_behav_intervals_with_trigger_intervals(trigger_intervals : dict[str,tuple[float,float]],validated_behav_df) -> tuple[dict[str,tuple[float,float]],ProcessingStatus]:
    #TODO: Make more robust
    behav_intervals = get_crane_behav_intervals(validated_behav_df)
    pred_trigger_intervals,max_expected_delta = get_predicted_trigger_intervals(behav_intervals)
    status = ProcessingStatus.OK
    experiment_start = next(iter(trigger_intervals.values()))[0] # Get first value of dict

    remaining_trigger_intervals = trigger_intervals.copy()
    matched_intervals = {}
    unmatched_behav_keys = set(behav_intervals.keys())
    max_start_delta=max_expected_delta
    best_deltas = []

    for pred_key,pred_start_end in pred_trigger_intervals.items():

        rel_pred_start = pred_start_end[0]
        best_trigger_key = None
        best_delta = float("inf")

        for trigger_interval_key,trigger_start_end in remaining_trigger_intervals.items():
            rel_trigger_start = trigger_start_end[0] - experiment_start
            delta = abs(rel_pred_start - rel_trigger_start)

            if delta < best_delta:
                best_trigger_key = trigger_interval_key
                best_delta = delta
                best_deltas.append(best_delta)

        if best_trigger_key is None:
            continue

        if best_delta > max_start_delta:
            logger.warning("Max delta exceeded for trigger %s. Delta: %s",best_trigger_key,best_delta)

        unmatched_behav_keys.remove(pred_key)
        matched_intervals[pred_key] = remaining_trigger_intervals.pop(best_trigger_key)

        #print(f"Selected: {best_trigger_key}. Best delta: {best_delta}. Matched {pred_key}")
        
    if len(unmatched_behav_keys) != 0:                                                                                                                 
        logger.warning("Could not match %s",unmatched_behav_keys)
        logger.debug("Best deltas where: %s",best_deltas)                                                                                      
        status = ProcessingStatus.ERROR  

    return (matched_intervals,status)
