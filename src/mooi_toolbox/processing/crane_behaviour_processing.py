import pandas as pd
from pathlib import Path
import re
import logging
import pandera.pandas as pa

logger = logging.getLogger(__name__)
#TODO convert to tuple
EMOTIONS_TESTED = ["Boredom", "Dissatisfaction", "Joy", "Sadness", "Satisfaction", "Confused", "Anger"]

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
        analysis_df
        .groupby(["BlockType", "TrialType"])
        .size()
        .reindex(expected_conditions, fill_value=0)
    )

    return counts.min() > 0 and counts.nunique() == 1

crane_behav_file_schema = pa.DataFrameSchema(
    {
    "TrialNr" : pa.Column(int, pa.Check.ge(1),nullable=False),
    "TrialStartTime" : pa.Column(float, pa.Check.ge(1),nullable=False),
    "TrialEndTime" : pa.Column(float, pa.Check.ge(1),nullable=False),
    "BlockType" : pa.Column(
        str, pa.Check.isin(["NonStressBlock","StressBlock"]),
        nullable=False),
    "TrialType" : pa.Column(
        str, pa.Check.isin(["SlipTrial","NonSlipTrial"]),
        nullable=False),
    "Training" : pa.Column(bool,nullable=False),
    "CurrentScore" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "TotalDropped" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "TargetScore" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "nrFrustrationBarrels" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "NrErrorSlips" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "NrSlips" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "NrOtherSlips" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "NrNoReasonSlips" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "NrForcedSlips" : pa.Column(int, pa.Check.ge(0),nullable=False),
    "AvgVelocity" : pa.Column(float, pa.Check.ge(0),nullable=False),
    "Nausea" : pa.Column(int, pa.Check.isin([1,2,3,4,5]),nullable=False),
    "Dizzy" : pa.Column(int, pa.Check.isin([1,2,3,4,5]),nullable=False),
    "Stressed" : pa.Column(int, pa.Check.isin([1,2,3,4,5]),nullable=False),
    "EmotionFeedback" : pa.Column(
        str, pa.Check.isin(EMOTIONS_TESTED),
        nullable=False),
    },
    strict=True,
    coerce=True,
    checks=pa.Check(has_balanced_conditions,
                    name="balanced_block_trial_conditions",
                    error=("Expected equal non-training trial "
                    "counts for every BlockType x TrialType condition."),
    ),
)

# Match with BIOPAC data
def behaviour_matches_biopac_data(subject_id : str,behaviour_data_dir : str) -> list[Path]:
    logger.info(f"Looking for {subject_id} in {behaviour_data_dir}...")

    reg_pattern = f"^.*{subject_id}_CraneOut.csv$"
    compiled = re.compile(reg_pattern)

    root = Path(behaviour_data_dir)
    return [ 
            behav_file_path 
            for behav_file_path in root.rglob("*") 
            if behav_file_path.is_file() and compiled.search(behav_file_path.name)
            ]

def import_csv_to_long_df(behav_fn : Path) -> pd.DataFrame: 
    """Import behaviour to a long df"""

    # Check for missing data. Try to work around missing data, but break if you need to.
    return pd.read_csv(behav_fn)

def create_participant_out_data(long_data_df : pd.DataFrame) -> pd.DataFrame:
    """
    Takes per participant crane behav data and converts to wide data which then can be 
    added in the pipeline.
    
    """
    #group_cols = 


    return pd.DataFrame()

def load_and_validate_crane_behaviour_csv(behav_file_fn) -> pd.DataFrame:
    #TODO: Decide what to do when multiple csv files are found
    behav_df = import_csv_to_long_df(behav_file_fn)
    try:
        behav_df_validated = crane_behav_file_schema.validate(behav_df)
    except pa.errors.SchemaErrors as e:
        logger.error("Error loading %s: %s",behav_file_fn,e.failure_cases.to_string(index=False))
        raise

    logger.info("Successfully loaded %s", behav_file_fn)

    return behav_df_validated

def main(subject_id : str,behaviour_data_dir : str) -> tuple[pd.DataFrame,pd.DataFrame]:
    
    """
    Per participant processes behaviour files and outputs a wide data frame 
    to concat in the batch.
    
    """

    behav_files_found = behaviour_matches_biopac_data(subject_id,behaviour_data_dir)

    if not behav_files_found:
        error = f"No files found for {subject_id}"
        logger.error(error)
        raise FileNotFoundError(error)
    
    logger.info(f"Found {behav_files_found}")

    behav_df_validated = load_and_validate_crane_behaviour_csv(behav_files_found[0])

    # Remove training
    training_rows = behav_df_validated[behav_df_validated["Training"]].index
    behav_df_validated_no_training = behav_df_validated.drop(index=training_rows)

    wide_cols = ["BlockType","TrialType"]
    
    summary = (
        behav_df_validated_no_training.groupby(wide_cols)
        .agg(
            nausea_avg=("Nausea","mean"),
            dizziness_avg=("Dizzy","mean"),
            stressed_avg=("Stressed","mean"),
            dropped_total=("TotalDropped","sum"),
            nr_frustration_barrels=("nrFrustrationBarrels","median"),
            nr_error_slips=("NrErrorSlips","mean"),
            nr_slips=("NrSlips","mean"),
            nr_no_reason_slips=("NrNoReasonSlips","mean"),
            nr_forced_slips=("NrForcedSlips","mean"),
            avg_velocity=("AvgVelocity","mean"),
            target_score=("TargetScore","median")
        )
    )
    emotion_counts = (
        behav_df_validated_no_training
        .groupby(wide_cols)["EmotionFeedback"]
        .value_counts()
        .unstack(fill_value=0)
        .reindex(columns=EMOTIONS_TESTED, fill_value=0)
    )

    emotion_totals = emotion_counts.sum(axis=1)
    emotion_proportions = emotion_counts.div(emotion_totals, axis=0)

    summary_with_proportions = (
        summary
        .drop(columns=EMOTIONS_TESTED, errors="ignore")
        .join(emotion_proportions.add_suffix("_proportion"))
    )

    one_row = summary_with_proportions.unstack(wide_cols,fill_value=0)

    if isinstance(one_row,pd.Series):
        one_row = one_row.to_frame().T

    one_row.columns = [f"{metric}_{block_type}_{trial_type}" for metric, block_type, trial_type in one_row.columns]

    one_row = one_row.reset_index(drop=True)

    return one_row,behav_df_validated