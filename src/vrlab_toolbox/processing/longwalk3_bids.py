import logging
import re
from datetime import datetime
from pathlib import Path
from typing import TypedDict

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


def get_all_dfs(subject_id_in: str, data_folder_in: Path) -> dict[Path, SubDict]:
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


# TODO: finish csv combination: should have an output suggestion as well.
def combine_behaviour_files(subject_id_in: str, data_folder_in: Path) -> dict[str, pd.DataFrame]:
    df_lists: dict[str, list[pd.DataFrame]] = {}
    dfs_by_date = get_all_dfs(subject_id_in, data_folder_in)

    for nr, (fn, sub_dict) in enumerate(dfs_by_date.items()):
        bids_filename_out = f"sub-{subject_id_in}_ses-{sub_dict['session_nr']}_task-longwalkv3_run-000_behaviour.tsv"

        # print(f"For date {sub_dict['date']} - {bids_filename_out}")
        df = sub_dict["dataframe"]
        df.rename(
            columns={"TimeStamp": "onset", "date": "onset", "datetime": "onset"}, inplace=True
        )
        df["onset"] = pd.to_datetime(df["onset"], format=DATESTR_FORMAT, errors="coerce")
        df = df.add_suffix(f"_{sub_dict['bp_id']}")
        df.rename(columns={f"onset_{sub_dict['bp_id']}": "onset"}, inplace=True)
        key = str(sub_dict["date"])

        for BP_ACTOR_ID in BP_ACTOR_IDS:
            word_location_df = df.filter(regex=f"^worldLocation_{BP_ACTOR_ID}$")
            col_name = word_location_df.columns[0]

            parts = word_location_df[col_name].str.extract(
                r"X=([\-\d.]+)\s+Y=([\-\d.]+)\sZ=([\-\d.]+)"
            )
            parts.columns = [f"{col_name}_x", f"{col_name}_y", f"{col_name}_z"]
            parts = parts.astype(float)
            # TODO: Now drop the old cols and append the new ones...
        if key is not None:
            df_lists.setdefault(key, []).append(df)

    for session_nr, (list_date, df_list) in enumerate(df_lists.items()):
        print(list_date)
        print(f"{len(df_list)} dfs to merge")
        print("-" * 100)
        combined_dfs = pd.concat(df_list, ignore_index=True)
        target_fn = f"sub-{subject_id_in}_ses-{session_nr}_task-longwalkv3_run-000_behaviour.tsv"

    # combined_dfs = {}
    # for date, df_list in df_lists.items():
    #    combined_df_out = pd.concat(df_list, ignore_index=True)
    #    combined_df_out = combined_df_out.sort_values("onset").reset_index(drop=True)
    #    combined_dfs.update(date) = combined_df_out

    return combined_dfs
