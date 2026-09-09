from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.bids import build_base_bids_events_schema
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.output_data import PipelineOutputData
from mooi_toolbox.processing.trial_intervals import TrialIntervals

LONGWALK_EVENTS_LABELS = {
    "TP0": "session_start",
    "TP1": "green_marker_1",
    "TP2": "green_marker_2",
    "TP3": "green_marker_3",
    "TP4": "green_marker_4",
    "TP5": "green_marker_5",
    "TP6": "green_marker_6",
    "TP7": "green_marker_7",
    "TP8": "green_marker_8",
    "TP9": "green_marker_9",
    "TP10": "green_marker_10",
}


# TODO: Why is this not BIDS events from bids.py?
@dataclass
class LongWalkRawBehaviourData(RawBehaviourData):
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_bids_events_schema)
    raw_behav_df: pd.DataFrame = field(default_factory=pd.DataFrame)

    def __post_init__(self):
        if self.raw_behav_df.empty:
            self.raw_behav_df = generate_empty_longwalk_behaviour_df()

        self.raw_behav_df = self.validation_schema(self.raw_behav_df)


class LongWalkImportRawBehaviourDataStrategy:
    behaviour_data_type = LongWalkRawBehaviourData

    def run(self, config_in: ParticipantConfig) -> LongWalkRawBehaviourData:

        return LongWalkRawBehaviourData(config_in)


def generate_empty_longwalk_behaviour_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "onset": [0] * len(LONGWALK_EVENTS_LABELS),
            "duration": [pd.NA] * len(LONGWALK_EVENTS_LABELS),
            "trial_type": [trial_type for trial_type in LONGWALK_EVENTS_LABELS.values()],
        }
    )


def build_long_walk_behaviour_output_data_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


@dataclass
class LongWalkBehaviouralOutputData(PipelineOutputData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_long_walk_behaviour_output_data_schema
    )


class ProcessLongWalkBehaviourDataWithIntervalsStrategyStep:
    input_data_type: type[LongWalkRawBehaviourData] = LongWalkRawBehaviourData

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: LongWalkRawBehaviourData,
        trial_intervals_in: TrialIntervals,
    ) -> LongWalkBehaviouralOutputData:
        # Save to BIDS
        # Create outputdata: Time to complete intervals! :)

        return LongWalkBehaviouralOutputData(config_in.subject_id)


def update_longwalk_behav_events_file_from_intervals(
    raw_behaviour_data_in: RawBehaviourData, trial_intervals_in: TrialIntervals
) -> LongWalkRawBehaviourData:

    # TODO: Create event file from both interval and empty behav info
    # for trial_type in raw_behaviour_data_in.raw_behav_df['trial_type']:
    #    if trial_type in TrialIntervals.intervals:

    return LongWalkRawBehaviourData(raw_behaviour_data_in.subject_config)


def calucluate_interval_durations(trial_intervals_in: TrialIntervals):
    pass
