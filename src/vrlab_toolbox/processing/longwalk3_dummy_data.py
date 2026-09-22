import csv
import datetime as dt
import logging
import random
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

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
ERROR_TYPES = ("multiple_cities_per_session",)
SCENARIO_DESCRIPTIONS: dict[str, str] = {
    CLEAN_SCENARIO_LABEL: (
        "One city's behaviour/actor-log file set per session (ses-01=city1, ses-02=city2, "
        "...) -- the well-formed layout."
    ),
    "multiple_cities_per_session": (
        "Still the standard number of sessions (one per requested city), but one randomly "
        "chosen session gets two runs instead of one -- the wrong city first (as if it was "
        "started by mistake), then that session's actually-planned city. Both are written as "
        "run-000, the same as the real Unreal-side export always does -- exercises detection "
        "of a session with more than one run/city, without it always being the same session."
    ),
}

DATE_PART_COLUMNS = ("year", "month", "day", "hour", "minute", "second", "millisecond")
WORLD_LOCATION_AXES = ("X", "Y", "Z")

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
    matches = [p for p in sorted(template_folder.glob("*.csv")) if _REDCAP_EXPORT_PATTERN.match(p.name)]
    if not matches:
        raise FileNotFoundError(f"No template REDCap debrief export csv found under {template_folder}")
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
    matches = [p for p in sorted(template_folder.glob("*.csv")) if _BEHAVIOUR_SUFFIX_PATTERN.search(p.name)]
    if not matches:
        raise FileNotFoundError(f"No template behaviour csv found under {template_folder}")
    return matches[0]


def discover_actor_log_templates(template_folder: Path) -> dict[str, Path]:
    """Maps each actor-location log's filename suffix (e.g. "BP_NPC_C.csv") to its template
    path, for every *_run-<n>_<suffix>.csv file under template_folder that isn't the behaviour
    file.
    """
    templates: dict[str, Path] = {}
    for csv_path in sorted(template_folder.glob("*.csv")):
        if _BEHAVIOUR_SUFFIX_PATTERN.search(csv_path.name):
            continue
        match = _ACTOR_LOG_SUFFIX_PATTERN.search(csv_path.name)
        if match:
            templates[match.group("suffix")] = csv_path

    if not templates:
        raise FileNotFoundError(f"No template actor-location log csvs found under {template_folder}")
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


def _combine_date(row: list[str], date_part_index: dict[str, int], rng: random.Random) -> str:
    # The template's own millisecond cell is just a placeholder (no real sub-second value has
    # ever been recorded by the Unreal-side export) -- a random one is generated per row instead
    # so dummy data doesn't leave every event's millisecond fixed at the same value.
    year, month, day, hour, minute, second = (
        int(row[date_part_index[name]]) for name in DATE_PART_COLUMNS if name != "millisecond"
    )
    millisecond = rng.randint(0, 999)
    return f"{year:04d}{month:02d}{day:02d}{hour:02d}{minute:02d}{second:02d}{millisecond:03d}"


def _combine_world_location(row: list[str], location_index: dict[str, int]) -> str:
    return " ".join(f"{axis}={row[location_index[axis]]}" for axis in WORLD_LOCATION_AXES)


def reshape_actor_log(
    header: list[str], rows: list[list[str]], rng: random.Random
) -> tuple[list[str], list[list[str]]]:
    """Replaces year/month/day/hour/minute/second/millisecond with a single "date" column
    (concatenated yyyyMMddHHmmssSSS, e.g. "20260916175501873" -- the millisecond part is
    randomly generated per row via rng, since the template CSVs don't carry a real recorded
    value yet -- see _combine_date) and worldLocationX/Y/Z with a single "worldLocation" column
    column (formatted the way an Unreal FVector prints via ToString(), e.g. "X=1.0 Y=2.0
    Z=3.0"). Any other column (actor, isFearCue, ...) is kept in place. Rows are otherwise
    unchanged. If header doesn't have both groups of columns (e.g. behaviour.csv), it's
    returned unchanged.
    """
    header_lower = [column.lower() for column in header]

    date_part_index = {name: header_lower.index(name) for name in DATE_PART_COLUMNS if name in header_lower}
    location_index = {
        axis: header_lower.index(f"worldlocation{axis.lower()}")
        for axis in WORLD_LOCATION_AXES
        if f"worldlocation{axis.lower()}" in header_lower
    }

    if len(date_part_index) != len(DATE_PART_COLUMNS) or len(location_index) != len(WORLD_LOCATION_AXES):
        return header, rows

    combined_indices = set(date_part_index.values()) | set(location_index.values())
    date_insert_at = min(date_part_index.values())
    location_insert_at = min(location_index.values())

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
            row, _combine_date(row, date_part_index, rng), _combine_world_location(row, location_index)
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


def _multiple_cities_per_session_layout(city_labels: tuple[str, ...], rng: random.Random) -> list[list[str]]:
    """One randomly chosen session's planned city is preceded by a run in a different, randomly
    chosen city -- e.g. ses-02 was planned as city2, but city3 got run first by mistake, then
    city2 was run afterwards to correct it (both written as run-000 -- see
    generate_dummy_longwalkv3_participant). Every other session keeps its single planned-city
    run. Still exactly len(city_labels) sessions -- only the run count within one of them
    changes.
    """
    if len(city_labels) < 2:
        raise ValueError("Need at least 2 cities to model a wrong-city run.")

    session_city_runs: list[list[str]] = [[city] for city in city_labels]

    error_session_index = rng.randrange(len(city_labels))
    planned_city = city_labels[error_session_index]
    wrong_city = rng.choice([city for city in city_labels if city != planned_city])
    session_city_runs[error_session_index] = [wrong_city, planned_city]

    return session_city_runs


def build_session_city_layout(
    city_labels: tuple[str, ...], error_type: str | None = None, rng: random.Random | None = None
) -> list[tuple[str, list[str]]]:
    """Maps each session token to the ordered list of cities run under it -- one entry per run
    (see generate_dummy_longwalkv3_participant for how each is turned into a filename).

    error_type=None (clean): one city, one run, per session -- ses-01=city_labels[0],
    ses-02=city_labels[1], ... error_type="multiple_cities_per_session": still exactly that many
    sessions, but one of them instead gets two runs, a wrong city then its correct one (see
    _multiple_cities_per_session_layout) -- requires rng.
    """
    if error_type is None:
        session_city_runs: list[list[str]] = [[city] for city in city_labels]
    elif error_type == "multiple_cities_per_session":
        if rng is None:
            raise ValueError("rng is required for error_type='multiple_cities_per_session'")
        session_city_runs = _multiple_cities_per_session_layout(city_labels, rng)
    else:
        raise ValueError(f"error_type must be one of {ERROR_TYPES}, got {error_type!r}")

    return [(f"ses-{index + 1:02d}", cities) for index, cities in enumerate(session_city_runs)]


def generate_dummy_longwalkv3_participant(
    template_folder: Path,
    output_folder: Path,
    subject_id: str,
    subject_index: int,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
    error_type: str | None = None,
    rng: random.Random | None = None,
) -> DummyLongWalkV3ParticipantResult:
    # Only required by build_session_city_layout for error_type="multiple_cities_per_session",
    # but also used below to randomize each actor-log row's millisecond value -- falls back to
    # an unseeded Random so a direct call without rng (the clean-scenario case) still works.
    rng = rng or random.Random()
    acq_template = discover_acq_template(template_folder)
    behaviour_template = discover_behaviour_template(template_folder)
    actor_log_templates = discover_actor_log_templates(template_folder)

    behaviour_header, behaviour_header_repeat_count, behaviour_rows = _read_repeated_header_csv(
        behaviour_template
    )

    acq_paths = []
    behaviour_paths = []
    actor_log_paths = []
    for session_index, (session_token, session_city_runs) in enumerate(
        build_session_city_layout(city_labels, error_type, rng)
    ):
        session_day = _session_day(subject_index, session_index)

        # One physiology recording per session -- it can't span the multiple days different
        # sessions now fall on -- started once, before that session's first exported run.
        acq_path = (
            output_folder / f"{_acq_timestamp(session_day)}_{subject_id}_LongWalkV3Out.acq"
        )
        shutil.copyfile(acq_template, acq_path)
        acq_paths.append(acq_path)

        for run_index, city_label in enumerate(session_city_runs):
            csv_timestamp = _run_csv_timestamp(session_day, run_index)
            # The real Unreal-side export never counts runs up -- every run is written as
            # "run-000" and it's the BIDS pipeline's job to sort out true run numbers later
            # (see longwalk3_bids.py's RUN_TOKEN TODO). Two runs in the same session/city pair
            # would collide, but the multiple-cities error only ever pairs a session with two
            # *different* cities, so the filenames stay distinct on task-<city> alone.
            run_token = "run-000"
            behaviour_path = (
                output_folder
                / f"{csv_timestamp}_{subject_id}_{session_token}_task-{city_label}_{run_token}_behaviour.csv"
            )
            _write_repeated_header_csv(
                behaviour_path, behaviour_header, behaviour_header_repeat_count, behaviour_rows
            )
            behaviour_paths.append(behaviour_path)

            for suffix, template_path in actor_log_templates.items():
                header, header_repeat_count, rows = _read_repeated_header_csv(template_path)
                new_header, new_rows = reshape_actor_log(header, rows, rng)
                actor_log_path = (
                    output_folder
                    / f"{csv_timestamp}_{subject_id}_{session_token}_task-{city_label}_{run_token}_{suffix}"
                )
                _write_repeated_header_csv(actor_log_path, new_header, header_repeat_count, new_rows)
                actor_log_paths.append(actor_log_path)

    scenario = error_type or CLEAN_SCENARIO_LABEL
    return DummyLongWalkV3ParticipantResult(subject_id, scenario, acq_paths, behaviour_paths, actor_log_paths)


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
