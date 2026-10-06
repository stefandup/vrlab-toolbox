from matplotlib.figure import Figure

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.input_data import PhysiologyFileFormat
from vrlab_toolbox.processing.longwalk3_behaviour import RawLongWalkV3BehaviourData
from vrlab_toolbox.processing.output_data import PipelineStatus
from vrlab_toolbox.processing.trial_intervals import (
    TrialIntervals,
    get_raw_biopac_trigger_intervals,
    plot_biopac_interval_qc,
)


class LongWalkV3GetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawLongWalkV3BehaviourData] = RawLongWalkV3BehaviourData
    fallback_strategy = None

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawLongWalkV3BehaviourData
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]:

        trial_intervals_out = TrialIntervals()
        raw_biopac_triggers = get_raw_biopac_trigger_intervals(raw_biodata_in["Trigger"])
        marker_intervals = get_longwalkv3_marker_intervals(raw_behaviour_data_in)
        # matched_intervals = raw_biopac_triggers.relabel_with_intervals(marker_intervals)

        interval_qc_figure_out = plot_biopac_interval_qc(
            raw_biodata_in["Trigger"],
            raw_biopac_trigger_intervals=raw_biopac_triggers,
            raw_behav_trial_intervals=marker_intervals,
        )

        return (trial_intervals_out, interval_qc_figure_out, PipelineStatus())


def get_longwalkv3_marker_intervals(raw_behaviour_data_in) -> TrialIntervals:

    marker_ID_df = raw_behaviour_data_in.raw_behav_df.dropna(subset="actor_ThreatLevelMarkerNewC")
    marker_interval_pairs = list(
        zip(marker_ID_df["onset"].iloc[:-1], marker_ID_df["onset"].iloc[1:], strict=False)
    )

    return TrialIntervals.from_raw_interval_pairs(
        marker_interval_pairs, physiology_file_format_in=PhysiologyFileFormat.BIOPAC
    )
