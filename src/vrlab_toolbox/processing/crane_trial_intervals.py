import logging
import math

import pandas as pd
from matplotlib.figure import Figure

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.crane_behaviour import (
    RawCraneBehaviourData,
)
from vrlab_toolbox.processing.pipeline import GetTrialIntervalsFallbackStartegy
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import (
    TrialIntervals,
    align_biopac_trigger_drift_from_behav_file,
    get_raw_biopac_trigger_intervals,
    plot_biopac_interval_qc,
    remove_biopac_known_false_triggers,
)

logger = logging.getLogger(__name__)
EXPECTED_INTERVAL_NR = 23


class CraneGetTrialIntervalStrategyFallbackStep:
    def run(self, raw_biodata_in: RawBioData) -> tuple[TrialIntervals, Figure, PipelineStatus]:
        interval_pipeline_status = PipelineStatus()

        raw_biopac_triggers = get_raw_biopac_trigger_intervals(raw_biodata_in["Trigger"])

        if len(raw_biopac_triggers.intervals) != EXPECTED_INTERVAL_NR:
            logger.warning(
                "Interval count is %d and not %d for subject.",
                len(raw_biopac_triggers.intervals),
                EXPECTED_INTERVAL_NR,
            )
        interval_pipeline_status.set(TrialIntervals, ProcessingStatus.ERROR)

        corrected_raw_trigger_intervals_gaps_filled = get_biopac_trigger_intervals_crane_pipeline(
            raw_biopac_triggers
        )

        interval_qc_figure = plot_biopac_interval_qc(
            raw_biodata_in["Trigger"],
            raw_biopac_triggers,
            corrected_raw_trigger_intervals_gaps_filled,
        )

        return (
            corrected_raw_trigger_intervals_gaps_filled,
            interval_qc_figure,
            interval_pipeline_status,
        )


class CraneGetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawCraneBehaviourData] = RawCraneBehaviourData
    fallback_strategy: "GetTrialIntervalsFallbackStartegy" = (
        CraneGetTrialIntervalStrategyFallbackStep()
    )

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawCraneBehaviourData
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]:

        interval_pipeline_status = PipelineStatus()

        raw_biopac_triggers = get_raw_biopac_trigger_intervals(raw_biodata_in["Trigger"])

        if len(raw_biopac_triggers.intervals) != EXPECTED_INTERVAL_NR:
            logger.warning(
                "Interval count is %d and not %d for subject.",
                len(raw_biopac_triggers.intervals),
                EXPECTED_INTERVAL_NR,
            )
            interval_pipeline_status.set(TrialIntervals, ProcessingStatus.ERROR)

        corrected_raw_trigger_intervals_gaps_filled = get_biopac_trigger_intervals_crane_pipeline(
            raw_biopac_triggers
        )

        raw_behav_trial_intervals = get_crane_trigger_behav_intervals(
            raw_behaviour_data_in.raw_behav_df
        )

        behav_trial_intervals_gaps_filled = raw_behav_trial_intervals.fill_in_gaps()

        aligned_behav_with_triggers, match_status = align_biopac_trigger_drift_from_behav_file(
            corrected_raw_trigger_intervals_gaps_filled, behav_trial_intervals_gaps_filled
        )

        interval_pipeline_status = interval_pipeline_status.merge(match_status)

        interval_qc_figure = plot_biopac_interval_qc(
            raw_biodata_in["Trigger"],
            raw_biopac_triggers,
            corrected_raw_trigger_intervals_gaps_filled,
            aligned_behav_with_triggers,
            behav_trial_intervals_gaps_filled,
        )

        return (aligned_behav_with_triggers, interval_qc_figure, interval_pipeline_status)


def get_biopac_trigger_intervals_crane_pipeline(raw_biopac_triggers) -> TrialIntervals:

    biopac_interval_pipeline_status = PipelineStatus()

    corrected_raw_triggers, corrected_status = remove_biopac_known_false_triggers(
        raw_biopac_triggers
    )
    biopac_interval_pipeline_status.set(TrialIntervals, corrected_status)
    corrected_raw_trigger_intervals_gaps_filled = corrected_raw_triggers.fill_in_gaps()
    corrected_raw_trigger_intervals_gaps_filled = remove_crane_delayed_start(
        corrected_raw_trigger_intervals_gaps_filled
    )

    return corrected_raw_trigger_intervals_gaps_filled


def get_crane_trigger_behav_intervals(
    validated_behav_df: pd.DataFrame,
) -> TrialIntervals:
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
    trial_intervals_out = TrialIntervals(intervals=intervals_out)
    return trial_intervals_out


def remove_crane_delayed_start(trigger_intervals_in: TrialIntervals) -> TrialIntervals:
    first_key, first_tp = next(iter(trigger_intervals_in.intervals.items()))
    if not math.isclose(first_tp[1] - first_tp[0], 60, abs_tol=1):
        trigger_intervals_in.intervals.pop(first_key, None)

    return trigger_intervals_in
