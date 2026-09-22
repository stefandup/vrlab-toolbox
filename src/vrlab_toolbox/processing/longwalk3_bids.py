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
- REDCap debrief backfill (like crane's) isn't implemented yet -- longwalk3_debrief_behaviour.py
  is still a schema stub with no group-export glob wired up.
"""

import logging
import re
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict, cast

import pandas as pd
import pandera.pandas as pa
from rich.console import Console
from rich.table import Table

from vrlab_toolbox.processing import bids, pandera_defaults
from vrlab_toolbox.processing.bids import build_base_bids_events_schema
from vrlab_toolbox.processing.bids_crosscheck import existing_subject_ids

logger = logging.getLogger(__name__)

PHYSIOLOGY_GLOB = "*_LongWalkV3Out.acq"
BEHAVIOUR_GLOB = "*_behaviour.csv"
DATATYPE_FOLDER_NAME = "beh"
TASK_TOKEN = "task-longwalkv3"
# Physiology has no repeated-run concept (one recording per session) -- fixed placeholder run
# entity, same as crane's PHYSIOLOGY suffix.
PHYSIOLOGY_RUN_TOKEN = "run-001"
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


def parse_physiology_filename(file: Path) -> ParsedPhysiologyFilename | None:
    match = _PHYSIOLOGY_FILENAME_PATTERN.match(file.stem)
    if match is None:
        return None
    return ParsedPhysiologyFilename(
        subject_id=match.group("subject_id"),
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
        subject_id=match.group("subject_id"),
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
        parsed = parse_raw_csv_filename(file)
        if parsed is None:
            logger.warning(
                "Skipping %s -- doesn't match the expected raw behaviour/actor-log filename shape.",
                file,
            )
            continue
        if parsed.subject_id != subject_id_in:
            # The glob above matches on substring, so a different subject whose id happens to
            # contain subject_id_in would otherwise slip in here too.
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
    """One events.tsv per (session, city, run) -- see module docstring for how a "run" is
    identified and numbered.
    """
    runs: dict[tuple[int, datetime], list[pd.DataFrame]] = {}
    city_label_by_run: dict[tuple[int, datetime], str] = {}

    for df in dfs_by_date:
        df.rename(
            columns={"TimeStamp": "onset", "date": "onset", "datetime": "onset"}, inplace=True
        )
        df["onset"] = pd.to_datetime(df["onset"], format=DATESTR_FORMAT, errors="coerce")
        df = df.add_suffix(f"_{df.attrs['bp_id']}")
        df.rename(columns={f"onset_{df.attrs['bp_id']}": "onset"}, inplace=True)

        # Extract float values from Unreal world location -- at most one BP_ACTOR_IDS entry
        # ever matches a single source file (a source file is always one actor's own log, or
        # behaviour.csv with no location columns at all).
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
            df = df.drop(columns=col_name)
            break

        run_key = (df.attrs["session_nr"], df.attrs["date"])
        runs.setdefault(run_key, []).append(df)
        city_label_by_run.setdefault(run_key, df.attrs["city_label"])

    runs_by_session: dict[int, list[tuple[int, datetime]]] = {}
    for run_key in runs:
        runs_by_session.setdefault(run_key[0], []).append(run_key)

    session_dfs_by_fn_out_dict: dict[str, pd.DataFrame] = {}
    for session_nr, run_keys in runs_by_session.items():
        for run_nr, run_key in enumerate(sorted(run_keys, key=lambda k: k[1]), start=1):
            combined_df_out = pd.concat(runs[run_key], ignore_index=True)
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


def _session_token(session_nr: int) -> str:
    return f"ses-{session_nr:02d}"


def _datatype_folder(output_folder: Path, subject_id: str, session_nr: int) -> Path:
    return bids.datatype_folder(
        output_folder, subject_id, _session_token(session_nr), DATATYPE_FOLDER_NAME
    )


def _scans_tsv_path(output_folder: Path, subject_id: str, session_nr: int) -> Path:
    return bids.scans_tsv_path(output_folder, subject_id, _session_token(session_nr))


def _convert_subject_physiology(
    subject_id: str, input_folder: Path, output_folder: Path
) -> list[Path]:
    """Copies one .acq per session, session number inferred from chronological order across
    this subject's physiology files -- see module docstring.
    """
    parsed_by_file = {
        file: parsed
        for file in sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
        if (parsed := parse_physiology_filename(file)) is not None
        and parsed.subject_id == subject_id
    }
    ordered_files = sorted(parsed_by_file, key=lambda file: parsed_by_file[file].date)

    written: list[Path] = []
    for session_nr, acq_file in enumerate(ordered_files, start=1):
        parsed = parsed_by_file[acq_file]
        destination = _datatype_folder(output_folder, subject_id, session_nr) / (
            bids.build_bids_filename(
                subject_id,
                _session_token(session_nr),
                TASK_TOKEN,
                PHYSIOLOGY_RUN_TOKEN,
                "physio",
                ".acq",
            )
        )
        bids.copy_scan(
            acq_file,
            destination,
            _scans_tsv_path(output_folder, subject_id, session_nr),
            parsed.date.isoformat(),
        )
        written.append(destination)

    return written


def _convert_subject_events(subject_id: str, input_folder: Path, output_folder: Path) -> list[Path]:
    dfs = get_all_dfs(subject_id, input_folder)
    events_by_filename = combine_events_df_files(subject_id, dfs)

    written: list[Path] = []
    for filename, events_df in events_by_filename.items():
        session_nr = _session_nr_from_events_filename(filename)
        destination = _datatype_folder(output_folder, subject_id, session_nr) / filename
        events_df.to_csv(destination, sep="\t", index=False)

        onset_min = events_df["onset"].min() if not events_df.empty else None
        # isinstance rather than pd.notna: also excludes pd.NaT (an all-unparseable "onset"
        # column), which isn't a pd.Timestamp instance either.
        acq_time = onset_min.isoformat() if isinstance(onset_min, pd.Timestamp) else "nodate"
        relative_name = destination.relative_to(
            _scans_tsv_path(output_folder, subject_id, session_nr).parent
        ).as_posix()
        bids.append_scan_row(
            _scans_tsv_path(output_folder, subject_id, session_nr), relative_name, acq_time
        )
        written.append(destination)

    return written


@dataclass
class LongWalkV3ConversionSummary:
    """Everything a caller (the CLI's `main()`) needs to report what a
    `convert_longwalkv3_to_bids()` call actually did. Warnings/skips are also emitted via the
    module `logger` as they happen -- this is the end-of-run rollup.
    """

    new_subject_ids: list[str] = field(default_factory=list)
    subject_physiology: dict[str, list[Path]] = field(default_factory=dict)
    subject_events: dict[str, list[Path]] = field(default_factory=dict)
    already_converted: set[str] = field(default_factory=set)
    unparseable_files: list[Path] = field(default_factory=list)


def convert_longwalkv3_to_bids(
    input_folder: Path, output_folder: Path
) -> LongWalkV3ConversionSummary:
    """Core, UI-agnostic conversion logic -- see module docstring for the output layout."""
    output_folder.mkdir(parents=True, exist_ok=True)
    already_converted = existing_subject_ids(output_folder)

    physiology_files = sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
    behaviour_files = sorted(input_folder.rglob(BEHAVIOUR_GLOB))

    all_subject_ids: set[str] = set()
    unparseable_files: list[Path] = []
    for file in (*physiology_files, *behaviour_files):
        subject_id = extract_subject_id(file)
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

    subject_physiology: dict[str, list[Path]] = {}
    subject_events: dict[str, list[Path]] = {}
    for subject_id in new_subject_ids:
        subject_physiology[subject_id] = _convert_subject_physiology(
            subject_id, input_folder, output_folder
        )
        subject_events[subject_id] = _convert_subject_events(
            subject_id, input_folder, output_folder
        )

    if skipped_subject_ids:
        logger.info(
            "Skipped %d subject(s) already converted: %s",
            len(skipped_subject_ids),
            ", ".join(skipped_subject_ids),
        )

    logger.info(
        "Added %d new subject folder(s) to %s: %d physiology, %d events file(s).",
        len(new_subject_ids),
        output_folder,
        sum(len(paths) for paths in subject_physiology.values()),
        sum(len(paths) for paths in subject_events.values()),
    )

    return LongWalkV3ConversionSummary(
        new_subject_ids=new_subject_ids,
        subject_physiology=subject_physiology,
        subject_events=subject_events,
        already_converted=already_converted,
        unparseable_files=unparseable_files,
    )


def print_longwalkv3_conversion_summary(summary: LongWalkV3ConversionSummary) -> None:
    """Rich console/table rendering of a `LongWalkV3ConversionSummary`, factored out so the
    CLI's `main()` stays a thin wrapper around `convert_longwalkv3_to_bids()`.
    """
    console = Console()
    if not summary.new_subject_ids:
        console.print(
            "No new subjects found -- everything in the source folder is already converted."
        )
        return

    table = Table(title="LongwalkV3 raw -> BIDS conversion")
    table.add_column("Subject ID")
    table.add_column("Physiology")
    table.add_column("Events")
    for subject_id in summary.new_subject_ids:
        table.add_row(
            subject_id,
            bids.summary_table_cell(summary.subject_physiology, subject_id),
            bids.summary_table_cell(summary.subject_events, subject_id),
        )
    console.print(table)
