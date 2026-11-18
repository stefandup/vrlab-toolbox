import csv
import datetime as dt
import json
import logging
import random
import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from bioread.reader import Reader

from vrlab_toolbox.processing.longwalk3_bids import DATESTR_FORMAT
from vrlab_toolbox.processing.longwalk_dummy_data import (
    TRIGGER_BASELINE_VOLTS,
    TRIGGER_HIGH_VOLTS,
    TRIGGER_PULSE_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)

DEFAULT_CITY_LABELS = ("city1", "city2", "city3")
BASE_TIMESTAMP = dt.datetime(2026, 9, 16, 17, 30)
# Each session is a separate real-world visit, so it gets its own day; each run within a
# session (only ever >1 under the multiple_cities_per_session error) gets its own time later
# that same day. Participants are likewise spread a week apart so one dummy dataset's
# participants don't all claim the same handful of calendar days.
SUBJECT_DAY_STEP = dt.timedelta(days=7)
SESSION_DAY_STEP = dt.timedelta(days=1)
RUN_TIME_STEP = dt.timedelta(minutes=30)
# The physiology recording starts a few minutes before that session's first behaviour/actor-log
# export, same ~13-minute gap seen between the real example .acq and .csv timestamps.
ACQ_TIME_OFFSET = -dt.timedelta(minutes=13)

CLEAN_SCENARIO_LABEL = "clean"
# One city's behaviour/actor-log file set per session is the well-formed layout (longwalkV3 has
# 3 planned sessions -- see longwalk3_bids.py's SESSION_TOKEN comment). Each named error type
# below instead produces a specific known-wrong session/city layout, to exercise the BIDS
# crosscheck's ability to flag it.
ERROR_TYPES = (
    "multiple_cities_per_session",
    "malformed_subject_id_in_physiology_filename",
    "missing_subject_id_in_physiology_filename",
    "mislabeled_physiology_date",
)
# How far "mislabeled_physiology_date" moves the last session's physiology filename date -- a
# wrong month on the recording PC's clock. Always forward, and always on the *last* session, so
# the converter's chronological session numbering (see longwalk3_bids._convert_subject_physiology)
# still puts it in the right session -- only its scans.tsv date ends up wrong.
MISLABELED_PHYSIOLOGY_DATE_SHIFT = dt.timedelta(days=30)
SCENARIO_DESCRIPTIONS: dict[str, str] = {
    CLEAN_SCENARIO_LABEL: (
        "One city's behaviour/actor-log file set per session, with each participant getting "
        "the cities in their own random order (e.g. ses-01=city3, ses-02=city1, "
        "ses-03=city2) -- the well-formed layout. Matches the real study design: the city "
        "per session is randomized per participant, never more than one city per session."
    ),
    "multiple_cities_per_session": (
        "Still the standard number of sessions (one per requested city, in a random order), "
        "but one randomly chosen session gets two runs instead of one -- the wrong city "
        "first (as if it was started by mistake), then that session's actually-planned city "
        "(the restart). Both are written as run-000, the same as the real Unreal-side export "
        "always does -- exercises detection of a session with more than one run/city, "
        "without it always being the same session."
    ),
    "malformed_subject_id_in_physiology_filename": (
        "Otherwise a normal, well-formed layout, but one randomly chosen session's physiology "
        '.acq file has its subject id mistyped -- e.g. "dummy(7)" instead of "dummy07" '
        "(see _malformed_subject_id). The filename still has the expected "
        '"{date}_{subject_id}_LongWalkV3Out" shape, so it resolves to that wrong id and '
        "turns into a stray extra subject -- exercises the crosscheck GUI's \"Fix Filenames in "
        'Raw Folder" dialog, where typing the correct id pulls it back into the right subject '
        "on the next Refresh BIDS."
    ),
    "missing_subject_id_in_physiology_filename": (
        "Otherwise a normal, well-formed layout, but one randomly chosen session's physiology "
        '.acq file was saved without the subject id ever being typed -- "{date}__LongWalkV3Out"'
        " -- so no subject id can be parsed from it. Exercises the crosscheck GUI's "
        '"Fix Filenames in Raw Folder" dialog showing it as "(unparseable)", and a typed '
        "correction pulling it back into the right subject on the next Refresh BIDS."
    ),
    "mislabeled_physiology_date": (
        "Otherwise a normal, well-formed layout, but the last session's physiology .acq "
        "filename carries the wrong date (a month later than the real session day -- a wrong "
        "clock on the recording PC). The converter copies that date into scans.tsv, so the "
        "physiology's date no longer matches its session's events -- exercises the crosscheck "
        'GUI flagging it red in the physiology pane, and correcting it with "Correct date...".'
    ),
}

DATE_PART_COLUMNS = ("year", "month", "day", "hour", "minute", "second", "millisecond")
WORLD_LOCATION_AXES = ("X", "Y", "Z")
# Newer actor-log exports (see longwalkv3_examples/) already ship a single combined "date"/
# "datetime" column in DATESTR_FORMAT instead of separate DATE_PART_COLUMNS -- both names are
# accepted since longwalk3_bids.combine_events_df_files renames either to "onset".
_COMBINED_DATETIME_COLUMN_NAMES = ("date", "datetime")

# Proposed (not yet in the real Unreal-side export): every actor log gets a "trigger" column.
# When a class sends a Biopac TTL it logs an extra row of its own: date/datetime is the send
# time and "trigger" names the sending class instance (e.g. "ThreatLevelMarkerNew2"); every
# other cell on that row is empty. Ordinary event rows leave "trigger" empty. The converter
# already turns date/datetime into "onset" and the column into "trigger_<bp_id>" (see
# longwalk3_bids.combine_events_df_files), so a class's pulse onsets are just its rows with a
# non-empty trigger_<bp_id>.
TRIGGER_COLUMN = "trigger"
ACTOR_COLUMN = "actor"
# Placeholder until the real list of TTL-sending classes is confirmed: every actor class except
# these is assumed to send one pulse per logged row (the heatmap manager logs continuously).
NON_TRIGGER_ACTOR_LOG_SUFFIXES = ("BP_HeatmapManager_C.csv",)
# Send lag after the row's own logged time -- roughly one to a few frames at 90 Hz -- so the
# dummy data doesn't pretend the logged event and the pulse send are simultaneous.
TRIGGER_LAG_MS_RANGE = (5, 50)
# On top of that per-trigger jitter, Unreal's send delay builds up over a run with no re-sync
# (the same cumulative drift align_biopac_trigger_drift_from_behav_file corrects for in crane).
# Partially simulated as a per-run rate drawn from this range, applied linearly to the time since
# run start -- the magnitude is a guess, tune it against real crane/longwalk QC plots.
TRIGGER_DRIFT_MS_PER_MINUTE_RANGE = (20.0, 100.0)
# The copied .acq template's own Trigger channel is overwritten with one pulse per logged
# trigger time (see write_acq_trigger_pulses), placed this long after the recording starts for
# the session's first run start. Only relative pulse timing matters to the pipeline (it matches
# pulse patterns, not wall-clock time), so this deliberately ignores ACQ_TIME_OFFSET -- the
# template recordings are shorter than that offset, so honouring it would push every pulse past
# the end of the recording.
ACQ_TRIGGER_LEAD_IN = dt.timedelta(seconds=5)
ACQ_TRIGGER_CHANNEL_NAME = "Trigger"
ACQ_TRIGGER_NOISE_VOLTS = 0.01

# Suffix (everything after "..._run-<n>_") of each actor-location log template found in
# longwalkv3_examples/ -- used to find each one under template_folder regardless of its
# timestamp/subject-id/run prefix.
_ACTOR_LOG_SUFFIX_PATTERN = re.compile(r"_run-\d+_(?P<suffix>.+\.csv)$")
_BEHAVIOUR_SUFFIX_PATTERN = re.compile(r"_run-\d+_behaviour\.csv$")

# REDCap's own export naming convention: "<ProjectName>_DATA_<YYYY-MM-DD>_<HHMM>.csv" -- used to
# find the debrief REDCap export template under template_folder (see longwalkv3_examples/), and
# to recover the project name for the dummy file written alongside it.
_REDCAP_EXPORT_PATTERN = re.compile(r"^(?P<project_name>.+)_DATA_\d{4}-\d{2}-\d{2}_\d{4}\.csv$")
REDCAP_DEBRIEF_TIMESTAMP = dt.datetime(2026, 9, 18, 15, 50)

# Heuristics for filling a dummy value per REDCap column name -- deliberately generic
# placeholders (not an attempt to model real response distributions): a REDCap "form complete"
# status column always gets code "2" (complete), a date-ish or name-ish column gets an obviously
# fake fixed value, a single-choice/scale question column (ends "_q<n>") gets "1", and anything
# else falls back to "dummy". study_id is handled separately since it must match the dummy
# subject id passed in.
_REDCAP_QUESTION_COLUMN_PATTERN = re.compile(r"_q\d+$")
_REDCAP_DUMMY_DATE = "2026-01-01"


def _dummy_redcap_value(column: str, subject_id: str) -> str:
    if column == "study_id":
        return subject_id
    if column.endswith("_complete"):
        return "2"
    if "date" in column.lower() or column.lower() == "dob":
        return _REDCAP_DUMMY_DATE
    if "name" in column.lower():
        return "Dummy"
    if "sign" in column.lower():
        return "Dummy Signature"
    if _REDCAP_QUESTION_COLUMN_PATTERN.search(column.lower()):
        return "1"
    return "dummy"


def discover_redcap_debrief_template(template_folder: Path) -> Path:
    matches = [
        p for p in sorted(template_folder.glob("*.csv")) if _REDCAP_EXPORT_PATTERN.match(p.name)
    ]
    if not matches:
        raise FileNotFoundError(
            f"No template REDCap debrief export csv found under {template_folder}"
        )
    return matches[0]


def _read_csv_header(csv_path: Path) -> list[str]:
    """Reads only the header row of csv_path -- never the data rows below it, since a REDCap
    export template may hold real participant data (see the debrief csv in
    longwalkv3_examples/); only its column structure is safe to reuse for dummy generation.
    """
    with csv_path.open(newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    return [cell.strip() for cell in header]


def generate_dummy_redcap_debrief_file(
    template_folder: Path, output_folder: Path, subject_ids: list[str]
) -> Path:
    """Writes a dummy REDCap debrief export csv under output_folder, one row per subject_id, with
    the same columns as the real export template found under template_folder (see
    discover_redcap_debrief_template) but every value replaced by a generic placeholder (see
    _dummy_redcap_value) -- the template's own data rows are never read.
    """
    template_path = discover_redcap_debrief_template(template_folder)
    header = _read_csv_header(template_path)

    project_name_match = _REDCAP_EXPORT_PATTERN.match(template_path.name)
    assert project_name_match is not None
    project_name = project_name_match.group("project_name")

    output_path = (
        output_folder
        / f"{project_name}_DATA_{REDCAP_DEBRIEF_TIMESTAMP.strftime('%Y-%m-%d_%H%M')}.csv"
    )
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for subject_id in subject_ids:
            writer.writerow([_dummy_redcap_value(column, subject_id) for column in header])

    return output_path


@dataclass
class DummyLongWalkV3ParticipantResult:
    subject_id: str
    scenario: str
    acq_paths: list[Path] = field(default_factory=list)
    behaviour_paths: list[Path] = field(default_factory=list)
    actor_log_paths: list[Path] = field(default_factory=list)


def discover_acq_template(template_folder: Path) -> Path:
    matches = sorted(template_folder.glob("*.acq"))
    if not matches:
        raise FileNotFoundError(f"No template .acq file found under {template_folder}")
    return matches[0]


def discover_behaviour_template(template_folder: Path) -> Path:
    matches = [
        p for p in sorted(template_folder.glob("*.csv")) if _BEHAVIOUR_SUFFIX_PATTERN.search(p.name)
    ]
    if not matches:
        raise FileNotFoundError(f"No template behaviour csv found under {template_folder}")
    return matches[0]


def discover_actor_log_templates(template_folder: Path) -> dict[str, Path]:
    """Maps each actor-location log's filename suffix (e.g. "BP_NPC_C.csv") to its template
    path, for every *_run-<n>_<suffix>.csv file under template_folder that isn't the behaviour
    file.

    When several recordings ship the same suffix, the newest (last by filename timestamp) wins
    -- unless it has no data rows and an older one does. A real export can log an actor type
    with a header only (e.g. BP_Phone_C when the phone never fired that run), which would
    otherwise leave every generated run with an empty log for it.
    """
    templates: dict[str, Path] = {}
    for csv_path in sorted(template_folder.glob("*.csv")):
        if _BEHAVIOUR_SUFFIX_PATTERN.search(csv_path.name):
            continue
        match = _ACTOR_LOG_SUFFIX_PATTERN.search(csv_path.name)
        if not match:
            continue
        suffix = match.group("suffix")
        if suffix in templates and not _read_repeated_header_csv(csv_path)[2]:
            continue
        templates[suffix] = csv_path

    if not templates:
        raise FileNotFoundError(
            f"No template actor-location log csvs found under {template_folder}"
        )
    return templates


def _read_repeated_header_csv(csv_path: Path) -> tuple[list[str], int, list[list[str]]]:
    """Parses a csv whose header row is repeated some number of times before the data rows
    start (see longwalkv3_examples/*.csv) -- returns (header, header_repeat_count, data_rows).
    """
    with csv_path.open(newline="", encoding="utf-8") as f:
        raw_rows = [[cell.strip() for cell in row] for row in csv.reader(f) if row]

    header = raw_rows[0]
    header_repeat_count = 0
    for row in raw_rows:
        if row == header:
            header_repeat_count += 1
        else:
            break

    return header, header_repeat_count, raw_rows[header_repeat_count:]


def _row_date_parts_datetime(row: list[str], date_part_index: dict[str, int]) -> dt.datetime:
    year, month, day, hour, minute, second = (
        int(row[date_part_index[name]]) for name in DATE_PART_COLUMNS if name != "millisecond"
    )
    return dt.datetime(year, month, day, hour, minute, second)


def _combine_date(
    row: list[str], date_part_index: dict[str, int], shift: dt.timedelta, rng: random.Random
) -> str:
    # The template's own millisecond cell is just a placeholder (no real sub-second value has
    # ever been recorded by the Unreal-side export) -- a random one is generated per row instead
    # so dummy data doesn't leave every event's millisecond fixed at the same value. `shift`
    # rebases the row's own year/month/day/... onto this run's actual date (see
    # reshape_actor_log) instead of leaving every generated participant/session/run stuck on
    # the template's own recorded date.
    shifted = _row_date_parts_datetime(row, date_part_index) + shift
    millisecond = rng.randint(0, 999)
    return f"{shifted:%Y%m%d%H%M%S}{millisecond:03d}"


def _combine_world_location(row: list[str], location_index: dict[str, int]) -> str:
    return " ".join(f"{axis}={row[location_index[axis]]}" for axis in WORLD_LOCATION_AXES)


def _parse_digit_timestamp(value: str) -> dt.datetime | None:
    """Parses a `DATESTR_FORMAT` digit string exactly the way
    longwalk3_bids.combine_events_df_files itself will (pd.to_datetime with the same
    format/errors="coerce") rather than the stricter datetime.strptime -- pandas tolerates
    some malformed-but-real-recorded values strptime rejects outright (e.g. a leap-second
    rounding artifact from the Unreal-side export, second=60, which pandas rolls into the next
    minute). Using the same parser here is what keeps "was this row actually shifted" and "will
    the converter actually treat this row as dated" in agreement -- otherwise a row left
    un-shifted because it looked unparseable can still parse downstream, leaking the
    template's own un-shifted date back into the converter's acq_time.
    """
    parsed = pd.to_datetime(value, format=DATESTR_FORMAT, errors="coerce")
    return None if pd.isna(parsed) else parsed.to_pydatetime()


def _shift_combined_datetime_rows(
    header: list[str], rows: list[list[str]], run_start: dt.datetime
) -> list[list[str]]:
    """Rebases a template that already has a single combined date/datetime column (see
    _COMBINED_DATETIME_COLUMN_NAMES) onto `run_start`, the same way _combine_date rebases a
    template that still has separate year/month/day/... columns -- reshape_actor_log falls
    back to this when there's nothing to reshape structurally, since without it every
    generated participant/session/run would keep the template's own recorded date untouched
    (see reshape_actor_log's `run_start` docstring). Returns `rows` unchanged if there's no
    such column, or no row with a parseable reference date to shift from.
    """
    header_lower = [column.lower() for column in header]
    timestamp_name = next(
        (name for name in _COMBINED_DATETIME_COLUMN_NAMES if name in header_lower), None
    )
    if timestamp_name is None or not rows:
        return rows

    timestamp_index = header_lower.index(timestamp_name)
    reference = next(
        (
            parsed
            for row in rows
            if (parsed := _parse_digit_timestamp(row[timestamp_index])) is not None
        ),
        None,
    )
    if reference is None:
        return rows
    shift = run_start - reference

    def shift_row(row: list[str]) -> list[str]:
        parsed = _parse_digit_timestamp(row[timestamp_index])
        if parsed is None:
            return row
        shifted = parsed + shift
        millisecond = shifted.microsecond // 1000
        new_row = list(row)
        new_row[timestamp_index] = f"{shifted:%Y%m%d%H%M%S}{millisecond:03d}"
        return new_row

    return [shift_row(row) for row in rows]


def _combined_datetime_values(header: list[str], rows: list[list[str]]) -> list[dt.datetime]:
    """Every parseable timestamp in a (reshaped) actor log's combined date/datetime column --
    empty if it has no such column (see _COMBINED_DATETIME_COLUMN_NAMES).
    """
    header_lower = [column.lower() for column in header]
    timestamp_name = next(
        (name for name in _COMBINED_DATETIME_COLUMN_NAMES if name in header_lower), None
    )
    if timestamp_name is None:
        return []

    timestamp_index = header_lower.index(timestamp_name)
    return [
        parsed
        for row in rows
        if (parsed := _parse_digit_timestamp(row[timestamp_index])) is not None
    ]


def add_trigger_column(
    header: list[str],
    rows: list[list[str]],
    rng: random.Random,
    sends_triggers: bool,
    run_start: dt.datetime,
    drift_ms_per_minute: float = 0.0,
) -> tuple[list[str], list[list[str]]]:
    """Appends TRIGGER_COLUMN to a (reshaped) actor log (empty on every existing row). If
    `sends_triggers`, each row with a parseable combined date/datetime is followed by a trigger
    row (see TRIGGER_COLUMN): its date/datetime is the event time plus a send lag, in
    DATESTR_FORMAT, and its trigger cell is the event row's actor instance name. The lag is a
    random TRIGGER_LAG_MS_RANGE jitter plus `drift_ms_per_minute` times the minutes elapsed
    since `run_start` -- the cumulative delay (see TRIGGER_DRIFT_MS_PER_MINUTE_RANGE). Shared by
    every actor log in a run, so all classes drift together, as they would off the one Unreal
    game thread.
    """
    new_header = [*header, TRIGGER_COLUMN]
    header_lower = [column.lower() for column in header]
    timestamp_name = next(
        (name for name in _COMBINED_DATETIME_COLUMN_NAMES if name in header_lower), None
    )
    if timestamp_name is None or not sends_triggers:
        return new_header, [[*row, ""] for row in rows]

    timestamp_index = header_lower.index(timestamp_name)
    actor_index = header_lower.index(ACTOR_COLUMN) if ACTOR_COLUMN in header_lower else None

    new_rows = []
    for row in rows:
        new_rows.append([*row, ""])
        parsed = _parse_digit_timestamp(row[timestamp_index])
        if parsed is None:
            continue
        minutes_since_start = max((parsed - run_start).total_seconds(), 0.0) / 60
        lag_ms = rng.randint(*TRIGGER_LAG_MS_RANGE) + drift_ms_per_minute * minutes_since_start
        sent = parsed + dt.timedelta(milliseconds=lag_ms)
        trigger_row = [""] * len(new_header)
        trigger_row[timestamp_index] = f"{sent:%Y%m%d%H%M%S}{sent.microsecond // 1000:03d}"
        trigger_row[-1] = row[actor_index] if actor_index is not None else TRIGGER_COLUMN
        new_rows.append(trigger_row)

    return new_header, new_rows


def _trigger_row_times(header: list[str], rows: list[list[str]]) -> list[dt.datetime]:
    """The date/datetime of every trigger row (non-empty TRIGGER_COLUMN -- see
    add_trigger_column), i.e. each pulse's logged send time."""
    header_lower = [column.lower() for column in header]
    timestamp_name = next(
        (name for name in _COMBINED_DATETIME_COLUMN_NAMES if name in header_lower), None
    )
    if timestamp_name is None or TRIGGER_COLUMN not in header:
        return []
    timestamp_index = header_lower.index(timestamp_name)
    trigger_index = header.index(TRIGGER_COLUMN)
    return [
        parsed
        for row in rows
        if row[trigger_index] and (parsed := _parse_digit_timestamp(row[timestamp_index]))
    ]


def write_acq_trigger_pulses(
    acq_path: Path,
    trigger_times: list[dt.datetime],
    recording_start: dt.datetime,
    rng: random.Random,
) -> int:
    """Overwrites, in place, the Trigger channel of an uncompressed .acq (a copied template)
    with a noisy TRIGGER_BASELINE_VOLTS baseline plus one TRIGGER_PULSE_DURATION_SECONDS pulse
    at TRIGGER_HIGH_VOLTS per trigger time, measured from `recording_start`. Every other channel
    and the file's headers are left untouched, so bioread still reads it as before. Pulses that
    fall outside the recording are dropped. Returns how many pulses were written.

    Only handles the layout the longwalkV3 templates use -- uncompressed, every channel at the
    same rate (frequency divider 1), interleaved sample by sample -- and raises ValueError for
    anything else rather than silently corrupting the file.
    """
    with acq_path.open("rb") as f:
        reader = Reader.read_headers(f)
    if reader.is_compressed:
        raise ValueError(f"{acq_path} is compressed -- can't overwrite its Trigger channel")
    channel_headers = reader.channel_headers
    dtype_headers = reader.channel_dtype_headers
    if any(ch.frequency_divider != 1 for ch in channel_headers) or any(
        dh.type_code != 2 for dh in dtype_headers
    ):
        raise ValueError(f"{acq_path} doesn't have the expected uniform int16 channel layout")
    channel_names = [ch.name for ch in channel_headers]
    if ACQ_TRIGGER_CHANNEL_NAME not in channel_names:
        raise ValueError(f"{acq_path} has no {ACQ_TRIGGER_CHANNEL_NAME!r} channel")
    data_start_offset = reader.data_start_offset
    samples_per_second = reader.samples_per_second
    if data_start_offset is None or samples_per_second is None:
        raise ValueError(f"{acq_path} is missing its data offset or sample rate header")

    trigger_channel_index = channel_names.index(ACQ_TRIGGER_CHANNEL_NAME)
    trigger_header = channel_headers[trigger_channel_index]
    n_samples = int(trigger_header.point_count)
    samples = np.memmap(
        acq_path,
        dtype=np.dtype(f"{reader.byte_order_char}i2"),
        mode="r+",
        offset=data_start_offset,
        shape=(n_samples, len(channel_headers)),
    )

    np_rng = np.random.default_rng(rng.getrandbits(32))
    volts = TRIGGER_BASELINE_VOLTS + np_rng.normal(0, ACQ_TRIGGER_NOISE_VOLTS, size=n_samples)
    pulse_samples = int(round(TRIGGER_PULSE_DURATION_SECONDS * samples_per_second))
    n_written = 0
    for trigger_time in trigger_times:
        start = int(round((trigger_time - recording_start).total_seconds() * samples_per_second))
        if start < 0 or start + pulse_samples > n_samples:
            continue
        volts[start : start + pulse_samples] = TRIGGER_HIGH_VOLTS
        n_written += 1
    if n_written < len(trigger_times):
        logger.debug(
            "%d of %d trigger pulses fell outside %s's recording and were dropped.",
            len(trigger_times) - n_written,
            len(trigger_times),
            acq_path.name,
        )

    raw = np.round((volts - trigger_header.raw_offset) / trigger_header.raw_scale)
    samples[:, trigger_channel_index] = np.clip(raw, -32768, 32767).astype(np.int16)
    samples.flush()
    del samples
    return n_written


def _spread_behaviour_timestamps(
    header: list[str], rows: list[list[str]], run_start: dt.datetime, run_end: dt.datetime
) -> list[list[str]]:
    """Replaces each behaviour row's TimeStamp with a DATESTR_FORMAT value spread evenly (in
    increasing order) strictly inside [run_start, run_end] -- the template's own TimeStamp cells
    aren't a usable recorded value (always 0.0), which the converter would otherwise coerce to
    NaT (see longwalk3_bids.combine_events_df_files). Every other column is kept as-is. Returns
    `rows` unchanged if header has no TimeStamp column.
    """
    header_lower = [column.lower() for column in header]
    if "timestamp" not in header_lower:
        return rows

    timestamp_index = header_lower.index("timestamp")
    step = (run_end - run_start) / (len(rows) + 1)

    def spread_row(index: int, row: list[str]) -> list[str]:
        timestamp = run_start + step * (index + 1)
        new_row = list(row)
        new_row[timestamp_index] = f"{timestamp:%Y%m%d%H%M%S}{timestamp.microsecond // 1000:03d}"
        return new_row

    return [spread_row(index, row) for index, row in enumerate(rows)]


def reshape_actor_log(
    header: list[str], rows: list[list[str]], rng: random.Random, run_start: dt.datetime
) -> tuple[list[str], list[list[str]]]:
    """Replaces year/month/day/hour/minute/second/millisecond with a single "date" column
    (concatenated yyyyMMddHHmmssSSS, e.g. "20260916175501873" -- the millisecond part is
    randomly generated per row via rng, since the template CSVs don't carry a real recorded
    value yet -- see _combine_date) and worldLocationX/Y/Z with a single "worldLocation" column
    column (formatted the way an Unreal FVector prints via ToString(), e.g. "X=1.0 Y=2.0
    Z=3.0"). Any other column (actor, isFearCue, ...) is kept in place. Rows are otherwise
    unchanged. If header doesn't have both groups of columns to reshape (e.g. behaviour.csv,
    or a newer export that already ships a single combined date/datetime column -- see
    _shift_combined_datetime_rows), the header/columns are returned unchanged, but any combined
    date/datetime column found is still rebased onto `run_start`.

    `run_start` (this run's target start time -- see _run_csv_timestamp) rebases every row's
    date by the same delta needed to move the template's own first row onto it, so a run's
    events land on that run's actual calendar day/time instead of the template's recorded one
    -- otherwise every generated participant/session/run ends up with identical event dates.
    """
    header_lower = [column.lower() for column in header]

    date_part_index = {
        name: header_lower.index(name) for name in DATE_PART_COLUMNS if name in header_lower
    }
    location_index = {
        axis: header_lower.index(f"worldlocation{axis.lower()}")
        for axis in WORLD_LOCATION_AXES
        if f"worldlocation{axis.lower()}" in header_lower
    }

    if len(date_part_index) != len(DATE_PART_COLUMNS) or len(location_index) != len(
        WORLD_LOCATION_AXES
    ):
        return header, _shift_combined_datetime_rows(header, rows, run_start)

    combined_indices = set(date_part_index.values()) | set(location_index.values())
    date_insert_at = min(date_part_index.values())
    location_insert_at = min(location_index.values())

    shift = (
        run_start - _row_date_parts_datetime(rows[0], date_part_index) if rows else dt.timedelta(0)
    )

    def reshape_row(row: list[str], date_value: str, location_value: str) -> list[str]:
        new_row = []
        for index, value in enumerate(row):
            if index == date_insert_at:
                new_row.append(date_value)
            if index == location_insert_at:
                new_row.append(location_value)
            if index not in combined_indices:
                new_row.append(value)
        return new_row

    new_header = reshape_row(header, "date", "worldLocation")
    new_rows = [
        reshape_row(
            row,
            _combine_date(row, date_part_index, shift, rng),
            _combine_world_location(row, location_index),
        )
        for row in rows
    ]
    return new_header, new_rows


def _write_repeated_header_csv(
    csv_path: Path, header: list[str], header_repeat_count: int, rows: list[list[str]]
) -> None:
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for _ in range(header_repeat_count):
            writer.writerow(header)
        writer.writerows(rows)


def _session_day(subject_index: int, session_index: int) -> dt.datetime:
    return BASE_TIMESTAMP + subject_index * SUBJECT_DAY_STEP + session_index * SESSION_DAY_STEP


def _acq_timestamp(session_day: dt.datetime) -> str:
    return (session_day + ACQ_TIME_OFFSET).strftime("%Y%m%d%H%M")


def _run_csv_timestamp(session_day: dt.datetime, run_index: int) -> str:
    return (session_day + run_index * RUN_TIME_STEP).strftime("%Y%m%d%H%M")


def _randomized_session_cities(city_labels: tuple[str, ...], rng: random.Random) -> list[str]:
    """Each city exactly once, in a random order -- one participant's planned city per
    session (index 0 = ses-01). The real study randomizes which city a participant walks in
    each session, so a fixed ses-01=city1, ses-02=city2, ... layout would never exercise
    anything that wrongly assumes that mapping.
    """
    return rng.sample(list(city_labels), k=len(city_labels))


def _multiple_cities_per_session_layout(
    planned_cities: list[str], rng: random.Random
) -> list[list[str]]:
    """One randomly chosen session's planned city is preceded by a run in a different, randomly
    chosen city -- e.g. ses-02 was planned as city2, but city3 got run first by mistake, then
    city2 was restarted afterwards to correct it (both written as run-000 -- see
    generate_dummy_longwalkv3_participant). Every other session keeps its single planned-city
    run. Still exactly len(planned_cities) sessions -- only the run count within one of them
    changes.
    """
    if len(planned_cities) < 2:
        raise ValueError("Need at least 2 cities to model a wrong-city run.")

    session_city_runs: list[list[str]] = [[city] for city in planned_cities]

    error_session_index = rng.randrange(len(planned_cities))
    planned_city = planned_cities[error_session_index]
    wrong_city = rng.choice([city for city in planned_cities if city != planned_city])
    session_city_runs[error_session_index] = [wrong_city, planned_city]

    return session_city_runs


def build_session_city_layout(
    city_labels: tuple[str, ...], error_type: str | None = None, rng: random.Random | None = None
) -> list[tuple[str, list[str]]]:
    """Maps each session token to the ordered list of cities run under it -- one entry per run
    (see generate_dummy_longwalkv3_participant for how each is turned into a filename).

    error_type=None (clean): one city, one run, per session, each city used exactly once in a
    random order (see _randomized_session_cities). error_type="multiple_cities_per_session":
    still exactly that many sessions, but one of them instead gets two runs, a wrong city then
    its correct one (see _multiple_cities_per_session_layout). rng falls back to an unseeded
    Random when not given.

    Only these two values are meaningful here -- a session/city *layout* shape. Other
    ERROR_TYPES entries (e.g. "malformed_subject_id_in_physiology_filename") don't affect this
    layout at all; generate_dummy_longwalkv3_participant applies those separately, after the
    (otherwise clean) file set this function's layout produces has been written, so callers
    pass this function None for any such error_type.
    """
    rng = rng or random.Random()
    planned_cities = _randomized_session_cities(city_labels, rng)
    if error_type is None:
        session_city_runs: list[list[str]] = [[city] for city in planned_cities]
    elif error_type == "multiple_cities_per_session":
        session_city_runs = _multiple_cities_per_session_layout(planned_cities, rng)
    else:
        raise ValueError(
            "error_type must be None or 'multiple_cities_per_session' for this layout "
            f"function, got {error_type!r}"
        )

    return [(f"ses-{index + 1:02d}", cities) for index, cities in enumerate(session_city_runs)]


_SUBJECT_ID_NUMBER_PATTERN = re.compile(r"^(?P<prefix>\D*?)0*(?P<number>\d+)$")


def _malformed_subject_id(subject_id: str) -> str:
    """A mistyped version of `subject_id` for "malformed_subject_id_in_physiology_filename":
    its number in brackets with the zero-padding dropped -- "dummy07" -> "dummy(7)". Falls
    back to appending "(1)" for an id without a trailing number.
    """
    match = _SUBJECT_ID_NUMBER_PATTERN.match(subject_id)
    if match is None:
        return f"{subject_id}(1)"
    return f"{match.group('prefix')}({match.group('number')})"


def _acq_filename(
    session_day: dt.datetime,
    subject_id: str,
    session_index: int,
    session_count: int,
    error_type: str | None,
    error_session_index: int | None,
) -> str:
    """The raw physiology filename for one session, with any physiology-filename error_type
    applied: "malformed_subject_id_in_physiology_filename" mistypes the id on
    `error_session_index` (see _malformed_subject_id),
    "missing_subject_id_in_physiology_filename" leaves the id out there instead (the id field
    is empty -- "{date}__LongWalkV3Out.acq", which longwalk3_bids.py's
    `_PHYSIOLOGY_FILENAME_PATTERN` can't parse a subject id from), and
    "mislabeled_physiology_date" shifts the *last* session's date by
    MISLABELED_PHYSIOLOGY_DATE_SHIFT (see its comment for why the last one).
    """
    timestamp = _acq_timestamp(session_day)
    if error_type == "mislabeled_physiology_date" and session_index == session_count - 1:
        timestamp = _acq_timestamp(session_day + MISLABELED_PHYSIOLOGY_DATE_SHIFT)
    filename_subject_id = subject_id
    if session_index == error_session_index:
        if error_type == "malformed_subject_id_in_physiology_filename":
            filename_subject_id = _malformed_subject_id(subject_id)
        elif error_type == "missing_subject_id_in_physiology_filename":
            filename_subject_id = ""
    return f"{timestamp}_{filename_subject_id}_LongWalkV3Out.acq"


def generate_dummy_longwalkv3_participant(
    template_folder: Path,
    output_folder: Path,
    subject_id: str,
    subject_index: int,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
    error_type: str | None = None,
    rng: random.Random | None = None,
) -> DummyLongWalkV3ParticipantResult:
    # Drives the per-participant city order (see build_session_city_layout) and each
    # actor-log row's millisecond value -- falls back to an unseeded Random so a direct call
    # without rng still works.
    rng = rng or random.Random()
    acq_template = discover_acq_template(template_folder)
    behaviour_template = discover_behaviour_template(template_folder)
    actor_log_templates = discover_actor_log_templates(template_folder)

    behaviour_header, behaviour_header_repeat_count, behaviour_rows = _read_repeated_header_csv(
        behaviour_template
    )

    # The physiology-filename errors only change one session's .acq filename (see
    # _acq_filename), not the session/city layout itself -- build_session_city_layout only knows
    # about the layout-shape error (multiple_cities_per_session), so any other error_type is passed
    # to it as None (see its own docstring).
    layout_error_type = error_type if error_type == "multiple_cities_per_session" else None
    session_city_layout = build_session_city_layout(city_labels, layout_error_type, rng)
    corrupt_physiology_session_index = (
        rng.randrange(len(session_city_layout))
        if error_type
        in (
            "malformed_subject_id_in_physiology_filename",
            "missing_subject_id_in_physiology_filename",
        )
        else None
    )

    acq_paths = []
    behaviour_paths = []
    actor_log_paths = []
    for session_index, (session_token, session_city_runs) in enumerate(session_city_layout):
        session_day = _session_day(subject_index, session_index)

        # One physiology recording per session -- it can't span the multiple days different
        # sessions now fall on -- started once, before that session's first exported run.
        acq_path = output_folder / _acq_filename(
            session_day,
            subject_id,
            session_index,
            len(session_city_layout),
            error_type,
            corrupt_physiology_session_index,
        )
        shutil.copyfile(acq_template, acq_path)
        acq_paths.append(acq_path)
        session_trigger_times: list[dt.datetime] = []

        for run_index, city_label in enumerate(session_city_runs):
            run_start = session_day + run_index * RUN_TIME_STEP
            csv_timestamp = _run_csv_timestamp(session_day, run_index)
            # The real Unreal-side export never counts runs up -- every run is written as
            # "run-000" and it's the BIDS pipeline's job to sort out true run numbers later
            # (see longwalk3_bids.py's RUN_TOKEN TODO). Two runs in the same session/city pair
            # would collide, but the multiple-cities error only ever pairs a session with two
            # *different* cities, so the filenames stay distinct on task-<city> alone.
            run_token = "run-000"
            run_filename_prefix = (
                f"{csv_timestamp}_{subject_id}_{session_token}_task-{city_label}_{run_token}"
            )
            run_timestamps: list[dt.datetime] = []
            run_drift_ms_per_minute = rng.uniform(*TRIGGER_DRIFT_MS_PER_MINUTE_RANGE)
            for suffix, template_path in actor_log_templates.items():
                header, header_repeat_count, rows = _read_repeated_header_csv(template_path)
                new_header, new_rows = reshape_actor_log(header, rows, rng, run_start)
                run_timestamps += _combined_datetime_values(new_header, new_rows)
                new_header, new_rows = add_trigger_column(
                    new_header,
                    new_rows,
                    rng,
                    suffix not in NON_TRIGGER_ACTOR_LOG_SUFFIXES,
                    run_start,
                    run_drift_ms_per_minute,
                )
                session_trigger_times += _trigger_row_times(new_header, new_rows)
                actor_log_path = output_folder / f"{run_filename_prefix}_{suffix}"
                _write_repeated_header_csv(
                    actor_log_path, new_header, header_repeat_count, new_rows
                )
                actor_log_paths.append(actor_log_path)

            # Behaviour ratings are spread across this run's own actor-log time span, so they
            # land within the run rather than all on the filename's minute. Falls back to one
            # RUN_TIME_STEP from run_start if no actor log carried a parseable timestamp.
            behaviour_run_start = min(run_timestamps, default=run_start)
            behaviour_run_end = max(run_timestamps, default=run_start + RUN_TIME_STEP)
            behaviour_path = output_folder / f"{run_filename_prefix}_behaviour.csv"
            _write_repeated_header_csv(
                behaviour_path,
                behaviour_header,
                behaviour_header_repeat_count,
                _spread_behaviour_timestamps(
                    behaviour_header, behaviour_rows, behaviour_run_start, behaviour_run_end
                ),
            )
            behaviour_paths.append(behaviour_path)

        # One shared Trigger channel per recording, so every sending class's pulses from every
        # run in this session land on it -- see ACQ_TRIGGER_LEAD_IN for why it's anchored here.
        write_acq_trigger_pulses(
            acq_path, session_trigger_times, session_day - ACQ_TRIGGER_LEAD_IN, rng
        )

    scenario = error_type or CLEAN_SCENARIO_LABEL
    return DummyLongWalkV3ParticipantResult(
        subject_id, scenario, acq_paths, behaviour_paths, actor_log_paths
    )


@dataclass
class DummyLongWalkV3DatasetResult:
    participant_results: list[DummyLongWalkV3ParticipantResult]
    # None when template_folder had no REDCap debrief export template to clone (see
    # discover_redcap_debrief_template) -- callers should treat that as "skipped", not an error.
    redcap_debrief_path: Path | None = None


def generate_dummy_longwalkv3_dataset(
    template_folder: Path,
    output_folder: Path,
    n_clean: int = 1,
    with_errors: bool = False,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
    seed: int | None = None,
) -> DummyLongWalkV3DatasetResult:
    output_folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    scenarios: list[str | None] = [None] * n_clean
    if with_errors:
        scenarios += list(ERROR_TYPES)

    participant_results = []
    for index, error_type in enumerate(scenarios):
        subject_id = f"dummy{index + 1:02d}"
        logger.info(
            "Generating dummy longwalkv3 participant %s (%s)",
            subject_id,
            error_type or CLEAN_SCENARIO_LABEL,
        )
        participant_results.append(
            generate_dummy_longwalkv3_participant(
                template_folder,
                output_folder,
                subject_id,
                index,
                city_labels,
                error_type,
                rng,
            )
        )

    redcap_debrief_path: Path | None = None
    try:
        redcap_debrief_path = generate_dummy_redcap_debrief_file(
            template_folder,
            output_folder,
            [result.subject_id for result in participant_results],
        )
    except FileNotFoundError:
        logger.info(
            "No REDCap debrief export template found under %s -- skipping dummy debrief file.",
            template_folder,
        )

    return DummyLongWalkV3DatasetResult(participant_results, redcap_debrief_path)


# --- Shape profiler ---------------------------------------------------------------------------
#
# Real longwalkV3 data is patient data, so neither an AI assistant nor the dummy generator above
# may copy rows out of it. The profiler is the way around that: a human runs it on the real
# (extracted) data folder, and it writes one JSON manifest describing only the *structure* --
# folder layout, filename patterns, CSV headers/column kinds/row counts, .acq channel layout --
# with no data values. A human reads the manifest before it goes anywhere; synthetic data is then
# built from the manifest instead of from real rows. See pipeline_next_steps.md item 32.
#
# What is deliberately left out: subject ids (replaced by sub-001, ...), dates and times of day
# (filename timestamps become "{timestamp}" plus a minute offset within the session), any CSV
# cell value, and any .acq sample or journal text. Filename tokens that appear for only one
# subject are masked too (see _FilenameTokenMasker) -- that catches a typo'd id, another
# subject's id, or a name typed into a filename by mistake.

SHAPE_MANIFEST_FILENAME = "longwalkv3_shape.json"
SHAPE_MANIFEST_VERSION = 1

_SUBJECT_FOLDER_PATTERN = re.compile(r"^sub-(?P<id>[A-Za-z0-9]+)$")
_SESSION_FOLDER_PATTERN = re.compile(r"^ses[-_ ]?\d+$", re.IGNORECASE)
_FILENAME_TIMESTAMP_PATTERN = re.compile(r"^\d{8,17}$")
_FILENAME_TIMESTAMP_FORMATS = {
    8: "%Y%m%d",
    12: "%Y%m%d%H%M",
    14: "%Y%m%d%H%M%S",
    17: DATESTR_FORMAT,
}
_DIGIT_TIMESTAMP_LENGTH = 17
# Tokens kept as-is regardless of how many subjects they appear for -- they carry no identity.
_STRUCTURED_TOKEN_PATTERNS = (
    re.compile(r"^ses-\d+$"),
    re.compile(r"^task-[A-Za-z0-9]+$"),
    re.compile(r"^run-\d+$"),
    re.compile(r"^ses-\d+task-[A-Za-z0-9]+$"),  # known export glitch, see next steps item 31
)
_FVECTOR_PATTERN = re.compile(r"^X=\S+ Y=\S+ Z=\S+$")
_DATA_LIKE_CELL_KINDS = frozenset({"int", "float", "digit_timestamp", "fvector"})
_SUBJECT_ID_PLACEHOLDER = "{id}"
_TIMESTAMP_PLACEHOLDER = "{timestamp}"
_NO_SUBJECT_FOLDER = "(outside any sub- folder)"
_NO_SESSION_FOLDER = "(none)"


def _cell_kind(value: str) -> str:
    """Classifies one CSV cell without keeping its value: empty, digit_timestamp (the 17-digit
    DATESTR_FORMAT stamp), int, float, fvector (Unreal "X=.. Y=.. Z=.."), or text."""
    if value == "":
        return "empty"
    if value.isdigit() and len(value) == _DIGIT_TIMESTAMP_LENGTH:
        return "digit_timestamp"
    try:
        int(value)
        return "int"
    except ValueError:
        pass
    try:
        float(value)
        return "float"
    except ValueError:
        pass
    if _FVECTOR_PATTERN.match(value):
        return "fvector"
    return "text"


def _profile_csv(csv_path: Path) -> dict:
    """Header, header-repeat count, row counts and per-column cell kinds of one CSV -- never a
    cell value. If the first row looks like data rather than a header (a headerless file), its
    cells are reported by kind only, so no value leaks in through the "header"."""
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        raw_rows = [[cell.strip() for cell in row] for row in csv.reader(f) if row]
    if not raw_rows:
        return {"empty_file": True}

    header = raw_rows[0]
    header_looks_like_data = any(_cell_kind(cell) in _DATA_LIKE_CELL_KINDS for cell in header)
    if header_looks_like_data:
        data_rows = raw_rows
        leading_header_rows = 0
    else:
        data_rows = [row for row in raw_rows if row != header]
        leading_header_rows = 0
        for row in raw_rows:
            if row != header:
                break
            leading_header_rows += 1

    columns = []
    for column_index, name in enumerate(header):
        cells = [row[column_index] if column_index < len(row) else "" for row in data_rows]
        kinds = Counter(_cell_kind(cell) for cell in cells)
        column: dict = {
            "name": f"(column {column_index + 1})" if header_looks_like_data else name,
            "cell_kinds": dict(sorted(kinds.items())),
        }
        if kinds["text"]:
            column["n_distinct_text"] = len({c for c in cells if _cell_kind(c) == "text"})
        stamps = [
            stamp
            for cell in cells
            if _cell_kind(cell) == "digit_timestamp"
            and (stamp := _parse_digit_timestamp(cell)) is not None
        ]
        if len(stamps) > 1:
            column["span_seconds"] = round((max(stamps) - min(stamps)).total_seconds(), 3)
        columns.append(column)

    return {
        "header_looks_like_data": header_looks_like_data,
        "n_columns": len(header),
        "n_header_rows": len(raw_rows) - len(data_rows),
        "n_leading_header_rows": leading_header_rows,
        "n_data_rows": len(data_rows),
        "n_rows_with_wrong_width": sum(len(row) != len(header) for row in data_rows),
        "columns": columns,
    }


def _profile_acq(acq_path: Path) -> dict:
    """Channel layout of one .acq from its headers only -- bioread's read_headers never loads
    samples, and the journal (free text that could hold notes) isn't reported."""
    with acq_path.open("rb") as f:
        reader = Reader.read_headers(f)
    samples_per_second = reader.samples_per_second
    channels = [
        {
            "name": channel.name,
            "units": channel.units,
            "frequency_divider": int(channel.frequency_divider),
            "point_count": int(channel.point_count),
        }
        for channel in reader.channel_headers
    ]
    duration_seconds = None
    if samples_per_second and channels:
        duration_seconds = round(
            max(ch["point_count"] * ch["frequency_divider"] for ch in channels)
            / samples_per_second,
            3,
        )
    return {
        "samples_per_second": samples_per_second,
        "is_compressed": bool(reader.is_compressed),
        "duration_seconds": duration_seconds,
        "channels": channels,
    }


def _filename_kind(path: Path) -> str:
    if path.suffix.lower() == ".acq":
        return "acq"
    if _BEHAVIOUR_SUFFIX_PATTERN.search(path.name):
        return "behaviour"
    if _ACTOR_LOG_SUFFIX_PATTERN.search(path.name):
        return "actor_log"
    return "other_csv"


def _schema_key(masked_pattern: str, kind: str) -> str:
    """Groups CSVs that should share one header: actor logs by their suffix (e.g.
    "BP_NPC_C.csv"), behaviour files together, anything else under "other". Takes the
    *masked* filename pattern, never the raw name, so a stray token can't leak in here."""
    if kind == "behaviour":
        return "behaviour.csv"
    if kind == "actor_log":
        match = _ACTOR_LOG_SUFFIX_PATTERN.search(masked_pattern)
        if match:
            return match.group("suffix")
    return "other"


def _parse_filename_timestamp(token: str) -> dt.datetime | None:
    fmt = _FILENAME_TIMESTAMP_FORMATS.get(len(token))
    if fmt is None:
        return None
    parsed = pd.to_datetime(token, format=fmt, errors="coerce")
    return None if pd.isna(parsed) else parsed.to_pydatetime()


def _replace_subject_id(text: str, raw_subject_id: str | None) -> str:
    if not raw_subject_id:
        return text
    return text.replace(raw_subject_id, _SUBJECT_ID_PLACEHOLDER)


class _FilenameTokenMasker:
    """Decides which "_"-separated filename tokens (and folder names) are safe to show as-is.

    Timestamps, the subject's own id and BIDS-style ses-/task-/run- tokens are always handled.
    Any other token is shown only if it appears for at least `min_subjects` different subjects
    (Unreal class names like "BP"/"NPC" or "LongWalkV3Out" do; a typo'd id, another subject's id,
    or a name typed into one file doesn't) -- otherwise it becomes "{masked:<length>}".
    """

    def __init__(self, min_subjects: int) -> None:
        self.min_subjects = min_subjects
        self._subjects_per_token: dict[str, set[str]] = {}

    @staticmethod
    def _is_structured(token: str) -> bool:
        return (
            token in ("", _SUBJECT_ID_PLACEHOLDER, f"sub-{_SUBJECT_ID_PLACEHOLDER}")
            or bool(_FILENAME_TIMESTAMP_PATTERN.match(token))
            or any(pattern.match(token) for pattern in _STRUCTURED_TOKEN_PATTERNS)
        )

    def observe(self, token: str, subject_key: str) -> None:
        if not self._is_structured(token):
            self._subjects_per_token.setdefault(token, set()).add(subject_key)

    def render(self, token: str) -> str:
        if _FILENAME_TIMESTAMP_PATTERN.match(token):
            return _TIMESTAMP_PLACEHOLDER
        if self._is_structured(token):
            return token
        if len(self._subjects_per_token.get(token, ())) >= self.min_subjects:
            return token
        return f"{{masked:{len(token)}}}"


def _filename_tokens(path: Path, raw_subject_id: str | None) -> list[str]:
    stem = path.name[: -len(path.suffix)] if path.suffix else path.name
    return _replace_subject_id(stem, raw_subject_id).split("_")


def _session_folder_label(
    name: str, raw_subject_id: str | None, masker: _FilenameTokenMasker
) -> str:
    if _SESSION_FOLDER_PATTERN.match(name):
        return name
    return masker.render(_replace_subject_id(name, raw_subject_id))


def _inner_folder_parts(path: Path, data_folder: Path, subject_key: str) -> tuple[str, ...]:
    """Folder names between the subject folder (or data_folder, for files outside any sub-
    folder) and the file itself -- the first one is the session folder."""
    parts = path.parent.relative_to(data_folder).parts
    return parts if subject_key == _NO_SUBJECT_FOLDER else parts[1:]


def _acq_schema_key(acq_profile: dict) -> str:
    return json.dumps(
        {
            "samples_per_second": acq_profile["samples_per_second"],
            "channels": [
                [ch["name"], ch["units"], ch["frequency_divider"]] for ch in acq_profile["channels"]
            ],
        }
    )


def profile_longwalkv3_shape(data_folder: Path) -> dict:
    """Walks data_folder recursively and returns the structure-only manifest described at the
    top of this section. Expected layout is the real export's sub-<id>/<session folder>/files;
    each sub- folder is searched recursively for .csv and .acq files, and files sitting directly
    in data_folder are profiled under their own key. Other top-level folders (e.g. an ID-mapping
    folder) are listed by name and file count only -- never opened.
    """
    data_folder = Path(data_folder)
    subject_folders = sorted(
        p for p in data_folder.iterdir() if p.is_dir() and _SUBJECT_FOLDER_PATTERN.match(p.name)
    )
    other_top_level_folders = sorted(
        p for p in data_folder.iterdir() if p.is_dir() and p not in subject_folders
    )

    # (subject key, raw id, file path) -- the raw id is only used to blank it out of names.
    found_files: list[tuple[str, str | None, Path]] = []
    for subject_number, subject_folder in enumerate(subject_folders, start=1):
        match = _SUBJECT_FOLDER_PATTERN.match(subject_folder.name)
        raw_subject_id = match.group("id") if match else None
        for path in sorted(subject_folder.rglob("*")):
            if path.is_file():
                found_files.append((f"sub-{subject_number:03d}", raw_subject_id, path))
    for path in sorted(p for p in data_folder.iterdir() if p.is_file()):
        found_files.append((_NO_SUBJECT_FOLDER, None, path))

    masker = _FilenameTokenMasker(min_subjects=min(2, max(len(subject_folders), 1)))
    for subject_key, raw_subject_id, path in found_files:
        folder_parts = _inner_folder_parts(path, data_folder, subject_key)
        for token in _filename_tokens(path, raw_subject_id) + [
            _replace_subject_id(part, raw_subject_id) for part in folder_parts
        ]:
            masker.observe(token, subject_key)

    subjects: dict[str, dict[str, dict]] = {}
    file_timestamps: dict[int, dt.datetime] = {}
    csv_schemas: dict[str, Counter] = {}
    acq_schemas: Counter = Counter()
    for subject_key, raw_subject_id, path in found_files:
        folder_parts = _inner_folder_parts(path, data_folder, subject_key)
        session_label = (
            _session_folder_label(folder_parts[0], raw_subject_id, masker)
            if folder_parts
            else _NO_SESSION_FOLDER
        )
        session = subjects.setdefault(subject_key, {}).setdefault(
            session_label, {"files": [], "other_files_by_extension": Counter()}
        )

        suffix = path.suffix.lower()
        if suffix not in (".csv", ".acq"):
            session["other_files_by_extension"][suffix or "(no extension)"] += 1
            continue

        tokens = _filename_tokens(path, raw_subject_id)
        kind = _filename_kind(path)
        file_entry: dict = {
            "pattern": "_".join(masker.render(t) for t in tokens) + path.suffix,
            "kind": kind,
        }
        if len(folder_parts) > 1:
            file_entry["nested_folder"] = "/".join(
                masker.render(_replace_subject_id(part, raw_subject_id))
                for part in folder_parts[1:]
            )
        for token in tokens:
            if _FILENAME_TIMESTAMP_PATTERN.match(token):
                stamp = _parse_filename_timestamp(token)
                if stamp is not None:
                    file_timestamps[id(file_entry)] = stamp
                    break

        try:
            if kind == "acq":
                file_entry["acq"] = _profile_acq(path)
                acq_schemas[_acq_schema_key(file_entry["acq"])] += 1
            else:
                file_entry["csv"] = _profile_csv(path)
                header = [c["name"] for c in file_entry["csv"].get("columns", [])]
                schema_key = _schema_key(file_entry["pattern"], kind)
                csv_schemas.setdefault(schema_key, Counter())[json.dumps(header)] += 1
        except Exception as error:  # one unreadable file shouldn't stop the whole profile
            # Only the exception type -- messages can quote file contents.
            file_entry["error"] = type(error).__name__
            logger.warning("Could not profile %s (%s)", path.name, type(error).__name__)
        session["files"].append(file_entry)

    # Filename timestamps become minute offsets from the earliest one in the same session, so
    # run order and acq-vs-csv agreement survive without any real date or time of day.
    subject_entries = []
    for subject_key, sessions in subjects.items():
        session_entries = []
        for session_label, session in sessions.items():
            stamps = [file_timestamps.get(id(f)) for f in session["files"]]
            session_start = min((s for s in stamps if s is not None), default=None)
            for file_entry, stamp in zip(session["files"], stamps, strict=True):
                file_entry["timestamp_offset_minutes"] = (
                    round((stamp - session_start).total_seconds() / 60, 2)
                    if stamp is not None and session_start is not None
                    else None
                )
            session_entries.append(
                {
                    "folder": session_label,
                    "files": session["files"],
                    "other_files_by_extension": dict(session["other_files_by_extension"]),
                }
            )
        subject_entries.append({"subject": subject_key, "sessions": session_entries})

    return {
        "manifest_version": SHAPE_MANIFEST_VERSION,
        "contains": (
            "Structure only: folder layout, filename patterns, CSV headers, column cell kinds "
            "and row counts, .acq channel layout. No data values, subject ids, dates or times "
            "of day. Review before sharing."
        ),
        "n_subjects": len(subject_folders),
        "other_top_level_folders": [
            {"name": p.name, "n_files": sum(1 for f in p.rglob("*") if f.is_file())}
            for p in other_top_level_folders
        ],
        "subjects": subject_entries,
        "csv_schemas": {
            key: [{"header": json.loads(h), "n_files": n} for h, n in counts.most_common()]
            for key, counts in sorted(csv_schemas.items())
        },
        "acq_schemas": [{**json.loads(k), "n_files": n} for k, n in acq_schemas.most_common()],
    }


def write_longwalkv3_shape_manifest(data_folder: Path, output_folder: Path) -> Path:
    """Profiles data_folder (see profile_longwalkv3_shape) and writes the manifest to
    output_folder/SHAPE_MANIFEST_FILENAME. Returns the written path."""
    manifest = profile_longwalkv3_shape(data_folder)
    output_folder.mkdir(parents=True, exist_ok=True)
    manifest_path = output_folder / SHAPE_MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


# --- Shape-driven generation ------------------------------------------------------------------
#
# Builds a synthetic dataset from a shape manifest (see profile_longwalkv3_shape) instead of from
# template rows, so it can follow the *current* real export without anyone copying real data.
# What the manifest drives: folder layout (sub-<id>/ses-NN/[run-00N/]), filename patterns, which
# actor logs a run has (per city), each CSV's header, header-repeat count, row count, actor
# count, time span, column kinds, the ragged rows the real export writes, and the .acq channel
# set, sample rate and duration. Everything is resampled from whole observed file profiles, so
# combinations stay realistic. What it can't know, and therefore makes up: every cell value
# (ratings 0-10, positions, actor names, phone messages), EDA signal shape, and which classes send
# a Biopac pulse (see _NON_PULSE_SUFFIXES).

SHAPE_ERROR_TYPES = (
    "aborted_run_restarted",
    "session_folder_underscore",
    "multiple_cities_per_session",
    "malformed_subject_id_in_physiology_filename",
    "missing_subject_id_in_physiology_filename",
    "mislabeled_physiology_date",
)
SHAPE_SUBJECT_ID_PREFIX = "dummy"
# Real exports name the physiology file "<timestamp>_sub-<id>_longwalkv3out.acq".
SHAPE_ACQ_SUFFIX = "longwalkv3out"
# Classes that do *not* send a TTL per logged row. Working assumption (2026-11-18): every class
# pulses on every row, so this is empty. Unconfirmed -- likely candidates to add once the Unreal
# side documents it: "BP_HeatmapManager_C.csv" (logs at ~2 Hz), "BP_BirdsFlying_C.csv" (hundreds
# of rows in ~4 s, so its pulses merge into one long high stretch), "BP_SerialComManager_C.csv".
_NON_PULSE_SUFFIXES: tuple[str, ...] = ()
# Seen in the real data: an aborted first attempt, then a restart a few minutes later in the
# same session, each run in its own run-00N subfolder, with the .acq started at the restart.
_ABORTED_RUN_RESTART_DELAY = dt.timedelta(minutes=4)
_CSV_LEAD_IN_SECONDS = 5.0
_RATING_RANGE = (0, 10)  # real scale unknown -- the manifest only says "int"
_PHONE_MESSAGES = (
    "New message",
    "Battery low",
    "Missed call",
    "Reminder: appointment",
    "Calendar alert",
    "Weather alert, heavy rain expected",
    "Unknown number, call back?",
)
# .acq writing: AcqKnowledge 3.0.3 layout (bioread revision 35) -- the simplest one bioread
# reads: uncompressed, no padding headers, no journal, an 8-byte empty marker block.
_ACQ_WRITE_REVISION = 35
_EDA_UNITS_FULL_SCALE = 40.0
_TRIGGER_FULL_SCALE_VOLTS = 10.0


@dataclass
class _CsvFileProfile:
    suffix: str  # e.g. "BP_NPC_C.csv", or "behaviour.csv"
    city: str | None
    aborted: bool  # from a run that was later restarted in the same session
    csv: dict


@dataclass
class LongWalkV3ShapeModel:
    """What generation needs from a manifest, pre-digested (see shape_model_from_manifest)."""

    headers: dict[str, list[str]]
    profiles: list[_CsvFileProfile]
    # suffix -> city -> fraction of that city's complete runs that had this file
    presence_by_city: dict[str, dict[str, float]]
    acq_channels: list[tuple[str, str]]
    acq_samples_per_second: float
    acq_durations: list[float]
    session_folder_spellings: list[str] = field(default_factory=list)

    def suffixes(self) -> list[str]:
        return [s for s in self.headers if s != "behaviour.csv"]

    def pick_profile(self, suffix: str, city: str, aborted: bool, rng: random.Random) -> dict:
        candidates = [p for p in self.profiles if p.suffix == suffix and p.aborted == aborted]
        same_city = [p for p in candidates if p.city == city]
        pool = same_city or candidates
        if not pool:  # e.g. no aborted run observed for this suffix: header only
            return {"n_header_rows": 1, "n_data_rows": 0, "columns": []}
        return rng.choice(pool).csv

    def presence(self, suffix: str, city: str) -> float:
        by_city = self.presence_by_city.get(suffix, {})
        if city in by_city:
            return by_city[city]
        return sum(by_city.values()) / len(by_city) if by_city else 0.0


_TASK_TOKEN_PATTERN = re.compile(r"_task-(?P<city>[A-Za-z0-9]+)_")
_MASKED_RUN_SUFFIX_PATTERN = re.compile(r"_run-\d+_(?P<suffix>.+\.csv)$")


def load_shape_manifest(manifest_path: Path) -> dict:
    return json.loads(Path(manifest_path).read_text(encoding="utf-8"))


def shape_model_from_manifest(manifest: dict) -> LongWalkV3ShapeModel:
    headers = {
        suffix: variants[0]["header"]
        for suffix, variants in manifest["csv_schemas"].items()
        if variants and suffix != "other" and "{masked" not in suffix
    }
    if "behaviour.csv" not in headers:
        raise ValueError("Shape manifest has no behaviour.csv schema to generate from")
    if not manifest.get("acq_schemas"):
        raise ValueError("Shape manifest has no .acq schema to generate from")
    acq_schema = manifest["acq_schemas"][0]

    profiles: list[_CsvFileProfile] = []
    runs_per_city: Counter = Counter()
    files_per_city: dict[str, Counter] = {}
    acq_durations: list[float] = []
    spellings: list[str] = []
    for subject in manifest["subjects"]:
        for session in subject["sessions"]:
            spellings.append(session["folder"])
            csv_files = [f for f in session["files"] if f["kind"] != "acq" and "csv" in f]
            offsets = [f.get("timestamp_offset_minutes") or 0.0 for f in csv_files]
            last_offset = max(offsets, default=0.0)
            complete_runs: dict[float, tuple[str | None, set[str]]] = {}
            for file_entry, offset in zip(csv_files, offsets, strict=True):
                match = _MASKED_RUN_SUFFIX_PATTERN.search(file_entry["pattern"])
                if file_entry["kind"] == "behaviour":
                    suffix = "behaviour.csv"
                elif match:
                    suffix = match.group("suffix")
                else:
                    continue
                if suffix not in headers or file_entry["csv"].get("empty_file"):
                    continue
                city_match = _TASK_TOKEN_PATTERN.search(file_entry["pattern"])
                city = city_match.group("city") if city_match else None
                aborted = offset < last_offset
                profiles.append(_CsvFileProfile(suffix, city, aborted, file_entry["csv"]))
                if not aborted:
                    complete_runs.setdefault(offset, (city, set()))[1].add(suffix)
            for city, suffixes in complete_runs.values():
                city_key = city or "(unknown)"
                runs_per_city[city_key] += 1
                files_per_city.setdefault(city_key, Counter()).update(suffixes)
            acq_durations += [
                f["acq"]["duration_seconds"]
                for f in session["files"]
                if f["kind"] == "acq" and f.get("acq") and f["acq"].get("duration_seconds")
            ]

    presence_by_city: dict[str, dict[str, float]] = {}
    for city, n_runs in runs_per_city.items():
        for suffix in headers:
            presence_by_city.setdefault(suffix, {})[city] = (
                files_per_city.get(city, Counter())[suffix] / n_runs
            )

    return LongWalkV3ShapeModel(
        headers=headers,
        profiles=profiles,
        presence_by_city=presence_by_city,
        acq_channels=[(name, units) for name, units, _divider in acq_schema["channels"]],
        acq_samples_per_second=float(acq_schema["samples_per_second"]),
        acq_durations=acq_durations or [600.0],
        session_folder_spellings=spellings,
    )


def _column_kind(column_profile: dict | None) -> str:
    if not column_profile:
        return "empty"
    kinds = {k: v for k, v in column_profile["cell_kinds"].items() if k != "empty"}
    return max(kinds, key=lambda k: kinds[k]) if kinds else "empty"


def _first_row_only(column_profile: dict | None) -> bool:
    """A column the real export fills on the first data row only (the heatmap's corner
    vectors), leaving every later row shorter than the header."""
    if not column_profile:
        return False
    kinds = column_profile["cell_kinds"]
    filled = sum(v for k, v in kinds.items() if k != "empty")
    return kinds.get("empty", 0) > 0 and filled <= 1


def _format_shape_datetime(moment: dt.datetime, unpadded_ms: bool) -> str:
    millisecond = moment.microsecond // 1000
    if unpadded_ms:
        # Hypothesis for the real export's shorter-than-17-digit datetime cells (the manifest
        # shows them as "int"): milliseconds written without zero-padding.
        return f"{moment:%Y%m%d%H%M%S}{millisecond % 100}"
    return f"{moment:%Y%m%d%H%M%S}{millisecond:03d}"


def _random_fvector(rng: random.Random) -> str:
    return " ".join(f"{axis}={rng.uniform(-5000, 5000):.3f}" for axis in WORLD_LOCATION_AXES)


def _row_times(
    n_rows: int, span_seconds: float, window_start: dt.datetime, window_seconds: float, rng
) -> list[dt.datetime]:
    if n_rows == 0:
        return []
    span = min(span_seconds, max(window_seconds - _CSV_LEAD_IN_SECONDS, 0.0))
    start_offset = rng.uniform(
        _CSV_LEAD_IN_SECONDS, max(window_seconds - span, _CSV_LEAD_IN_SECONDS)
    )
    offsets = sorted(rng.uniform(0, span) for _ in range(n_rows))
    if n_rows > 1:
        offsets[0], offsets[-1] = 0.0, span
    return [window_start + dt.timedelta(seconds=start_offset + o) for o in offsets]


def _synthesize_actor_log(
    suffix: str,
    header: list[str],
    profile: dict,
    window_start: dt.datetime,
    window_seconds: float,
    rng: random.Random,
) -> tuple[list[str], list[dt.datetime]]:
    """Text lines of one actor log (header repeats included) plus the times of rows that
    send a Biopac pulse."""
    columns = {c["name"]: c for c in profile.get("columns", [])}
    n_rows = int(profile.get("n_data_rows", 0))
    n_header_rows = max(int(profile.get("n_header_rows", 1)), 1)
    datetime_profile = columns.get("datetime")
    span = float((datetime_profile or {}).get("span_seconds", min(window_seconds, 60.0)))
    times = _row_times(n_rows, span, window_start, window_seconds, rng)

    kinds = (datetime_profile or {}).get("cell_kinds", {})
    unpadded_fraction = kinds.get("int", 0) / max(sum(kinds.values()), 1)
    actor_count = max(1, min(int(columns.get("actor", {}).get("n_distinct_text", 1)), n_rows or 1))
    class_name = suffix.removesuffix(".csv")
    actors = [f"{class_name}_{i}" for i in range(actor_count)]
    row_actors = actors[:n_rows] + [rng.choice(actors) for _ in range(n_rows - len(actors))]
    rng.shuffle(row_actors)

    message_profile = columns.get("message")
    comma_fraction = profile.get("n_rows_with_wrong_width", 0) / max(n_rows, 1)
    first_row_only = [name for name in header if _first_row_only(columns.get(name))]
    n_distinct_flags = int(columns.get("isFearCue", {}).get("n_distinct_text", 2))

    lines = [",".join(header)] * n_header_rows
    for row_index, (moment, actor) in enumerate(zip(times, row_actors, strict=True)):
        cells = []
        for name in header:
            if name in first_row_only and row_index > 0:
                continue  # ragged like the real export: later rows stop short
            if name == "datetime":
                cells.append(_format_shape_datetime(moment, rng.random() < unpadded_fraction))
            elif name in ("actor", TRIGGER_COLUMN):
                cells.append(actor)
            elif name == "isFearCue":
                cells.append(rng.choice(("True", "False")[:n_distinct_flags]))
            elif name == "message" and message_profile is not None:
                with_comma = rng.random() < comma_fraction
                options = [m for m in _PHONE_MESSAGES if ("," in m) == with_comma]
                cells.append(rng.choice(options))  # unquoted on purpose, like the real export
            elif _column_kind(columns.get(name)) == "fvector":
                cells.append(_random_fvector(rng))
            elif _column_kind(columns.get(name)) in ("int", "float"):
                cells.append(str(rng.randint(0, 100)))
            else:
                cells.append("")
        lines.append(",".join(cells))

    pulse_times = (
        []
        if suffix in _NON_PULSE_SUFFIXES
        else [t + dt.timedelta(milliseconds=rng.randint(*TRIGGER_LAG_MS_RANGE)) for t in times]
    )
    return lines, pulse_times


def _synthesize_behaviour(
    header: list[str],
    profile: dict,
    window_start: dt.datetime,
    window_seconds: float,
    rng: random.Random,
) -> list[str]:
    n_rows = int(profile.get("n_data_rows", 0))
    n_header_rows = max(int(profile.get("n_header_rows", 1)), 1)
    lines = [",".join(header)] * n_header_rows
    if n_rows == 0:
        return lines
    step = max(window_seconds - 2 * _CSV_LEAD_IN_SECONDS, 0.0) / n_rows
    for row_index in range(n_rows):
        moment = window_start + dt.timedelta(seconds=_CSV_LEAD_IN_SECONDS + step * (row_index + 1))
        cells = [
            f"{moment:%H%M}"
            if name.lower().startswith("timestamp")
            else str(rng.randint(*_RATING_RANGE))
            for name in header
        ]
        lines.append(",".join(cells))
    return lines


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _synthetic_eda(
    n_samples: int, samples_per_second: float, pulse_seconds: list[float], np_rng
) -> np.ndarray:
    """Tonic level with slow drift plus skin-conductance responses: ~1-3 s after a share of
    the pulses, and some spontaneous ones. Plausible-looking, not physiologically modelled."""
    seconds = n_samples / samples_per_second
    knots = np.arange(0, seconds + 10, 10.0)
    tonic = np_rng.uniform(2.0, 8.0) + np.cumsum(np_rng.normal(0, 0.05, size=len(knots)))
    signal = np.interp(np.arange(n_samples) / samples_per_second, knots, tonic)

    onsets = [t + np_rng.uniform(1.0, 3.0) for t in pulse_seconds if np_rng.random() < 0.6]
    onsets += list(np_rng.uniform(0, seconds, size=int(seconds / 60 * 2)))
    kernel_t = np.arange(0, 20, 1 / samples_per_second)
    kernel = np.exp(-kernel_t / 4.0) - np.exp(-kernel_t / 0.75)
    kernel /= kernel.max()
    for onset in onsets:
        start = int(onset * samples_per_second)
        if start >= n_samples:
            continue
        stop = min(start + len(kernel), n_samples)
        signal[start:stop] += np_rng.uniform(0.05, 0.8) * kernel[: stop - start]
    return np.clip(signal + np_rng.normal(0, 0.005, size=n_samples), 0, None)


def _synthetic_trigger(
    n_samples: int, samples_per_second: float, pulse_seconds: list[float], np_rng
) -> np.ndarray:
    volts = TRIGGER_BASELINE_VOLTS + np_rng.normal(0, ACQ_TRIGGER_NOISE_VOLTS, size=n_samples)
    width = int(round(TRIGGER_PULSE_DURATION_SECONDS * samples_per_second))
    for t in pulse_seconds:
        start = int(round(t * samples_per_second))
        if 0 <= start and start + width <= n_samples:
            volts[start : start + width] = TRIGGER_HIGH_VOLTS
    return volts


def _packed_header(header_class, **values) -> bytes:
    header = header_class.for_revision(_ACQ_WRITE_REVISION, "<", encoding="latin1")
    struct = header._struct_class()
    for name, value in values.items():
        setattr(struct, name, value)
    return bytes(struct)


def _header_length(header_class) -> int:
    return header_class.for_revision(_ACQ_WRITE_REVISION, "<", encoding="latin1").struct_length


def write_synthetic_acq(
    acq_path: Path,
    channels: list[tuple[str, str, np.ndarray, float]],
    samples_per_second: float,
) -> None:
    """Writes an uncompressed AcqKnowledge file bioread reads back: channels are (name, units,
    values, full_scale), all the same length and rate, stored as int16 scaled so that
    +/-full_scale fits. Built from bioread's own header structs, so the byte layout is exactly
    what its reader expects."""
    from bioread import headers as bh

    n_samples = len(channels[0][2])
    graph_length = _header_length(bh.GraphHeader)
    channel_length = _header_length(bh.ChannelHeader)
    parts = [
        _packed_header(
            bh.GraphHeader,
            nItemHeaderLen=graph_length,
            lVersion=_ACQ_WRITE_REVISION,
            lExtItemHeaderLen=graph_length,
            nChannels=len(channels),
            dSampleTime=1000.0 / samples_per_second,
            szHorizUnits1=b"sec",
        )
    ]
    raw_columns = []
    for index, (name, units, values, full_scale) in enumerate(channels):
        scale = full_scale / 32767
        raw_columns.append(np.clip(np.round(values / scale), -32768, 32767).astype("<i2"))
        parts.append(
            _packed_header(
                bh.ChannelHeader,
                lChanHeaderLen=channel_length,
                nNum=index,
                szCommentText=name.encode("latin1")[:39],
                nDispChan=1,
                dVoltScale=1.0,
                szUnitsText=units.encode("latin1")[:19],
                lBufLength=n_samples,
                dAmplScale=scale,
                dAmplOffset=0.0,
                nChanOrder=index,
            )
        )
    parts.append(_packed_header(bh.ForeignHeader, nLength=_header_length(bh.ForeignHeader)))
    parts += [_packed_header(bh.ChannelDTypeHeader, nSize=2, nType=2) for _ in channels]
    parts.append(np.column_stack(raw_columns).astype("<i2").tobytes())
    parts.append(_packed_header(bh.MarkerHeader, lLength=8, lMarkers=0))
    acq_path.parent.mkdir(parents=True, exist_ok=True)
    acq_path.write_bytes(b"".join(parts))


def _shape_acq_filename(
    timestamp: dt.datetime, subject_id: str, error_type: str | None, is_error_session: bool
) -> str:
    if is_error_session and error_type == "mislabeled_physiology_date":
        timestamp += MISLABELED_PHYSIOLOGY_DATE_SHIFT
    id_part = f"sub-{subject_id}"
    if is_error_session and error_type == "malformed_subject_id_in_physiology_filename":
        id_part = f"sub-{_malformed_subject_id(subject_id)}"
    elif is_error_session and error_type == "missing_subject_id_in_physiology_filename":
        id_part = ""
    return f"{timestamp:%Y%m%d%H%M}_{id_part}_{SHAPE_ACQ_SUFFIX}.acq"


def _write_shape_run(
    model: LongWalkV3ShapeModel,
    run_folder: Path,
    file_prefix: str,
    city: str,
    window_start: dt.datetime,
    window_seconds: float,
    aborted: bool,
    rng: random.Random,
) -> tuple[Path, list[Path], list[dt.datetime]]:
    behaviour_profile = model.pick_profile("behaviour.csv", city, aborted, rng)
    behaviour_path = run_folder / f"{file_prefix}_behaviour.csv"
    _write_lines(
        behaviour_path,
        _synthesize_behaviour(
            model.headers["behaviour.csv"], behaviour_profile, window_start, window_seconds, rng
        ),
    )
    actor_log_paths = []
    pulse_times: list[dt.datetime] = []
    for suffix in model.suffixes():
        if rng.random() >= model.presence(suffix, city):
            continue
        profile = model.pick_profile(suffix, city, aborted, rng)
        lines, pulses = _synthesize_actor_log(
            suffix, model.headers[suffix], profile, window_start, window_seconds, rng
        )
        path = run_folder / f"{file_prefix}_{suffix}"
        _write_lines(path, lines)
        actor_log_paths.append(path)
        pulse_times += pulses
    return behaviour_path, actor_log_paths, pulse_times


def generate_shape_participant(
    model: LongWalkV3ShapeModel,
    output_folder: Path,
    subject_id: str,
    subject_index: int,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
    error_type: str | None = None,
    rng: random.Random | None = None,
) -> DummyLongWalkV3ParticipantResult:
    """One synthetic participant in the real export's layout: sub-<id>/ses-NN/ holding one
    .acq plus one behaviour.csv and actor logs per run (in run-00N/ subfolders when a session
    has a restarted run). `error_type` is one of SHAPE_ERROR_TYPES or None (clean)."""
    rng = rng or random.Random()
    np_rng = np.random.default_rng(rng.getrandbits(32))
    layout_error = error_type if error_type == "multiple_cities_per_session" else None
    layout = build_session_city_layout(city_labels, layout_error, rng)
    error_session = rng.randrange(len(layout))
    if error_type == "mislabeled_physiology_date":
        error_session = len(layout) - 1

    subject_folder = output_folder / f"sub-{subject_id}"
    acq_paths, behaviour_paths, actor_log_paths = [], [], []
    for session_index, (session_token, cities) in enumerate(layout):
        is_error_session = session_index == error_session
        folder_name = session_token
        if error_type == "session_folder_underscore" and is_error_session:
            folder_name = session_token.replace("-", "_")
        session_folder = subject_folder / folder_name
        session_start = _session_day(subject_index, session_index)
        duration = rng.uniform(min(model.acq_durations), max(model.acq_durations))

        restarted = error_type == "aborted_run_restarted" and is_error_session
        # (city, run start, run folder name or "", aborted?)
        runs: list[tuple[str, dt.datetime, str, bool]] = []
        if restarted:
            runs.append((cities[0], session_start, "run-001", True))
            runs.append((cities[0], session_start + _ABORTED_RUN_RESTART_DELAY, "run-002", False))
        else:
            runs += [
                (city, session_start + i * _ABORTED_RUN_RESTART_DELAY, "", False)
                for i, city in enumerate(cities)
            ]
        acq_start = runs[-1][1] if restarted else session_start

        pulse_times: list[dt.datetime] = []
        for run_number, (city, run_start, run_folder_name, aborted) in enumerate(runs, start=1):
            prefix = (
                f"{run_start:%Y%m%d%H%M}_sub-{subject_id}_{session_token}_task-{city}"
                f"_run-{run_number}"
            )
            window = duration if not aborted else duration * rng.uniform(0.15, 0.3)
            if not restarted and len(runs) > 1:
                window = duration / len(runs)
            behaviour_path, logs, pulses = _write_shape_run(
                model,
                session_folder / run_folder_name if run_folder_name else session_folder,
                prefix,
                city,
                run_start,
                window,
                aborted,
                rng,
            )
            behaviour_paths.append(behaviour_path)
            actor_log_paths += logs
            pulse_times += pulses

        n_samples = int(duration * model.acq_samples_per_second)
        pulse_seconds = [(t - acq_start).total_seconds() for t in pulse_times]
        channels = []
        for name, units in model.acq_channels:
            if name == ACQ_TRIGGER_CHANNEL_NAME:
                values = _synthetic_trigger(
                    n_samples, model.acq_samples_per_second, pulse_seconds, np_rng
                )
                channels.append((name, units, values, _TRIGGER_FULL_SCALE_VOLTS))
            else:
                values = _synthetic_eda(
                    n_samples, model.acq_samples_per_second, pulse_seconds, np_rng
                )
                channels.append((name, units, values, _EDA_UNITS_FULL_SCALE))
        acq_path = session_folder / _shape_acq_filename(
            acq_start, subject_id, error_type, is_error_session
        )
        write_synthetic_acq(acq_path, channels, model.acq_samples_per_second)
        acq_paths.append(acq_path)

    return DummyLongWalkV3ParticipantResult(
        subject_id,
        error_type or CLEAN_SCENARIO_LABEL,
        acq_paths,
        behaviour_paths,
        actor_log_paths,
    )


def generate_dummy_longwalkv3_dataset_from_shape(
    manifest_path: Path,
    output_folder: Path,
    n_clean: int = 1,
    with_errors: bool = False,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
    seed: int | None = None,
) -> DummyLongWalkV3DatasetResult:
    """Synthetic dataset modelled on a shape manifest: `n_clean` well-formed participants,
    plus one per SHAPE_ERROR_TYPES entry if `with_errors`."""
    model = shape_model_from_manifest(load_shape_manifest(manifest_path))
    output_folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    scenarios: list[str | None] = [None] * n_clean
    if with_errors:
        scenarios += list(SHAPE_ERROR_TYPES)

    results = []
    for index, error_type in enumerate(scenarios):
        subject_id = f"{SHAPE_SUBJECT_ID_PREFIX}{index + 1:02d}"
        logger.info(
            "Generating shape-based longwalkv3 participant %s (%s)",
            subject_id,
            error_type or CLEAN_SCENARIO_LABEL,
        )
        results.append(
            generate_shape_participant(
                model, output_folder, subject_id, index, city_labels, error_type, rng
            )
        )
    return DummyLongWalkV3DatasetResult(results, None)
