import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import pandas as pd

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


class SubDict(TypedDict):
    dataframe: pd.DataFrame
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
    return fields[0].strip().lower() in {"date", "timestamp"}


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
        if current_header is not None:
            chunks.append(pd.DataFrame(current_rows, columns=current_header))

        df = pd.concat(chunks, ignore_index=True)

    return df


def get_dfs_by_date(subject_id_in: str, data_folder_in: Path) -> dict[Path, SubDict]:
    return {
        file: {
            "dataframe": csv_to_df_compress_header(file),
            "date": _get_date_from_id(file),
            "session_nr": _get_session_nr(file),
            "city_nr": _get_city_nr(file),
            "bp_id": get_bp_id(file),
        }
        for file in data_folder_in.rglob(f"*{subject_id_in}*.csv")
    }


def combine_behaviour_files(subject_id_in: str, data_folder_in: Path) -> pd.DataFrame:
    df_list: list[pd.DataFrame] = []
    dfs_by_date = get_dfs_by_date(subject_id_in, data_folder_in)

    for nr, (fn, sub_dict) in enumerate(dfs_by_date.items()):
        bids_filename_out = f"sub-{subject_id_in}_ses-{sub_dict['session_nr']}_task-longwalkv3_run-000_behaviour.tsv"

        # print(f"For date {sub_dict['date']} - {bids_filename_out}")
        df = sub_dict["dataframe"]
        df.rename(columns={"TimeStamp": "onset", "date": "onset"}, inplace=True)
        df["onset"] = pd.to_datetime(df["onset"], format=DATESTR_FORMAT, errors="coerce")
        df = df.add_suffix(f"_{sub_dict['bp_id']}")
        df.rename(columns={f"onset_{sub_dict['bp_id']}": "onset"}, inplace=True)
        df_list.append(df)

    df_out = pd.concat(df_list, ignore_index=True)
    df_out = df_out.sort_values("onset").reset_index(drop=True)

    return df_out
