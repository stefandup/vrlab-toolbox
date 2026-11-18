"""LongwalkV3-specific raw-to-BIDS conversion logic: parsing longwalkV3's raw flat-file
naming, combining a session/city/run's behaviour.csv with its sibling actor-location logs into
one BIDS events.tsv, and orchestrating the copy into a BIDS-shaped output folder. Generic BIDS
mechanics (scans.tsv, filename building, duplicate collision) live in `processing/bids.py` and
are reused here.

Never touches `input_folder` -- only ever copies/writes into `output_folder`. Dumps every
matching file it finds; picking a canonical file among duplicates is the crosscheck tool's job,
not this converter's (see crane_bids.py's module docstring for the same philosophy).

Incremental by subject: a subject whose `sub-XXX/` folder already exists in `output_folder` is
left completely alone and skipped.

Output layout:
- Every file goes in `sub-XXX/ses-NN/beh/`, one `ses-NN` per real longwalkV3 session (up to 3
  planned sessions, each a separate real-world day).
- One physiology `.acq` file per session -- copied as `..._run-001_physio.acq` (physiology has
  no real multi-run concept, so run-001 is a fixed placeholder, same as crane). The raw
  physiology filename carries no `ses-` token of its own, so its session number is inferred
  from chronological order across a subject's `.acq` files (each real session is a separate,
  later day -- see longwalk3_dummy_data.py).
- One events.tsv per (session, city, run) -- a "run" is every distinct raw-file timestamp
  within a session (a behaviour.csv and its sibling actor-location logs always share one
  timestamp per real export burst). Runs are numbered 1, 2, ... in chronological order within
  their session -- the raw filename's own "run-N"/"run-000" token is never a true run counter
  (the real Unreal-side export always writes the same placeholder), so it's ignored for
  numbering and the city label plus a real run number are carried as `acq-<city>`/`run-NNN`
  entities instead.
- One debrief file per subject per session. The REDCap export is long format (one row per
  subject per event); each event maps to a session (REDCAP_EVENT_SESSION_ORDER), and empty
  event rows are skipped. Named with the same `acq-debrief`/`_beh.tsv` convention as crane,
  matching longwalk3_debrief_behaviour.py's `filename_glob`. Identifying columns (names, date
  of birth, signatures) are dropped; every other column is kept as-is until
  longwalk3_debrief_behaviour.py's raw debrief schema is filled in.
- Raw files from the current export sit in `sub-<id>/ses-NN/[run-00N/]`; the session folder
  decides an .acq's session. The legacy flat layout falls back to chronological order.
"""

import json
import logging
import re
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import numpy as np
import pandas as pd
import pandera.pandas as pa
from rich.console import Console
from rich.table import Table

from vrlab_toolbox.processing import bids, pandera_defaults
from vrlab_toolbox.processing.bids import build_base_bids_events_schema
from vrlab_toolbox.processing.bids_crosscheck import SCANS_TSV_DATE_FORMAT, existing_subject_ids

RAW_FILENAME_ID_CORRECTIONS_FILENAME = "raw_filename_id_corrections.json"

logger = logging.getLogger(__name__)

# Every .acq, not just "*_LongWalkV3Out.acq": a physiology file whose name no longer matches
# the expected shape (a " (1)" duplicate-copy suffix, a missing subject id, ...) must still be
# found, so it's reported as unparseable and listed in the crosscheck GUI's "Fix Filenames in
# Raw Folder" dialog -- instead of silently never being seen at all. Files that don't resolve
# to a subject are still never copied (see _convert_subject_physiology).
PHYSIOLOGY_GLOB = "*.acq"
BEHAVIOUR_GLOB = "*_behaviour.csv"
# Real REDCap exports are named "{ProjectName}_DATA_{YYYY-MM-DD}_{HHMM}.csv" (see
# longwalk3_dummy_data.py's _REDCAP_EXPORT_PATTERN) -- project name varies per study, unlike
# crane's single fixed project export name, so the glob only pins down the shared "_DATA_"
# marker.
GROUP_REDCAP_GLOB = "*_DATA_*.csv"
# What the crosscheck GUI's "Pull REDCap Data" button saves into the raw folder --
# `processing/redcap.redcap_output_path` names it "redcap_{study_id}_{crosscheck_id}.csv", and
# the LongwalkV3 crosscheck's crosscheck_id is its dataset name. The study id is only known to
# the GUI, so it's wildcarded here. Preferred over GROUP_REDCAP_GLOB: it's the latest data
# straight from the REDCap API, while a "_DATA_" file is a manual export that may be older.
REDCAP_CROSSCHECK_ID = "longwalkv3"
REDCAP_PULL_GLOB = f"redcap_*_{REDCAP_CROSSCHECK_ID}.csv"
# The REDCap column that identifies which subject a debrief row belongs to -- "study_id" here,
# not crane's "record_id".
DEBRIEF_ID_COLUMN = "study_id"
DATATYPE_FOLDER_NAME = "beh"
TASK_TOKEN = "task-longwalkv3"
# Physiology has no repeated-run concept (one recording per session) -- fixed placeholder run
# entity, same as crane's PHYSIOLOGY suffix.
PHYSIOLOGY_RUN_TOKEN = "run-001"
# Debrief has no repeated-run concept -- one REDCap row per subject per session.
DEBRIEF_RUN_TOKEN = "run-001"
# Session for a REDCap row without an event name (an export with no event column).
DEBRIEF_SESSION_NR = 1
# The REDCap export is long format: one row per subject per event. Events map to sessions in
# this order (from the reviewed shape manifest, 2026-11-18): baseline = ses-01, ...
REDCAP_EVENT_COLUMN = "redcap_event_name"
REDCAP_EVENT_SESSION_ORDER = (
    "baseline_arm_1",
    "followup_session_1_arm_1",
    "followup_session_2_arm_1",
)
# Identifying REDCap fields that are never copied into BIDS: names (participant, researcher),
# date of birth, consent signature dates, and REDCap's survey identifier (can be an email).
_DEBRIEF_IDENTIFYING_COLUMN_PATTERN = re.compile(
    r"(name|^dob$|_sign$|survey_identifier)", re.IGNORECASE
)
# Raw filenames carry a minute-precision date/time prefix (e.g. "202609161752") -- distinct
# from the separate, seconds+milliseconds format used by the "date"/"onset" column *inside*
# each behaviour/actor-log csv (see DATESTR_FORMAT).
FILENAME_DATESTR_FORMAT = "%Y%m%d%H%M"
DATESTR_FORMAT = "%Y%m%d%H%M%S%f"

# Real filenames are "{date}_{subject_id}_LongWalkV3Out.acq" -- subject_id can itself contain
# spaces (seen in longwalkv3_examples/), so it's captured greedily up to the fixed suffix.
_PHYSIOLOGY_FILENAME_PATTERN = re.compile(
    r"^(?P<date>\d+)_(?P<subject_id>.+)_LongWalkV3Out$", re.IGNORECASE
)
# Fallback for a physiology filename that doesn't match _PHYSIOLOGY_FILENAME_PATTERN (so its
# subject id can't be parsed) but a human has declared its subject id via a correction -- the
# leading minute-precision date (FILENAME_DATESTR_FORMAT) is still recoverable on its own,
# e.g. "202609161717__LongWalkV3Out" (id never typed) or "..._LongWalkV3Out (1)".
_PHYSIOLOGY_LEADING_DATE_PATTERN = re.compile(r"^(?P<date>\d{12})(?!\d)")
# Real behaviour/actor-log filenames are
# "{date}_{subject_id}_ses-{session_nr}_task-{city_label}_run-{n}_{bp_id}" -- except real
# behaviour.csv exports sometimes drop the underscore between the ses- and task- entities
# (e.g. "ses-01task-city1", seen in longwalkv3_examples/), so it's optional here.
_RAW_CSV_FILENAME_PATTERN = re.compile(
    r"^(?P<date>\d+)_(?P<subject_id>.+?)_ses-(?P<session_nr>\d+)_?task-(?P<city_label>.+?)_"
    r"run-\d+_(?P<bp_id>.+)$",
    re.IGNORECASE,
)


class EventsFileDictAttributes(TypedDict):
    date: datetime
    session_nr: int
    city_label: str
    bp_id: str


@dataclass
class ParsedPhysiologyFilename:
    subject_id: str
    date: datetime


def _normalize_subject_id(raw_subject_id: str) -> str:
    """The current export writes "sub-<id>" into raw filenames (older exports wrote a bare
    "<id>"); BIDS filenames add their own "sub-" prefix, so it's stripped here once."""
    if raw_subject_id.lower().startswith("sub-"):
        return raw_subject_id[len("sub-") :]
    return raw_subject_id


def parse_physiology_filename(file: Path) -> ParsedPhysiologyFilename | None:
    match = _PHYSIOLOGY_FILENAME_PATTERN.match(file.stem)
    if match is None:
        return None
    return ParsedPhysiologyFilename(
        subject_id=_normalize_subject_id(match.group("subject_id")),
        date=datetime.strptime(match.group("date"), FILENAME_DATESTR_FORMAT),
    )


@dataclass
class ParsedRawCsvFilename:
    subject_id: str
    date: datetime
    session_nr: int
    city_label: str
    bp_id: str


def parse_raw_csv_filename(file: Path) -> ParsedRawCsvFilename | None:
    match = _RAW_CSV_FILENAME_PATTERN.match(file.stem)
    if match is None:
        return None
    return ParsedRawCsvFilename(
        subject_id=_normalize_subject_id(match.group("subject_id")),
        date=datetime.strptime(match.group("date"), FILENAME_DATESTR_FORMAT),
        session_nr=int(match.group("session_nr")),
        city_label=match.group("city_label"),
        bp_id=match.group("bp_id"),
    )


def extract_subject_id(file: Path) -> str | None:
    parsed_physiology = parse_physiology_filename(file)
    if parsed_physiology is not None:
        return parsed_physiology.subject_id
    parsed_csv = parse_raw_csv_filename(file)
    return parsed_csv.subject_id if parsed_csv is not None else None


def load_raw_filename_id_corrections(bids_folder: Path) -> dict[str, str]:
    return bids.load_json_map(bids_folder / RAW_FILENAME_ID_CORRECTIONS_FILENAME)


def save_raw_filename_id_corrections(bids_folder: Path, corrections: dict[str, str]) -> None:
    bids.save_json_map(bids_folder / RAW_FILENAME_ID_CORRECTIONS_FILENAME, corrections)


def resolve_physiology_filename(
    file: Path, input_folder: Path, corrections: dict[str, str]
) -> ParsedPhysiologyFilename | None:
    """Like `parse_physiology_filename`, but checks a human-declared correction first (see
    `load_raw_filename_id_corrections`), keyed by the file's path relative to `input_folder`.
    A corrected file still needs a recoverable date: the full "{date}_..._LongWalkV3Out" shape
    if it matches, else just a leading 12-digit date (`_PHYSIOLOGY_LEADING_DATE_PATTERN`) -- so
    a filename whose subject id can't be parsed at all can still be fixed by a correction. A
    correction can override the subject id, not conjure a date out of an unrecognizable
    filename.
    """
    try:
        key = file.relative_to(input_folder).as_posix()
    except ValueError:
        key = file.name
    corrected_subject_id = corrections.get(key)
    if corrected_subject_id:
        match = _PHYSIOLOGY_FILENAME_PATTERN.match(
            file.stem
        ) or _PHYSIOLOGY_LEADING_DATE_PATTERN.match(file.stem)
        if match is None:
            return None
        return ParsedPhysiologyFilename(
            subject_id=corrected_subject_id,
            date=datetime.strptime(match.group("date"), FILENAME_DATESTR_FORMAT),
        )
    return parse_physiology_filename(file)


def resolve_raw_csv_filename(
    file: Path, input_folder: Path, corrections: dict[str, str]
) -> ParsedRawCsvFilename | None:
    """Like `parse_raw_csv_filename`, but checks a human-declared correction first -- same
    contract as `resolve_physiology_filename`, for the raw behaviour/actor-log csv side.
    """
    try:
        key = file.relative_to(input_folder).as_posix()
    except ValueError:
        key = file.name
    corrected_subject_id = corrections.get(key)
    if corrected_subject_id:
        match = _RAW_CSV_FILENAME_PATTERN.match(file.stem)
        if match is None:
            return None
        return ParsedRawCsvFilename(
            subject_id=corrected_subject_id,
            date=datetime.strptime(match.group("date"), FILENAME_DATESTR_FORMAT),
            session_nr=int(match.group("session_nr")),
            city_label=match.group("city_label"),
            bp_id=match.group("bp_id"),
        )
    return parse_raw_csv_filename(file)


def resolve_subject_id(file: Path, input_folder: Path, corrections: dict[str, str]) -> str | None:
    """Correction-aware analog of `extract_subject_id` -- used wherever a subject id needs to
    reflect a human's raw-filename correction (see `resolve_physiology_filename`/
    `resolve_raw_csv_filename`), not just what the raw filename itself parses to.
    """
    parsed_physiology = resolve_physiology_filename(file, input_folder, corrections)
    if parsed_physiology is not None:
        return parsed_physiology.subject_id
    parsed_csv = resolve_raw_csv_filename(file, input_folder, corrections)
    return parsed_csv.subject_id if parsed_csv is not None else None


def find_debrief_export(input_folder: Path, override: Path | None = None) -> Path | None:
    """Locate the shared REDCap group export -- same contract as crane_bids.find_debrief_export.
    `override`, given, is used as-is. Otherwise searches recursively for a REDCap API pull
    (`REDCAP_PULL_GLOB`) first, then falls back to a manual REDCap export (`GROUP_REDCAP_GLOB`).

    Public so `gui/longwalk3_bids_crosscheck_gui.py` can also call it with just `input_folder`,
    to show which file auto-detection currently resolves to.
    """
    if override is not None:
        return override

    for pattern in (REDCAP_PULL_GLOB, GROUP_REDCAP_GLOB):
        candidates = sorted(input_folder.rglob(pattern))
        if not candidates:
            continue
        if len(candidates) > 1:
            logger.warning(
                "Multiple files matching %r found -- using %s: %s",
                pattern,
                candidates[0].name,
                ", ".join(path.name for path in candidates),
            )
        return candidates[0]

    logger.warning(
        "No file matching %r or %r found in %s -- skipping debrief entirely",
        REDCAP_PULL_GLOB,
        GROUP_REDCAP_GLOB,
        input_folder,
    )
    return None


def load_debrief_export(input_folder: Path, override: Path | None = None) -> pd.DataFrame | None:
    """Read the shared REDCap group export. Unlike crane_bids.load_debrief_export, columns
    aren't filtered against a raw debrief schema yet -- see module docstring -- so every column
    the export has is kept as-is.
    """
    export_path = find_debrief_export(input_folder, override)
    if export_path is None:
        return None
    return pd.read_csv(export_path, dtype={DEBRIEF_ID_COLUMN: str})


def discover_raw_files_for_review(input_folder: Path) -> list[Path]:
    """Every raw physiology/behaviour/actor-log file in `input_folder`, read-only, regardless
    of whether it currently resolves to a subject id -- lets the crosscheck GUI's
    raw-filename correction dialog review or override any of them, not only ones that fail to
    parse. Every raw csv (not just BEHAVIOUR_GLOB's `*_behaviour.csv`) is included, since
    `get_all_dfs` pulls in a subject's sibling actor-location logs the same way. Every `.acq`
    is included too (`PHYSIOLOGY_GLOB`), including one whose name no longer matches the
    expected physiology filename shape.
    """
    return sorted(
        (*input_folder.rglob(PHYSIOLOGY_GLOB), *input_folder.rglob("*.csv")),
        key=lambda file: file.relative_to(input_folder).as_posix(),
    )


def explain_unparseable_filename(file: Path) -> str:
    """Plain-English reason `parse_physiology_filename`/`parse_raw_csv_filename` returned
    None, for the crosscheck GUI's raw-filename correction dialog.
    """
    if file.suffix.lower() == ".acq":
        return (
            'Doesn\'t match the expected "{date}_{subject_id}_LongWalkV3Out" physiology '
            "filename pattern."
        )
    return (
        "Doesn't match the expected \"{date}_{subject_id}_ses-{session_nr}_"
        'task-{city_label}_run-{n}_{bp_id}" raw csv filename pattern.'
    )


def is_header(fields):
    return fields[0].strip().lower() in {"date", "timestamp", "datetime", "timestamphhmm"}


def _fit_row_to_header(fields: list[str], width: int) -> list[str]:
    """Ragged rows seen in the real export: BP_PhoneAlerts_C's free-text `message` holds
    unquoted commas (row wider than the header -- the overflow is joined back into the last
    column), and BP_HeatmapManager_C fills its corner-vector columns on the first row only
    (row narrower -- padded with empty cells)."""
    if len(fields) > width:
        return [*fields[: width - 1], ",".join(fields[width - 1 :])]
    return fields + [""] * (width - len(fields))


def csv_to_df_compress_header(csv_fn_in: Path) -> pd.DataFrame:
    """The first non-blank line is the header. The current export repeats it once per actor
    instance at the top of the file -- identical repeats are dropped wherever they appear. A
    *different* header line further down (older exports) starts a new chunk. A header-only
    file gives an empty dataframe with that header's columns."""
    with open(csv_fn_in, encoding="utf-8-sig") as f:
        lines = [line.strip() for line in f if line.strip()]
    if not lines:
        logger.error("Empty datafile %s", csv_fn_in)
        raise ValueError(f"Empty datafile {csv_fn_in}")

    chunks: list[pd.DataFrame] = []
    header = [cell.strip() for cell in lines[0].split(",")]
    rows: list[list[str]] = []
    for line in lines[1:]:
        raw_fields = line.split(",")
        fields = [cell.strip() for cell in raw_fields]
        if fields == header:
            continue
        if is_header(fields):
            chunks.append(pd.DataFrame(rows, columns=pd.Index(header)))
            header, rows = fields, []
            continue
        # Fit before stripping, so an overflow joined back keeps its own spacing.
        rows.append([cell.strip() for cell in _fit_row_to_header(raw_fields, len(header))])
    chunks.append(pd.DataFrame(rows, columns=pd.Index(header)))

    return pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]


_UNREAL_SECONDS_DIGITS = 14  # yyyyMMddHHmmss
BEHAVIOUR_HHMM_COLUMN = "TimeStampHHmm"


def parse_unreal_datetimes(values: pd.Series) -> pd.Series:
    """Unreal's digit timestamps: yyyyMMddHHmmss followed by milliseconds.

    DECISION D6 (open, docs/longwalk3_plan.md): about 1 in 4 real cells is shorter than 17
    digits. Working assumption: milliseconds are written without zero-padding, so whatever
    follows the 14 seconds digits is read as an integer number of milliseconds ("...52" is
    52 ms, not 520 ms as a plain `%f` parse would give). Anything else becomes NaT.
    """
    text = values.astype("string").str.strip()
    valid = text.str.fullmatch(r"\d{14,17}").fillna(False).astype(bool)
    seconds = pd.to_datetime(
        text.str[:_UNREAL_SECONDS_DIGITS], format="%Y%m%d%H%M%S", errors="coerce"
    )
    milliseconds = pd.Series(
        pd.to_numeric(text.str[_UNREAL_SECONDS_DIGITS:], errors="coerce"), index=text.index
    ).fillna(0)
    parsed = seconds + pd.to_timedelta(milliseconds, unit="ms")
    return parsed.where(valid)


def parse_behaviour_hhmm(values: pd.Series, run_date: datetime) -> pd.Series:
    """behaviour.csv's `TimeStampHHmm` carries hours and minutes only -- the day comes from
    the run's raw filename date. Anything not 3-4 digits becomes NaT."""
    text = values.astype("string").str.strip().str.zfill(4)
    valid = text.str.fullmatch(r"\d{4}").fillna(False).astype(bool)
    parsed = pd.to_datetime(
        f"{run_date:%Y%m%d}" + text.where(valid, ""), format="%Y%m%d%H%M", errors="coerce"
    )
    return parsed.where(valid)


def get_all_dfs(
    subject_id_in: str, data_folder_in: Path, corrections: dict[str, str] | None = None
) -> list[pd.DataFrame]:
    """`corrections` (see `load_raw_filename_id_corrections`) is checked per file via
    `resolve_raw_csv_filename`. Candidates are still pre-filtered by a `subject_id_in`
    substring glob (as before) for the common case, plus any file a correction explicitly
    points at `subject_id_in` -- covers a raw filename whose own text doesn't contain
    `subject_id_in` at all, without scanning (and re-warning about) every csv in the folder on
    every subject's call.
    """
    corrections = corrections or {}
    corrected_for_subject = {
        data_folder_in / key
        for key, corrected_subject_id in corrections.items()
        if corrected_subject_id == subject_id_in
    }
    candidate_files = set(data_folder_in.rglob(f"*{subject_id_in}*.csv")) | corrected_for_subject

    df_list_out = []
    for file in sorted(candidate_files):
        parsed = resolve_raw_csv_filename(file, data_folder_in, corrections)
        if parsed is None:
            logger.warning(
                "Skipping %s -- doesn't match the expected raw behaviour/actor-log filename shape.",
                file,
            )
            continue
        if parsed.subject_id != subject_id_in:
            # The substring glob above can still admit a different subject whose id happens
            # to contain subject_id_in.
            continue

        df_out = csv_to_df_compress_header(file)
        attributes = EventsFileDictAttributes(
            date=parsed.date,
            session_nr=parsed.session_nr,
            city_label=parsed.city_label,
            # Real actor-log suffixes carry underscores (e.g. "BP_NPC_C") that BP_ACTOR_IDS'
            # own entries don't (e.g. "BPNPCC") -- joined back together the same way
            # get_bp_id used to.
            bp_id=parsed.bp_id.replace("_", ""),
        )
        df_out.attrs = cast(dict[Hashable, Any], attributes)
        df_list_out.append(df_out)

    return df_list_out


BP_ACTOR_IDS = [
    "BPAudioCueTriggerC",
    "BPBirdsFlyingC",
    "BPHeatmapManagerC",
    "BPNPCC",
    "BPPanicAttackManagerC",
    "BPPanicCooldownTimersManagerC",
    "BPPanicTriggerC",
    "BPPhoneAlertsC",
    "BPPhoneC",
    "BPSerialComManagerC",
    "ThreatLevelMarkerNewC",
]


def build_longwalkv3_raw_session_events_behav_file_schema() -> pa.DataFrameSchema:
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
            f"trigger_{BP_ACTOR_ID}": pandera_defaults.optional_str_col()
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
    """One events.tsv per (session, city, run) -- see module docstring for how a "run" is
    identified and numbered.
    """
    runs: dict[tuple[int, datetime], list[pd.DataFrame]] = {}
    city_label_by_run: dict[tuple[int, datetime], str] = {}

    for df in dfs_by_date:
        df.rename(
            columns={"TimeStamp": "time_stamp", "date": "time_stamp", "datetime": "time_stamp"},
            inplace=True,
        )

        if BEHAVIOUR_HHMM_COLUMN in df.columns:
            event_times = parse_behaviour_hhmm(
                cast(pd.Series, df[BEHAVIOUR_HHMM_COLUMN]), df.attrs["date"]
            )
        else:
            event_times = parse_unreal_datetimes(cast(pd.Series, df["time_stamp"]))
        df["onset"] = (event_times - df.attrs["date"]).dt.total_seconds()
        df = df.add_suffix(f"_{df.attrs['bp_id']}")

        # Rename all cols according the class ID

        df.rename(columns={f"onset_{df.attrs['bp_id']}": "onset"}, inplace=True)

        # Extract float values from Unreal world location
        for BP_ACTOR_ID in BP_ACTOR_IDS:
            word_location_df = df.filter(regex=f"^worldLocation_{BP_ACTOR_ID}$")
            if word_location_df.empty:
                continue

            col_name = word_location_df.columns[0]
            parts = word_location_df[col_name].str.extract(
                r"X=([\-\d.]+)\s+Y=([\-\d.]+)\sZ=([\-\d.]+)"
            )
            parts.columns = [f"{col_name}_x", f"{col_name}_y", f"{col_name}_z"]
            parts = parts.astype(float)
            df[parts.columns] = parts
            df = df.drop(columns=[str(col_name)])
            break

        run_key = (df.attrs["session_nr"], df.attrs["date"])
        runs.setdefault(run_key, []).append(df)
        city_label_by_run.setdefault(run_key, df.attrs["city_label"])

    runs_by_session: dict[int, list[tuple[int, datetime]]] = {}
    for run_key in runs:
        runs_by_session.setdefault(run_key[0], []).append(run_key)

    session_dfs_by_fn_out_dict: dict[str, pd.DataFrame] = {}
    # Create output filenames
    for session_nr, run_keys in runs_by_session.items():
        for run_nr, run_key in enumerate(sorted(run_keys, key=lambda k: k[1]), start=1):
            combined_df_out = pd.concat(runs[run_key], ignore_index=True)
            combined_df_out.attrs["date"] = run_key[1]
            combined_df_out["duration"] = np.nan
            target_fn_out = bids.build_bids_filename(
                subject_id_in,
                _session_token(session_nr),
                TASK_TOKEN,
                f"run-{run_nr:03d}",
                "events",
                ".tsv",
                acq=city_label_by_run[run_key],
            )
            session_dfs_by_fn_out_dict[target_fn_out] = combined_df_out

    return session_dfs_by_fn_out_dict


_EVENTS_FILENAME_SESSION_PATTERN = re.compile(r"_ses-(?P<session_nr>\d+)_")


def _session_nr_from_events_filename(filename: str) -> int:
    match = _EVENTS_FILENAME_SESSION_PATTERN.search(filename)
    assert match is not None, f"{filename!r} isn't a combine_events_df_files output filename"
    return int(match.group("session_nr"))


_RAW_SESSION_FOLDER_PATTERN = re.compile(r"^ses[-_ ]?(?P<session_nr>\d+)$", re.IGNORECASE)


def _session_nr_from_raw_folder(file: Path, input_folder: Path) -> int | None:
    """Session number of the raw session folder `file` sits in ("ses-01", "ses_01", ...), or
    None for a file outside any session folder (legacy flat layout)."""
    try:
        parts = file.relative_to(input_folder).parts[:-1]
    except ValueError:
        return None
    for part in parts:
        match = _RAW_SESSION_FOLDER_PATTERN.match(part)
        if match:
            return int(match.group("session_nr"))
    return None


# TODO: Move to BIDS??
def _session_token(session_nr: int) -> str:
    return f"ses-{session_nr:02d}"


def _datatype_folder(output_folder: Path, subject_id: str, session_nr: int) -> Path:
    return bids.datatype_folder(
        output_folder, subject_id, _session_token(session_nr), DATATYPE_FOLDER_NAME
    )


def _scans_tsv_path(output_folder: Path, subject_id: str, session_nr: int) -> Path:
    return bids.scans_tsv_path(output_folder, subject_id, _session_token(session_nr))


def _convert_subject_physiology(
    subject_id: str, input_folder: Path, output_folder: Path, corrections: dict[str, str]
) -> list[Path]:
    """Copies one .acq per session, session number inferred from chronological order across
    this subject's physiology files -- see module docstring. `corrections` (see
    `load_raw_filename_id_corrections`) lets a human-declared subject id override a raw
    filename's own parse for this subject, same as `get_all_dfs` does for events.
    """
    parsed_by_file = {
        file: parsed
        for file in sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
        if (parsed := resolve_physiology_filename(file, input_folder, corrections)) is not None
        and parsed.subject_id == subject_id
    }
    ordered_files = sorted(parsed_by_file, key=lambda file: parsed_by_file[file].date)
    # Current export: each .acq sits in its raw session folder ("ses-02", or "ses_01" as seen
    # in real data), so that folder decides the session. Legacy flat layout (no session
    # folders): fall back to chronological order, as before.
    folder_session_nrs = [_session_nr_from_raw_folder(f, input_folder) for f in ordered_files]
    if all(nr is not None for nr in folder_session_nrs):
        session_nrs = cast(list[int], folder_session_nrs)
    else:
        session_nrs = list(range(1, len(ordered_files) + 1))

    written: list[Path] = []
    for session_nr, acq_file in zip(session_nrs, ordered_files, strict=True):
        parsed = parsed_by_file[acq_file]
        folder = _datatype_folder(output_folder, subject_id, session_nr)
        # Two .acq files in one session folder are both kept ("-dup2"), for the crosscheck to
        # resolve -- never silently overwritten.
        destination = bids.resolve_collision(
            lambda suffix, folder=folder, session_nr=session_nr: (
                folder
                / bids.build_bids_filename(
                    subject_id,
                    _session_token(session_nr),
                    TASK_TOKEN,
                    PHYSIOLOGY_RUN_TOKEN,
                    suffix,
                    ".acq",
                )
            ),
            "physio",
        )
        bids.copy_scan(
            acq_file,
            destination,
            _scans_tsv_path(output_folder, subject_id, session_nr),
            parsed.date.strftime(SCANS_TSV_DATE_FORMAT),
        )
        written.append(destination)

    return written


def _convert_subject_events(
    subject_id: str, input_folder: Path, output_folder: Path, corrections: dict[str, str]
) -> list[Path]:
    dfs = get_all_dfs(subject_id, input_folder, corrections)
    events_by_filename = combine_events_df_files(subject_id, dfs)

    written: list[Path] = []
    for filename, events_df in events_by_filename.items():
        session_nr = _session_nr_from_events_filename(filename)
        destination = _datatype_folder(output_folder, subject_id, session_nr) / filename
        events_df.to_csv(destination, sep="\t", index=False)

        run_start = events_df.attrs["date"] if not events_df.empty else None
        acq_time = (
            run_start.strftime(SCANS_TSV_DATE_FORMAT)
            if isinstance(run_start, datetime)
            else "nodate"
        )
        relative_name = destination.relative_to(
            _scans_tsv_path(output_folder, subject_id, session_nr).parent
        ).as_posix()
        bids.append_scan_row(
            _scans_tsv_path(output_folder, subject_id, session_nr), relative_name, acq_time
        )
        written.append(destination)

    return written


DEBRIEF_FILENAME_GLOB = "*_acq-debrief_*_beh.tsv"


def _has_debrief_file(output_folder: Path, subject_id: str) -> bool:
    subject_folder = output_folder / f"sub-{subject_id}"
    return subject_folder.is_dir() and any(subject_folder.rglob(DEBRIEF_FILENAME_GLOB))


def _debrief_acq_date(output_folder: Path, subject_id: str, session_nr: int) -> str:
    """Best-effort acquisition date for a session's debrief file -- that session's own first
    scan date if there is one, "nodate" otherwise. Same fallback contract as
    crane_bids._existing_acq_date.
    """
    rows = bids.read_scans_tsv_rows(_scans_tsv_path(output_folder, subject_id, session_nr))
    return rows[0]["acq_time"] if rows else "nodate"


def debrief_session_nrs(debrief_df: pd.DataFrame) -> dict[str, int]:
    """REDCap event name -> session number. The export is long format, one row per subject per
    event, and events map to sessions in the order REDCAP_EVENT_SESSION_ORDER lists them;
    events not listed there follow, in order of first appearance in the export. An export
    without an event column is treated as one row per subject for ses-01."""
    if REDCAP_EVENT_COLUMN not in debrief_df.columns:
        return {}
    seen = list(dict.fromkeys(debrief_df[REDCAP_EVENT_COLUMN].dropna().astype(str)))
    ordered = [e for e in REDCAP_EVENT_SESSION_ORDER if e in seen]
    ordered += [e for e in seen if e not in ordered]
    return {event: n for n, event in enumerate(ordered, start=1)}


def _is_identifying_debrief_column(column: str) -> bool:
    if column in (DEBRIEF_ID_COLUMN, REDCAP_EVENT_COLUMN):
        return False
    return bool(_DEBRIEF_IDENTIFYING_COLUMN_PATTERN.search(column))


def _debrief_answer_columns(debrief_df: pd.DataFrame) -> list[str]:
    """Columns that hold actual answers -- not the id/event columns or a "<form>_complete"
    status. A REDCap event row with none of these filled was never filled in."""
    structural = {DEBRIEF_ID_COLUMN, REDCAP_EVENT_COLUMN}
    return [
        c
        for c in debrief_df.columns
        if c not in structural
        and not c.endswith("_complete")
        and not _is_identifying_debrief_column(c)
    ]


def _is_blank(value: object) -> bool:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return True
    return not str(value).strip()


def _convert_subject_debrief(
    subject_id: str, debrief_df: pd.DataFrame, output_folder: Path
) -> list[Path]:
    """Writes this subject's REDCap rows as one
    `sub-XXX_ses-NN_task-longwalkv3_acq-debrief_run-001_beh.tsv` per session (the same
    acq-debrief/`_beh` convention crane_bids.py uses), session taken from the row's REDCap event
    (see debrief_session_nrs). Rows with no answers at all are skipped, and identifying columns
    (names, date of birth, signatures, survey identifier) are never copied into BIDS. Returns
    the written paths -- empty if the export has no filled-in row for this subject.
    """
    subject_rows = debrief_df[debrief_df[DEBRIEF_ID_COLUMN] == subject_id]
    if subject_rows.empty:
        return []

    session_by_event = debrief_session_nrs(debrief_df)
    answer_columns = _debrief_answer_columns(debrief_df)
    kept_columns = [c for c in debrief_df.columns if not _is_identifying_debrief_column(c)]

    written: list[Path] = []
    for _, row in subject_rows.iterrows():
        if all(_is_blank(row[c]) for c in answer_columns):
            continue
        event = row.get(REDCAP_EVENT_COLUMN)
        session_nr = session_by_event.get(str(event), DEBRIEF_SESSION_NR)
        destination = _datatype_folder(output_folder, subject_id, session_nr) / (
            bids.build_bids_filename(
                subject_id,
                _session_token(session_nr),
                TASK_TOKEN,
                DEBRIEF_RUN_TOKEN,
                "beh",
                ".tsv",
                acq="debrief",
            )
        )
        pd.DataFrame([[row[c] for c in kept_columns]], columns=pd.Index(kept_columns)).to_csv(
            destination, sep="\t", index=False
        )

        scans_tsv_path = _scans_tsv_path(output_folder, subject_id, session_nr)
        relative_name = destination.relative_to(scans_tsv_path.parent).as_posix()
        acq_date = _debrief_acq_date(output_folder, subject_id, session_nr)
        bids.append_scan_row(scans_tsv_path, relative_name, acq_date)
        written.append(destination)
    return written


# Raw-layout problems found at conversion time, which the BIDS folder alone can no longer show
# (e.g. a "ses_01" raw folder spelling) -- read back by the crosscheck GUI's subject issues.
RAW_AUDIT_FILENAME = "longwalkv3_raw_audit.json"
_RAW_RUN_FOLDER_PATTERN = re.compile(r"^run-\d+$", re.IGNORECASE)


def audit_raw_subject_files(files: list[Path], input_folder: Path) -> list[str]:
    """Problems with how one subject's raw files are laid out: a session folder not spelled
    "ses-NN", a csv whose filename session disagrees with its folder, and restarted-run
    subfolders (run-001/, run-002/) -- one aborted attempt the crosscheck should resolve."""
    problems: list[str] = []

    def add(problem: str) -> None:
        if problem not in problems:
            problems.append(problem)

    for file in files:
        try:
            parts = file.relative_to(input_folder).parts[:-1]
        except ValueError:
            continue
        folder_session_nr = None
        for part in parts:
            match = _RAW_SESSION_FOLDER_PATTERN.match(part)
            if match:
                folder_session_nr = int(match.group("session_nr"))
                expected = _session_token(folder_session_nr)
                if part != expected:
                    add(f"Raw session folder '{part}' should be named '{expected}'")
            elif _RAW_RUN_FOLDER_PATTERN.match(part) and folder_session_nr is not None:
                add(
                    f"{_session_token(folder_session_nr)}: raw data has restarted-run "
                    "subfolders (run-00N) -- keep the complete run, remove the aborted one"
                )
        parsed = parse_raw_csv_filename(file) if file.suffix.lower() == ".csv" else None
        if parsed and folder_session_nr is not None and parsed.session_nr != folder_session_nr:
            add(
                f"{file.name} sits in raw folder {_session_token(folder_session_nr)} but its "
                f"name says {_session_token(parsed.session_nr)}"
            )
    return problems


def load_raw_audit(bids_folder: Path) -> dict[str, list[str]]:
    path = bids_folder / RAW_AUDIT_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read %s -- ignoring raw audit", path)
        return {}


def _save_raw_audit(bids_folder: Path, audit: dict[str, list[str]]) -> None:
    path = bids_folder / RAW_AUDIT_FILENAME
    path.write_text(json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8")


@dataclass
class LongWalkV3ConversionSummary:
    """Everything a caller (the CLI's `main()`) needs to report what a
    `convert_longwalkv3_to_bids()` call actually did. Warnings/skips are also emitted via the
    module `logger` as they happen -- this is the end-of-run rollup.
    """

    new_subject_ids: list[str] = field(default_factory=list)
    subject_physiology: dict[str, list[Path]] = field(default_factory=dict)
    subject_events: dict[str, list[Path]] = field(default_factory=dict)
    subject_debrief: dict[str, list[Path]] = field(default_factory=dict)
    already_converted: set[str] = field(default_factory=set)
    unparseable_files: list[Path] = field(default_factory=list)
    unmatched_debrief: list[str] = field(default_factory=list)
    backfilled_debrief_ids: list[str] = field(default_factory=list)


def convert_longwalkv3_to_bids(
    input_folder: Path, output_folder: Path, debrief_export: Path | None = None
) -> LongWalkV3ConversionSummary:
    """Core, UI-agnostic conversion logic -- see module docstring for the output layout.

    `debrief_export`, if given, overrides auto-detection of the shared REDCap group export --
    for when there's more than one file matching `GROUP_REDCAP_GLOB` in `input_folder`.
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    already_converted = existing_subject_ids(output_folder)
    raw_filename_corrections = load_raw_filename_id_corrections(output_folder)

    physiology_files = sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
    behaviour_files = sorted(input_folder.rglob(BEHAVIOUR_GLOB))
    debrief_df = load_debrief_export(input_folder, debrief_export)

    all_subject_ids: set[str] = set()
    unparseable_files: list[Path] = []
    for file in (*physiology_files, *behaviour_files):
        subject_id = resolve_subject_id(file, input_folder, raw_filename_corrections)
        if subject_id is None:
            unparseable_files.append(file)
            continue
        all_subject_ids.add(subject_id)

    if unparseable_files:
        logger.warning(
            "Could not extract a subject id from %d filename(s) -- skipped entirely, not "
            "copied: %s",
            len(unparseable_files),
            ", ".join(f.name for f in unparseable_files),
        )

    new_subject_ids = sorted(all_subject_ids - already_converted)
    skipped_subject_ids = sorted(all_subject_ids & already_converted)

    raw_files_by_subject: dict[str, list[Path]] = {}
    for file in discover_raw_files_for_review(input_folder):
        subject_id = resolve_subject_id(file, input_folder, raw_filename_corrections)
        if subject_id in new_subject_ids:
            raw_files_by_subject.setdefault(subject_id, []).append(file)
    raw_audit = load_raw_audit(output_folder)
    for subject_id in new_subject_ids:
        raw_audit[subject_id] = audit_raw_subject_files(
            raw_files_by_subject.get(subject_id, []), input_folder
        )
    if new_subject_ids:
        _save_raw_audit(output_folder, raw_audit)

    subject_physiology: dict[str, list[Path]] = {}
    subject_events: dict[str, list[Path]] = {}
    for subject_id in new_subject_ids:
        subject_physiology[subject_id] = _convert_subject_physiology(
            subject_id, input_folder, output_folder, raw_filename_corrections
        )
        subject_events[subject_id] = _convert_subject_events(
            subject_id, input_folder, output_folder, raw_filename_corrections
        )

    if skipped_subject_ids:
        logger.info(
            "Skipped %d subject(s) already converted: %s",
            len(skipped_subject_ids),
            ", ".join(skipped_subject_ids),
        )

    # Debrief backfill: an already-converted subject still gets reconsidered for debrief
    # specifically if they don't have one yet (e.g. a previous run's export didn't match
    # them) -- same philosophy as crane_bids.convert_crane_to_bids.
    backfill_candidate_ids = sorted(
        sid for sid in already_converted if not _has_debrief_file(output_folder, sid)
    )
    debrief_candidate_ids = sorted(set(new_subject_ids) | set(backfill_candidate_ids))

    subject_debrief: dict[str, list[Path]] = {}
    backfilled_debrief_ids: list[str] = []
    if debrief_df is not None:
        for subject_id in debrief_candidate_ids:
            destinations = _convert_subject_debrief(subject_id, debrief_df, output_folder)
            if destinations:
                subject_debrief[subject_id] = destinations
                if subject_id in backfill_candidate_ids:
                    backfilled_debrief_ids.append(subject_id)

    if backfilled_debrief_ids:
        logger.info(
            "Backfilled debrief for %d already-converted subject(s) that didn't have one yet: %s",
            len(backfilled_debrief_ids),
            ", ".join(backfilled_debrief_ids),
        )

    unmatched_debrief = [sid for sid in debrief_candidate_ids if sid not in subject_debrief]
    if debrief_df is not None and unmatched_debrief:
        logger.warning(
            "No debrief row found for %d subject(s) -- check whether their %s in %r actually "
            "matches the ID in their filenames: %s",
            len(unmatched_debrief),
            DEBRIEF_ID_COLUMN,
            GROUP_REDCAP_GLOB,
            ", ".join(unmatched_debrief),
        )

    logger.info(
        "Added %d new subject folder(s) to %s: %d physiology, %d events, %d debrief file(s) "
        "(%d of those backfilled for already-converted subjects).",
        len(new_subject_ids),
        output_folder,
        sum(len(paths) for paths in subject_physiology.values()),
        sum(len(paths) for paths in subject_events.values()),
        sum(len(paths) for paths in subject_debrief.values()),
        len(backfilled_debrief_ids),
    )

    return LongWalkV3ConversionSummary(
        new_subject_ids=new_subject_ids,
        subject_physiology=subject_physiology,
        subject_events=subject_events,
        subject_debrief=subject_debrief,
        already_converted=already_converted,
        unparseable_files=unparseable_files,
        unmatched_debrief=unmatched_debrief,
        backfilled_debrief_ids=backfilled_debrief_ids,
    )


def print_longwalkv3_conversion_summary(summary: LongWalkV3ConversionSummary) -> None:
    """Rich console/table rendering of a `LongWalkV3ConversionSummary`, factored out so the
    CLI's `main()` stays a thin wrapper around `convert_longwalkv3_to_bids()`.
    """
    console = Console()
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        console.print(
            "No new subjects found -- everything in the source folder is already converted."
        )
        return

    table = Table(title="LongwalkV3 raw -> BIDS conversion")
    table.add_column("Subject ID")
    table.add_column("Physiology")
    table.add_column("Events")
    table.add_column("Debrief")
    for subject_id in summary.new_subject_ids:
        table.add_row(
            subject_id,
            bids.summary_table_cell(summary.subject_physiology, subject_id),
            bids.summary_table_cell(summary.subject_events, subject_id),
            bids.summary_table_cell(summary.subject_debrief, subject_id),
        )
    for subject_id in summary.backfilled_debrief_ids:
        table.add_row(
            f"{subject_id} (backfill)",
            "(already converted)",
            "(already converted)",
            bids.summary_table_cell(summary.subject_debrief, subject_id),
        )
    console.print(table)
