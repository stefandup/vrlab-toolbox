import logging
import re
from collections.abc import Hashable
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import pandas as pd
import pandera.pandas as pa

from vrlab_toolbox.processing import pandera_defaults
from vrlab_toolbox.processing.bids import build_base_bids_events_schema

logger = logging.getLogger(__name__)

PHYSIOLOGY_GLOB = "*_LongWalkV3Out.acq"
BEHAVIOUR_GLOB = "*_behaviour.csv"
DATATYPE_FOLDER_NAME = "beh"
# Will have 3 planned sessions
SESSION_TOKEN = "ses-"
# TODO Runs to count up for multiple ones
RUN_TOKEN = "run-000"
TASK_TOKEN = "task-longwalkv3"
_SUBJECT_ID_PATTERN = re.compile(r"^(?:(?P<date>\d+)[_-])?(?P<subject_id>.+?).*$", re.IGNORECASE)
_DUPLICATE_COPY_MARKER_PATTERN = re.compile(r"\(\d+\)\s*$")
_PID_DASH_PATTERN = re.compile(r"^PID-(\d+)$", re.IGNORECASE)
DATESTR_FORMAT = "%Y%m%d%H%M%S%f"


class EventsFileDictAttributes(TypedDict):
    date: datetime | None
    session_nr: int
    city_nr: int
    bp_id: str


def _get_date_from_id(subject_id_in: Path) -> datetime | None:
    date_as_str = str(subject_id_in.name).split("_")[0]

    if date_as_str == "0":
        return None

    return datetime.strptime(date_as_str, DATESTR_FORMAT)


def _get_session_nr(subject_id_in: Path) -> int:
    return int(str(subject_id_in.name).split("_")[2].split("-")[1])


def _get_city_nr(subject_id_in: Path) -> int:
    city_str = str(subject_id_in.name).split("_")[3].split("-")[1]
    return int(re.sub(r"\D", "", city_str))


def get_bp_id(subject_id_in: Path) -> str:
    str_parts = str(subject_id_in.stem).split("_")[5:]

    return "".join(str_parts)


def is_header(fields):
    return fields[0].strip().lower() in {"date", "timestamp", "datetime"}


def csv_to_df_compress_header(csv_fn_in: Path) -> pd.DataFrame:
    chunks = []
    current_header = None
    current_rows = []

    with open(csv_fn_in, encoding="utf-8") as f:
        raw_lines = f.readlines()  # list of strings, each ending in "\n"
        for line in raw_lines:
            line = line.strip()

            if not line:
                continue

            fields = line.split(",")

            if is_header(fields):
                if current_header is not None:
                    chunks.append(pd.DataFrame(current_rows, columns=current_header))
                current_header = fields
                current_rows = []
            else:
                current_rows.append(fields)

        if current_header is None:
            logger.error(f"Error: empty datafile {csv_fn_in}")
            raise ValueError

        chunks.append(pd.DataFrame(current_rows, columns=current_header))

        df = pd.concat(chunks, ignore_index=True)

    return df


def get_all_dfs(subject_id_in: str, data_folder_in: Path) -> list[pd.DataFrame]:
    df_list_out = []
    for file in data_folder_in.rglob(f"*{subject_id_in}*.csv"):
        df_out = csv_to_df_compress_header(file)
        date_out = _get_date_from_id(file)
        attributes = EventsFileDictAttributes(
            date=date_out,
            session_nr=_get_session_nr(file),
            city_nr=_get_city_nr(file),
            bp_id=get_bp_id(file),
        )
        df_out.attrs = cast(dict[Hashable, Any], attributes)
        df_list_out.append(df_out)

    return df_list_out


BP_ACTOR_IDS = [
    "BPAudioCueTriggerC",
    "BPHeatmapManagerC",
    "BPNPCC",
    "BPPanicAttackManagerC",
    "BPPanicCooldownTimersManagerC",
    "BPPanicTriggerC",
    "BPPhoneC",
    "ThreatLevelMarkerNewC",
]


def build_longwalkv3_raw_session_events_behav_file_schema_() -> pa.DataFrameSchema:
    additional_cols_session = {
        "Nausea_behaviour": pandera_defaults.likert_col(),
        "Dizzy_behaviour": pandera_defaults.likert_col(),
        "Stressed_behaviour": pandera_defaults.likert_col(),
        "Anxious_behaviour": pandera_defaults.likert_col(),
        **{
            f"actor_{BP_ACTOR_ID}": pandera_defaults.optional_str_col()
            for BP_ACTOR_ID in BP_ACTOR_IDS
        },
        **{
            f"^worldLocation_{BP_ACTOR_ID}_[xyz]$": pandera_defaults.coord_axis_col()
            for BP_ACTOR_ID in BP_ACTOR_IDS
        },
    }

    return build_base_bids_events_schema(additional_cols_session)


def combine_events_df_files(
    subject_id_in, dfs_by_date: list[pd.DataFrame]
) -> dict[str, pd.DataFrame]:
    df_by_date_dict: dict[datetime, list[pd.DataFrame]] = {}
    session_dfs_by_fn_out_dict: dict[str, pd.DataFrame] = {}

    for df in dfs_by_date:
        df.rename(
            columns={"TimeStamp": "onset", "date": "onset", "datetime": "onset"}, inplace=True
        )
        df["onset"] = pd.to_datetime(df["onset"], format=DATESTR_FORMAT, errors="coerce")
        df = df.add_suffix(f"_{df.attrs['bp_id']}")
        df.rename(columns={f"onset_{df.attrs['bp_id']}": "onset"}, inplace=True)

        # Extract float values from Unreal world location
        actors_bp_list = []
        for BP_ACTOR_ID in BP_ACTOR_IDS:
            word_location_df = df.filter(regex=f"^worldLocation_{BP_ACTOR_ID}$")

            if word_location_df.empty:
                logger.info(f"{BP_ACTOR_ID} has no world location. Skipping.")
                continue

            col_name = word_location_df.columns[0]

            parts = word_location_df[col_name].str.extract(
                r"X=([\-\d.]+)\s+Y=([\-\d.]+)\sZ=([\-\d.]+)"
            )
            parts.columns = [f"{col_name}_x", f"{col_name}_y", f"{col_name}_z"]
            parts = parts.astype(float)
            df[parts.columns] = parts
            df = df.drop(columns=col_name)

            df_by_date_dict.setdefault(df.attrs["date"], []).append(df)

    target_fns_out = []
    # Concat by date
    for session_nr, (list_date, df_list) in enumerate(df_by_date_dict.items()):
        logger.info(f"{len(df_list)} dfs to merge for date {list_date}")
        combined_dfs_out = pd.concat(df_list, ignore_index=True)
        target_fns_out = f"sub-{subject_id_in}_ses-{session_nr}_task-longwalkv3_run-000_events.tsv"
        session_dfs_by_fn_out_dict.update({target_fns_out: combined_dfs_out})

    return session_dfs_by_fn_out_dict
