import pandas as pd
import os
import pandera.pandas as pa
import logging
from functools import cache

from mooi_toolbox.processing.input_data import ParticipantConfig

logger = logging.getLogger(__name__)

EMOTIONS_TESTED = ("Boredom", "Dissatisfaction", "Joy", "Sadness", "Satisfaction", "Confused", "Anger")
emotion_cols = [emotion.upper() for emotion in EMOTIONS_TESTED]

# TODO More checks possible here
crane_debrief_file_schema = pa.DataFrameSchema(
    {
        "Subject_ID" : pa.Column(str),
        "started_with_Crane_MobiLab" : pa.Column(str),
        "High_at_start_end" : pa.Column(str),
        "BARREL" : pa.Column(str,pa.Check.isin(["GREEN","RED"]),nullable=False),
        **{emotion : pa.Column(int, pa.Check.isin([1,2,3,4,5]),nullable=False) for emotion in emotion_cols}
    },
    strict=True,
    coerce=True    
)
#TODO: Fix this as it is likely out of scope
@cache
def load_group_debrief_data(behaviour_data_dir : str) -> pd.DataFrame:
    red_cap_fn = r"CraneGame_Emotional Experience Form.xlsx"
    data_fn = os.path.join(behaviour_data_dir,red_cap_fn)

    df = pd.read_excel(data_fn, dtype={"Subject_ID": str})

    # Clean column names a bit
    df.columns = (
        df.columns
        .str.strip()
        .str.replace(" ", "_")
        .str.replace("/", "_")
    )

    # Forward-fill subject-level variables
    subject_cols = [
        "Subject_ID",
        "started_with_Crane_MobiLab",
        "High_at_start_end"
    ]

    df[subject_cols] = df[subject_cols].ffill()

    # Drop fully empty rows, if any
    df = df.dropna(how="all")
    df = df.drop(columns="Subject_Names")

    # Validate df

    try:
        df_validated = crane_debrief_file_schema.validate(df)
    except pa.errors.SchemaErrors as e:
        logger.error("Error loading %s: %s",data_fn,e.failure_cases.to_string(index=False))
        raise

    # Optional: rename BARREL to something clearer
    df_validated = df_validated.rename(columns={"BARREL": "TrialType"})
    df_validated["TrialType"] = df_validated["TrialType"].replace({"GREEN" : "SlipTrial", "RED" : "NonSlipTrial"})

    emotion_totals = df_validated[emotion_cols].sum(axis=1)
    emotion_proportions = df_validated[emotion_cols].div(emotion_totals,axis=0)
    df_proportions = (df_validated.drop(columns=emotion_cols, errors="ignore").join(emotion_proportions))

    wide = df_proportions.pivot(index=["Subject_ID"],columns="TrialType",values=emotion_cols)
    wide.columns = [
    f"{emotion}_{colour}"
    for emotion, colour in wide.columns
    ]
    wide = wide.reset_index()
    debrief_data_out = wide.add_prefix("Debrief_")

    return debrief_data_out

def process(config_in : ParticipantConfig) -> pd.DataFrame:
    debrief_df = load_group_debrief_data(config_in.behav_folder)
    # Copy as to ensure the cache is read only. Cahce ensures that we dont reload the excel for every subject
    subject_debrief_out = debrief_df.loc[debrief_df["Debrief_Subject_ID"] == config_in.subject_id].copy()

    if subject_debrief_out.empty:
        logger.warning("Missing behaviour data for subject %s",config_in.subject_id)
        raise ValueError

    subject_debrief_out = subject_debrief_out.drop(columns="Debrief_Subject_ID")
    return subject_debrief_out