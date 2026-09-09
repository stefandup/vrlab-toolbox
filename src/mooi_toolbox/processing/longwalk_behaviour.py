from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing import pandera_defaults
from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.bids import BidsEventsData, build_base_bids_events_schema
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.longwalk_bids import create_bids_events_file_in_folder
from mooi_toolbox.processing.output_data import (
    PipelineOutputData,
    build_base_pipeline_output_schema,
)
from mooi_toolbox.processing.trial_intervals import TrialIntervals

LONGWALK_EVENTS_LABELS = {
    "TP0": "green_marker_1",
    "TP1": "green_marker_2",
    "TP2": "green_marker_3",
    "TP3": "green_marker_4",
    "TP4": "green_marker_5",
    "TP5": "green_marker_6",
    "TP6": "green_marker_7",
    "TP7": "green_marker_8",
    "TP8": "green_marker_9",
    "TP9": "green_marker_10",
    "TP10": "end_marker",
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
    behaviour_output_type = LongWalkRawBehaviourData

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
    return build_base_pipeline_output_schema(
        {
            f"{event_type}_duration_seconds": pandera_defaults.optional_str_col()
            for event_type in LONGWALK_EVENTS_LABELS.values()
        }
    )


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

        bids_events_out = BidsEventsData()

        df_out = pd.DataFrame({"onset": [0], "duration": [0], "trial_type": ["session_start"]})
        for trial_type in raw_behaviour_data_in.raw_behav_df["trial_type"]:
            if trial_type in trial_intervals_in.intervals:
                trial_duration = (
                    trial_intervals_in.intervals[trial_type][1]
                    - trial_intervals_in.intervals[trial_type][0]
                )
                df_out.loc[len(df_out)] = {
                    "onset": trial_intervals_in.intervals[trial_type][0],
                    "duration": trial_duration,
                    "trial_type": trial_type,
                }
        bids_events_out.append_dataframe(
            df_out, {"trial_type": pandera_defaults.optional_str_col()}
        )
        # Create outputdata: Time to complete intervals! :)

        create_bids_events_file_in_folder(
            bids_events_out, config_in.data_folder, config_in.subject_id, "", "behaviour"
        )

        return get_longwalk_outputdata_from_events(config_in.subject_id, bids_events_out)


def update_longwalk_behav_events_file_from_intervals(
    raw_behaviour_data_in: RawBehaviourData, trial_intervals_in: TrialIntervals
) -> LongWalkRawBehaviourData:

    # TODO: Create event file from both interval and empty behav info
    # for trial_type in raw_behaviour_data_in.raw_behav_df['trial_type']:
    #    if trial_type in TrialIntervals.intervals:

    return LongWalkRawBehaviourData(raw_behaviour_data_in.subject_config)


def get_longwalk_outputdata_from_events(
    subject_id_in: str,
    bids_events_in: BidsEventsData,
) -> LongWalkBehaviouralOutputData:

    df_wide = (
        bids_events_in.events_df.assign(row=0)
        .pivot(index="row", columns="trial_type", values="duration")
        .reset_index(drop=True)
    )
    df_wide.columns.name = None
    df_wide = df_wide.add_suffix("_duration_seconds")
    output_data = LongWalkBehaviouralOutputData(subject_id=subject_id_in)
    output_data.subject_df_out = df_wide
    return output_data
