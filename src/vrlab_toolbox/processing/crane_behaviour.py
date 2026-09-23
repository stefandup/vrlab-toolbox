import logging
from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

from vrlab_toolbox.processing import behaviour
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.output_data import PipelineOutputData

logger = logging.getLogger(__name__)
# TODO convert to tuple
EMOTIONS_TESTED = [
    "Boredom",
    "Dissatisfaction",
    "Joy",
    "Sadness",
    "Satisfaction",
    "Confused",
    "Anger",
]

BLOCK_TYPES = ("NonStressBlock", "StressBlock")
TRIAL_TYPES = ("SlipTrial", "NonSlipTrial")
BEHAVIOUR_OUTPUT_METRICS = (
    "nausea_avg",
    "dizziness_avg",
    "stressed_avg",
    "dropped_total",
    "nr_frustration_barrels",
    "nr_error_slips",
    "nr_slips",
    "nr_no_reason_slips",
    "nr_forced_slips",
    "avg_velocity",
    "target_score",
    *(f"{emotion}_proportion" for emotion in EMOTIONS_TESTED),
)


def has_balanced_conditions(df):
    analysis_df = df[~df["Training"]]

    expected_conditions = pd.MultiIndex.from_product(
        [
            ["NonStressBlock", "StressBlock"],
            ["SlipTrial", "NonSlipTrial"],
        ],
        names=["BlockType", "TrialType"],
    )

    counts = (
        analysis_df.groupby(["BlockType", "TrialType"])
        .size()
        .reindex(expected_conditions, fill_value=0)
    )

    return counts.min() > 0 and counts.nunique() == 1


def build_crane_raw_behav_file_schema() -> pa.DataFrameSchema:
    crane_raw_behav_file_schema = pa.DataFrameSchema(
        {
            "TrialNr": pa.Column(int, pa.Check.ge(1), nullable=False),
            "TrialStartTime": pa.Column(float, pa.Check.ge(1), nullable=False),
            "TrialEndTime": pa.Column(float, pa.Check.ge(1), nullable=False),
            "BlockType": pa.Column(
                str, pa.Check.isin(["NonStressBlock", "StressBlock"]), nullable=False
            ),
            "TrialType": pa.Column(
                str, pa.Check.isin(["SlipTrial", "NonSlipTrial"]), nullable=False
            ),
            "Training": pa.Column(bool, nullable=False),
            "CurrentScore": pa.Column(int, pa.Check.ge(0), nullable=False),
            "TotalDropped": pa.Column(int, pa.Check.ge(0), nullable=False),
            "TargetScore": pa.Column(int, pa.Check.ge(0), nullable=False),
            "nrFrustrationBarrels": pa.Column(int, pa.Check.ge(0), nullable=False),
            "NrErrorSlips": pa.Column(int, pa.Check.ge(0), nullable=False),
            "NrSlips": pa.Column(int, pa.Check.ge(0), nullable=False),
            "NrOtherSlips": pa.Column(int, pa.Check.ge(0), nullable=False),
            "NrNoReasonSlips": pa.Column(int, pa.Check.ge(0), nullable=False),
            "NrForcedSlips": pa.Column(int, pa.Check.ge(0), nullable=False),
            "AvgVelocity": pa.Column(float, pa.Check.ge(0), nullable=False),
            "Nausea": pa.Column(int, pa.Check.isin([1, 2, 3, 4, 5]), nullable=False),
            "Dizzy": pa.Column(int, pa.Check.isin([1, 2, 3, 4, 5]), nullable=False),
            "Stressed": pa.Column(int, pa.Check.isin([1, 2, 3, 4, 5]), nullable=False),
            "EmotionFeedback": pa.Column(str, pa.Check.isin(EMOTIONS_TESTED), nullable=False),
        },
        strict=True,
        coerce=True,
        checks=pa.Check(
            has_balanced_conditions,
            name="balanced_block_trial_conditions",
            error=(
                "Expected equal non-training trial counts for every BlockType x TrialType condition"
            ),
        ),
    )
    return crane_raw_behav_file_schema


def _optional_float_column() -> pa.Column:
    return pa.Column(float, nullable=True, coerce=True, required=False)


def build_crane_behaviour_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            f"{metric}_{block_type}_{trial_type}": _optional_float_column()
            for metric in BEHAVIOUR_OUTPUT_METRICS
            for block_type in BLOCK_TYPES
            for trial_type in TRIAL_TYPES
        },
        coerce=True,
        strict=False,
    )


@dataclass
class RawCraneBehaviourData(behaviour.RawBehaviourData):
    validation_schema: pa.DataFrameSchema = field(default_factory=build_crane_raw_behav_file_schema)

    def to_bids_events(self) -> behaviour.BidsEventsData:

        renamed_to_bids_columns = {
            "TrialNr": "trial_nr",
            "CurrentScore": "current_score",
            "TotalDropped": "total_dropped",
            "TargetScore": "target_score",
            "nrFrustrationBarrels": "nr_frustration_barrels",
            "NrErrorSlips": "nr_error_slips",
            "NrSlips": "nr_slips",
            "NrOtherSlips": "nr_other_slips",
            "NrNoReasonSlips": "nr_no_reason_slips",
            "NrForcedSlips": "nr_forced_slips",
            "AvgVelocity": "avg_velocity",
            "Nausea": "nausea",
            "Dizzy": "dizzy",
            "Stressed": "stressed",
            "EmotionFeedback": "emotion_feedback",
        }

        events_df = pd.DataFrame(
            {
                "onset": self.raw_behav_df["TrialStartTime"],
                "duration": self.raw_behav_df["TrialEndTime"] - self.raw_behav_df["TrialStartTime"],
                "trial_type": (
                    self.raw_behav_df["BlockType"] + "_" + self.raw_behav_df["TrialType"]
                ),
                "training": self.raw_behav_df["Training"],
                **{
                    bids_name: self.raw_behav_df[raw_name]
                    for raw_name, bids_name in renamed_to_bids_columns.items()
                },
            }
        )
        additional_columns = {
            bids_name: pa.Column(self.validation_schema.columns[raw_name].dtype, coerce=True)
            for raw_name, bids_name in renamed_to_bids_columns.items()
        }

        additional_columns["trial_type"] = pa.Column(str, nullable=False, coerce=True)
        additional_columns["training"] = pa.Column(bool, nullable=False, coerce=True)

        bids_events = behaviour.BidsEventsData()
        bids_events.append_dataframe(
            events_df,
            additional_columns=additional_columns,
        )

        return bids_events


@dataclass
class CraneBehaviourOutputData(PipelineOutputData):
    """
    Returns the one line output data which the Pipeline can concatenate for the final
    group level output.
    """

    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_crane_behaviour_output_schema
    )


class ImportCraneBehaviourDataStrategyStep:
    behaviour_output_type: type[RawCraneBehaviourData] = RawCraneBehaviourData

    def run(self, config_in: ParticipantConfig) -> RawCraneBehaviourData:

        return RawCraneBehaviourData.load_from_bids_behaviour_type(
            config_in, self.behaviour_output_type
        )


class ProcessCraneBehaviourDataStrategyStep:
    """
    Emotion proportions per condition.

    For each BlockType x TrialType bucket, count how many trials had each
    EmotionFeedback value, then divide by the bucket's total trial count.
    Result: 7 proportions per bucket (one per emotion), summing to 1.
    """

    input_data_type: type[RawCraneBehaviourData] = RawCraneBehaviourData

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: RawCraneBehaviourData,
    ) -> CraneBehaviourOutputData:
        # TODO: See if using bids might simplify things long run
        behav_df_validated = raw_behaviour_data_in.raw_behav_df

        # Remove training
        training_rows = behav_df_validated[behav_df_validated["Training"]].index
        behav_df_validated_no_training = behav_df_validated.drop(index=training_rows)

        wide_cols = ["BlockType", "TrialType"]

        summary = behav_df_validated_no_training.groupby(wide_cols).agg(
            nausea_avg=("Nausea", "mean"),
            dizziness_avg=("Dizzy", "mean"),
            stressed_avg=("Stressed", "mean"),
            dropped_total=("TotalDropped", "sum"),
            nr_frustration_barrels=("nrFrustrationBarrels", "sum"),
            nr_error_slips=("NrErrorSlips", "sum"),
            nr_slips=("NrSlips", "sum"),
            nr_no_reason_slips=("NrNoReasonSlips", "sum"),
            nr_forced_slips=("NrForcedSlips", "sum"),
            avg_velocity=("AvgVelocity", "mean"),
            target_score=("TargetScore", "median"),
        )
        emotion_counts = (
            behav_df_validated_no_training.groupby(wide_cols)["EmotionFeedback"]
            .value_counts()
            .unstack(fill_value=0)
            .reindex(columns=EMOTIONS_TESTED, fill_value=0)
        )

        emotion_totals = emotion_counts.sum(axis=1)
        emotion_proportions = emotion_counts.div(emotion_totals, axis=0)

        summary_with_proportions = summary.drop(columns=EMOTIONS_TESTED, errors="ignore").join(
            emotion_proportions.add_suffix("_proportion")
        )

        one_row = summary_with_proportions.unstack(wide_cols, fill_value=0)

        if isinstance(one_row, pd.Series):
            one_row = one_row.to_frame().T

        one_row.columns = [
            f"{metric}_{block_type}_{trial_type}"
            for metric, block_type, trial_type in one_row.columns
        ]

        one_row = one_row.reset_index(drop=True)

        behaviour_output = CraneBehaviourOutputData(config_in.subject_id)
        behaviour_output.append_dataframe(one_row, build_crane_behaviour_output_schema().columns)

        return behaviour_output
