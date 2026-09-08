import logging

from matplotlib.figure import Figure

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.longwalk_behaviour import (
    LONGWALK_EVENTS_LABELS,
    LongWalkRawBehaviourData,
)
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import (
    TrialIntervals,
    get_raw_biopac_trigger_intervals,
    plot_biopac_interval_qc,
)

logger = logging.getLogger(__name__)


class LongWalkGetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[LongWalkRawBehaviourData] = LongWalkRawBehaviourData

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: LongWalkRawBehaviourData
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]:
        interval_pipeline_status = PipelineStatus()
        raw_biopac_triggers = get_raw_biopac_trigger_intervals(raw_biodata_in["Trigger"])

        if len(raw_biopac_triggers.intervals) != len(raw_behaviour_data_in.raw_behav_df):
            logger.warning(
                "Interval count is %d and not %d for subject.",
                len(raw_biopac_triggers.intervals),
                len(raw_behaviour_data_in.raw_behav_df),
            )
            interval_pipeline_status.set(TrialIntervals, ProcessingStatus.ERROR)

        # Relabel with behaviour
        triggers_out = raw_biopac_triggers

        for tp_id in list(raw_biopac_triggers.intervals.keys()):
            if tp_id in LONGWALK_EVENTS_LABELS:
                triggers_out.intervals[LONGWALK_EVENTS_LABELS[tp_id]] = (
                    raw_biopac_triggers.intervals.pop(tp_id)
                )

        interval_qc_figure = plot_biopac_interval_qc(
            raw_biodata_in["Trigger"],
            raw_biopac_triggers,
        )

        return (triggers_out, interval_qc_figure, interval_pipeline_status)
