from io import StringIO

import keyring
import pandas as pd
import requests

REDCAP_URL = "https://redcap.sun.ac.za/api/"
REPORT_ID = 14932

KEYRING_SERVICE = "mooi-toolbox-redcap"
KEYRING_USERNAME = "api-token"


def get_token() -> str:
    """Get the REDCap API token from the operating system credential store."""
    token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)

    if not token:
        raise RuntimeError(
            "No REDCap API token found. "
            "Store it first with: keyring set mooi-toolbox-redcap api-token"
        )

    return token


def pull_report(token: str) -> pd.DataFrame:
    """Pull the REDCap report and return it as a DataFrame."""
    payload = {
        "token": token,
        "content": "report",
        "report_id": REPORT_ID,
        "format": "csv",
        "rawOrLabel": "raw",
        "rawOrLabelHeaders": "raw",
        "exportCheckboxLabel": "false",
        "returnFormat": "json",
    }

    response = requests.post(REDCAP_URL, data=payload, timeout=60)
    response.raise_for_status()

    if not response.text.strip():
        raise ValueError("REDCap returned an empty response.")

    return pd.read_csv(StringIO(response.text))