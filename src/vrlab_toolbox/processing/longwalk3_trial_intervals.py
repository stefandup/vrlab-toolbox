from matplotlib.figure import Figure

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.longwalk3_behaviour import RawLongWalkV3BehaviourData
from vrlab_toolbox.processing.output_data import PipelineStatus
from vrlab_toolbox.processing.trial_intervals import TrialIntervals


class LongWalkV3GetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawLongWalkV3BehaviourData] = RawLongWalkV3BehaviourData
    fallback_strategy = None

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawLongWalkV3BehaviourData
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]:

        return (TrialIntervals(), Figure(), PipelineStatus())
