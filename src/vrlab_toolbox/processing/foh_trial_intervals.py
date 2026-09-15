import logging

import pandas as pd
from matplotlib.figure import Figure

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.foh_behaviour import RawFohBehaviourData
from vrlab_toolbox.processing.foh_config import FOH_TRIAL_INTERVALS
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import (
    TrialIntervals,
    get_lsl_event_time_with_fallback,
)

logger = logging.getLogger(__name__)


class FohGetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawFohBehaviourData] = RawFohBehaviourData
    fallback_strategy = None

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawFohBehaviourData
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]:
        trial_intervals = TrialIntervals()
        interval_pipeline_status = PipelineStatus()

        try:
            trial_intervals, interval_pipeline_status = create_foh_lsl_trial_intervals(
                raw_biodata_in["VR_markers"], raw_behaviour_data_in.raw_behav_df
            )
        except (KeyError, ValueError) as e:
            logger.warning(f"Error processing intervals. - {e}")

        return (trial_intervals, Figure(), interval_pipeline_status)


def create_foh_lsl_trial_intervals(
    vr_markers_df: pd.DataFrame, VR_trial_events_df: pd.DataFrame
) -> tuple[TrialIntervals, PipelineStatus]:
    # TODO: This shouldnt be hardset to the platform
    """
    Takes marker info from VR LSL streams vr_markers and VR_trial_events and creates intervals.
    """
    event_sources = {"VR_markers": vr_markers_df, "VR_trial_events": VR_trial_events_df}

    trial_intervals = {}
    pipeline_status = PipelineStatus()

    for interval_name, interval_events in FOH_TRIAL_INTERVALS.items():
        start_event = interval_events.start
        start_fallback = interval_events.start_fallback

        end_event = interval_events.end
        end_fallback = interval_events.end_fallback

        try:
            start_time = get_lsl_event_time_with_fallback(
                event_sources,
                start_event,
                start_fallback,
            )

            end_time = get_lsl_event_time_with_fallback(
                event_sources,
                end_event,
                end_fallback,
            )
            pipeline_status.set(TrialIntervals, ProcessingStatus.OK)

        except ValueError:
            logger.warning(
                "Could not create interval %s from start event %s to end event %s",
                interval_name,
                start_event.event,
                end_event.event,
            )
            pipeline_status.set(TrialIntervals, ProcessingStatus.ERROR)
            continue

        trial_intervals[interval_name] = (start_time, end_time)
    trial_intervals_out = TrialIntervals(intervals=trial_intervals)
    return (trial_intervals_out, pipeline_status)
