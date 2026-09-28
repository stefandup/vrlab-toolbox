import json
import re
from io import StringIO
from pathlib import Path

import keyring
import pandas as pd
import requests


DEFAULT_REDCAP_URL = "https://redcap.sun.ac.za/api/"

# Kept temporarily so the existing pull_redcap CLI still works.
LEGACY_REPORT_ID = 14932
LEGACY_KEYRING_USERNAME = "api-token"

KEYRING_SERVICE = "vrlab-toolbox-redcap"


def _safe_filename_part(value: str) -> str:
    """Return a filesystem-safe version of a study/crosscheck id."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "unknown"


def _keyring_username(study_id: str, crosscheck_id: str) -> str:
    """Return the keyring username for one study and crosscheck."""
    return f"{study_id}:{crosscheck_id}"


def save_config(
    config_file: Path,
    redcap_url: str,
    report_id: int,
) -> None:
    """Save non-secret REDCap configuration."""
    config_file.parent.mkdir(parents=True, exist_ok=True)

    config = {
        "redcap_url": redcap_url.strip(),
        "report_id": int(report_id),
    }

    config_file.write_text(
        json.dumps(config, indent=2),
        encoding="utf-8",
    )


def load_config(config_file: Path) -> dict | None:
    """Load REDCap configuration, or None if it has not been configured."""
    if not config_file.exists():
        return None

    try:
        return json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_token(study_id: str, crosscheck_id: str, token: str) -> None:
    """Store a REDCap token for one study and crosscheck."""
    keyring.set_password(
        KEYRING_SERVICE,
        _keyring_username(study_id, crosscheck_id),
        token.strip(),
    )


def get_token(
    study_id: str | None = None,
    crosscheck_id: str | None = None,
) -> str:
    """Load a REDCap API token.

    New code supplies study_id and crosscheck_id.
    Calling without either argument keeps the existing CLI working.
    """
    if study_id is None and crosscheck_id is None:
        username = LEGACY_KEYRING_USERNAME
    elif study_id and crosscheck_id:
        username = _keyring_username(study_id, crosscheck_id)
    else:
        raise ValueError(
            "study_id and crosscheck_id must either both be supplied or both omitted."
        )

    token = keyring.get_password(KEYRING_SERVICE, username)

    if not token:
        if study_id and crosscheck_id:
            raise RuntimeError(
                f"No REDCap API token is configured for "
                f"{study_id!r} / {crosscheck_id!r}."
            )

        raise RuntimeError("No legacy REDCap API token is configured.")

    return token


def pull_report(
    token: str,
    report_id: int = LEGACY_REPORT_ID,
    redcap_url: str = DEFAULT_REDCAP_URL,
) -> pd.DataFrame:
    """Pull one REDCap report and return it as a DataFrame."""
    payload = {
        "token": token,
        "content": "report",
        "report_id": report_id,
        "format": "csv",
        "rawOrLabel": "raw",
        "rawOrLabelHeaders": "raw",
        "exportCheckboxLabel": "false",
        "returnFormat": "json",
    }

    response = requests.post(redcap_url, data=payload, timeout=60)
    response.raise_for_status()

    response_text = response.text.strip()

    if not response_text:
        raise ValueError("REDCap returned an empty response.")

    if response_text.lower().startswith(("<!doctype html", "<html")):
        raise ValueError(
            "REDCap returned HTML instead of CSV. "
            "Check the API URL, API token, and report ID."
        )

    return pd.read_csv(StringIO(response_text))


def redcap_output_path(
    raw_folder: Path,
    study_id: str,
    crosscheck_id: str,
) -> Path:
    """Return the standard REDCap CSV location inside the raw folder."""
    study = _safe_filename_part(study_id)
    crosscheck = _safe_filename_part(crosscheck_id)

    return raw_folder / f"redcap_{study}_{crosscheck}.csv"


def pull_report_to_raw(
    raw_folder: Path,
    study_id: str,
    crosscheck_id: str,
    report_id: int,
    redcap_url: str = DEFAULT_REDCAP_URL,
) -> Path:
    """Pull REDCap data and save it using the standard raw-folder filename."""
    token = get_token(study_id, crosscheck_id)

    dataframe = pull_report(
        token=token,
        report_id=report_id,
        redcap_url=redcap_url,
    )

    output_file = redcap_output_path(
        raw_folder=raw_folder,
        study_id=study_id,
        crosscheck_id=crosscheck_id,
    )

    output_file.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_file, index=False)

    return output_file
