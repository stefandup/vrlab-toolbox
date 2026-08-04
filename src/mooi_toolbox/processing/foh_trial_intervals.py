import logging

from matplotlib.figure import Figure

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.foh_behaviour import RawFohBehaviourData
from mooi_toolbox.processing.output_data import PipelineStatus
from mooi_toolbox.processing.trial_intervals import (
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
        create_lsl_trial_intervals(raw_biodata_in, raw_behaviour_data_in)

        return (TrialIntervals(), Figure(), PipelineStatus())


def create_lsl_trial_intervals(
    vr_markers_df: RawBioData, VR_trial_events_df: RawFohBehaviourData
) -> dict[str, tuple[float, float]]:
    # TODO: This shouldnt be hardset to the platform
    """
    Takes marker info from VR LSL streams vr_markers and VR_trial_events and creates intervals.
    """
    event_sources = {"VR_markers": vr_markers_df, "VR_trial_events": VR_trial_events_df}

    trial_intervals = {}
    # TODO: wire to a .py config file.
    for interval_name, interval_events in cfg.get_trial_intervals().items():
        start_event = interval_events["start"]
        start_fallback = interval_events.get("start_fallback")

        end_event = interval_events["end"]
        end_fallback = interval_events.get("end_fallback")

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

        except ValueError:
            logger.warning(
                "Could not create interval %s from start event %s to end event %s",
                interval_name,
                start_event["event"],
                end_event["event"],
            )
            continue

        trial_intervals[interval_name] = (start_time, end_time)

    return trial_intervals
