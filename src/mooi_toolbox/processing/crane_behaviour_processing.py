import pandas as pd
from pathlib import Path
import re
import logging
import pandera.pandas as pa

logger = logging.getLogger(__name__)

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
        str, pa.Check.isin(["Boredom", "Dissatisfaction", "Joy", "Sadness", "Satisfaction", "Confused", "Anger"]),
        nullable=False),
    },
    strict=True,
    coerce=True,
)

# Match with BIOPAC data
def behaviour_matches_biopac_data(subject_id : str,behaviour_data_dir : str) -> list[Path]:
    logger.info(f"Looking for {subject_id} in {behaviour_data_dir}...")

    reg_pattern = f"^{subject_id}.csv$"
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

    return pd.DataFrame()

def create_participant_out_data(long_data_df : pd.DataFrame) -> pd.DataFrame:
    """
    Takes per participant crane behav data and converts to wide data which then can be 
    added in the pipeline.
    
    """
    #group_cols = 


    return pd.DataFrame()

def main(subject_id : str,behaviour_data_dir : str) -> pd.DataFrame:
    
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

    #TODO: Decide what to do when multiple csv files are found
    behav_df = import_csv_to_long_df(behav_files_found[0])
    try:
        behav_df_validated = crane_behav_file_schema.validate(behav_df)
    except pa.errors.SchemaErrors as e:
        logger.error("Error loading %s: %s",behav_files_found[0],e.failure_cases.to_string(index=False))
        raise

    logger.info("Successfully loaded %s", behav_files_found[0])

    wide_cols = ["BlockType","TrialType"]

    summary = (
        behav_df_validated.groupby(wide_cols)
        .agg(
            nausea_total=("Nausea","sum"),
            dizziness_total=("Dizzy","sum"),
            dropped_total=("TotalDropped","sum"),
            nr_frustration_barrels=("NrFrustrationBarrels","median"),
            nr_error_slips=("NrErrorSlips","mean"),
            nr_slips=("NrSlips","mean"),
            nr_no_reason_slips=("NrNoReasonSlips","mean"),
            nr_forced_slips=("NrForcedSlips","mean"),
            avg_velocity=("AvgVelocity","mean"),
            target_score=("TargetScore","median")
        )
    )

    one_row = summary.unstack(wide_cols,fill_value=0)
    one_row = one_row.to_frame().T
    one_row.columns = [f"{metric}_{block_type}_{trial_type}" for metric, block_type, trial_type in one_row.columns]

    one_row = one_row.reset_index(drop=True)

    return one_row