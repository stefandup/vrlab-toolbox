import pandas as pd

CRANE_REDCAP_RENAMES = {
    "crane_dissastifaction_gb": "crane_dissatisfaction_gb",
}


def clean_crane_redcap_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean REDCap variables used by the Crane task."""
    return df.rename(columns=CRANE_REDCAP_RENAMES)