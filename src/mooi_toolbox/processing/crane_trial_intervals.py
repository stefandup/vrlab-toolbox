import logging

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.crane_behaviour import RawCraneBehaviourData
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals, get_raw_biopac_trigger_intervals

logger = logging.getLogger(__name__)
EXPECTED_INTERVAL_NR = 23


class CraneGetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawCraneBehaviourData] = RawCraneBehaviourData

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawCraneBehaviourData
    ) -> tuple[TrialIntervals, PipelineStatus]:

        interval_pipeline_status = PipelineStatus()

        raw_biopac_triggers = get_raw_biopac_trigger_intervals(raw_biodata_in["Trigger"])

        if len(raw_biopac_triggers.intervals) != EXPECTED_INTERVAL_NR:
            logger.warning(
                "Interval count is %d and not %d for subject.",
                len(raw_biopac_triggers.intervals),
                EXPECTED_INTERVAL_NR,
            )
            interval_pipeline_status = interval_pipeline_status.merge(
                PipelineStatus(intervals=ProcessingStatus.ERROR)
            )

        corrected_triggers, corrected_status = remove_crane_known_false_triggers(
            raw_biopac_triggers
        )
        interval_pipeline_status = interval_pipeline_status.merge(
            PipelineStatus(intervals=corrected_status)
        )
        matched_triggers, match_status = match_crane_behav_intervals_with_trigger_intervals(
            corrected_triggers, raw_behaviour_data_in.raw_behav_df
        )
        interval_pipeline_status = interval_pipeline_status.merge(
            PipelineStatus(intervals=match_status)
        )

        return (matched_triggers, interval_pipeline_status)


def remove_crane_known_false_triggers(
    trigger_intervals_to_check: TrialIntervals,
) -> tuple[TrialIntervals, ProcessingStatus]:
    # TODO: Improve! This needs to update with partial
    # [start_end[1] - start_end[0] for start_end in trigger_interval_pairs]
    if not trigger_intervals_to_check.intervals:
        return (trigger_intervals_to_check, ProcessingStatus.ERROR)

    trigger_interval_pairs = list(trigger_intervals_to_check.intervals.values())

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
                end_time - start_time,
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        valid_trigger_interval_pairs.append((start_time, end_time))

    valid_trigger_interval_pairs = TrialIntervals.from_raw_interval_pairs(
        valid_trigger_interval_pairs
    )

    return (valid_trigger_interval_pairs, status_out)


def get_crane_trigger_behav_intervals(
    validated_behav_df: pd.DataFrame,
) -> dict[str, tuple[float, float]]:
    # TODO: Needs to be generalized
    intervals_out = {}

    for _, row in validated_behav_df.iterrows():
        if row["Training"]:
            intervals_out.update(
                {
                    f"{row['BlockType']}_{row['TrialType']}_{row['TrialNr']}_Training": tuple(
                        [row["TrialStartTime"], row["TrialEndTime"]]
                    )
                }
            )
        else:
            intervals_out.update(
                {
                    f"{row['BlockType']}_{row['TrialType']}_{row['TrialNr']}": tuple(
                        [row["TrialStartTime"], row["TrialEndTime"]]
                    )
                }
            )

    return intervals_out


def get_crane_predicted_trigger_intervals(
    behav_intervals: dict[str, tuple[float, float]],
) -> tuple[dict[str, tuple[float, float]], float]:

    reference_df = pd.read_parquet(r"references/matched_debug_df_testa.parquet")

    # Control for the relative start difference.
    X = (
        reference_df["behav_start"].loc[1 : len(behav_intervals)]
        - reference_df["behav_start"].iloc[0]
    ).values.reshape(-1, 1)
    y = (
        reference_df["trigger_start"].loc[1 : len(behav_intervals)]
        - reference_df["trigger_start"].iloc[0]
    ).values.reshape(-1, 1)

    model = make_pipeline(PolynomialFeatures(degree=2, include_bias=False), LinearRegression())

    model.fit(X, y)
    newX = np.array([start_end_time[0] for start_end_time in behav_intervals.values()]).reshape(
        -1, 1
    )
    newX_rel = newX - newX[0]
    mean_trial_len = np.mean(
        [start_end_times[1] - start_end_times[0] for start_end_times in behav_intervals.values()]
    )
    train_pred_y = model.predict(X)
    absolute_errors = np.abs(np.ravel(y) - np.ravel(train_pred_y))
    max_expected_delta = np.percentile(absolute_errors, 95) * 10

    pred_trigger_y = model.predict(newX_rel)

    pred_trigger_intervals = {
        key: (pred_trigger_y[nr].item(), pred_trigger_y[nr].item() + mean_trial_len)
        for nr, key in enumerate(behav_intervals.keys())
    }
    return (pred_trigger_intervals, max_expected_delta)


def match_crane_behav_intervals_with_trigger_intervals(
    trial_intervals_in: TrialIntervals, validated_behav_df: pd.DataFrame
) -> tuple[TrialIntervals, ProcessingStatus]:
    # TODO: Make more robust
    trigger_intervals = trial_intervals_in.intervals
    behav_intervals = get_crane_trigger_behav_intervals(validated_behav_df)
    pred_trigger_intervals, max_expected_delta = get_crane_predicted_trigger_intervals(
        behav_intervals
    )
    status = ProcessingStatus.OK
    experiment_start = next(iter(trigger_intervals.values()))[0]  # Get first value of dict

    remaining_trigger_intervals = trigger_intervals.copy()
    matched_intervals = {}
    unmatched_behav_keys = set(behav_intervals.keys())
    max_start_delta = max_expected_delta
    best_deltas = []

    for pred_key, pred_start_end in pred_trigger_intervals.items():
        rel_pred_start = pred_start_end[0]
        best_trigger_key = None
        best_delta = float("inf")

        for trigger_interval_key, trigger_start_end in remaining_trigger_intervals.items():
            rel_trigger_start = trigger_start_end[0] - experiment_start
            delta = abs(rel_pred_start - rel_trigger_start)

            if delta < best_delta:
                best_trigger_key = trigger_interval_key
                best_delta = delta
                best_deltas.append(best_delta)

        if best_trigger_key is None:
            continue

        if best_delta > max_start_delta:
            logger.warning(
                "Max delta exceeded for trigger %s. Delta: %s", best_trigger_key, best_delta
            )

        unmatched_behav_keys.remove(pred_key)
        matched_intervals[pred_key] = remaining_trigger_intervals.pop(best_trigger_key)

        # print(f"Selected: {best_trigger_key}. Best delta: {best_delta}. Matched {pred_key}")

    if len(unmatched_behav_keys) != 0:
        logger.warning("Could not match %s", unmatched_behav_keys)
        logger.debug("Best deltas where: %s", best_deltas)
        status = ProcessingStatus.ERROR

    matched_trial_intervals_out = TrialIntervals(intervals=matched_intervals)

    return (matched_trial_intervals_out, status)
