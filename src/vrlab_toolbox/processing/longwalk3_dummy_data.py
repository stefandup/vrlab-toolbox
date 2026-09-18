import csv
import datetime as dt
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CITY_LABELS = ("city1", "city2", "city3")
BASE_TIMESTAMP = dt.datetime(2026, 9, 16, 17, 30)
CSV_TIMESTAMP_OFFSET = dt.timedelta(minutes=13)
SUBJECT_TIMESTAMP_STEP = dt.timedelta(minutes=30)

DATE_PART_COLUMNS = ("year", "month", "day", "hour", "minute", "second")
WORLD_LOCATION_AXES = ("X", "Y", "Z")

# Suffix (everything after "..._run-<n>_") of each actor-location log template found in
# longwalkv3_examples/ -- used to find each one under template_folder regardless of its
# timestamp/subject-id/run prefix.
_ACTOR_LOG_SUFFIX_PATTERN = re.compile(r"_run-\d+_(?P<suffix>.+\.csv)$")
_BEHAVIOUR_SUFFIX_PATTERN = re.compile(r"_run-\d+_behaviour\.csv$")


@dataclass
class DummyLongWalkV3ParticipantResult:
    subject_id: str
    acq_path: Path
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


def _combine_date(row: list[str], date_part_index: dict[str, int]) -> str:
    year, month, day, hour, minute, second = (
        int(row[date_part_index[name]]) for name in DATE_PART_COLUMNS
    )
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def _combine_world_location(row: list[str], location_index: dict[str, int]) -> str:
    return " ".join(f"{axis}={row[location_index[axis]]}" for axis in WORLD_LOCATION_AXES)


def reshape_actor_log(header: list[str], rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    """Replaces year/month/day/hour/minute/second with a single "date" column (ISO 8601) and
    worldLocationX/Y/Z with a single "worldLocation" column (formatted the way an Unreal FVector
    prints via ToString(), e.g. "X=1.0 Y=2.0 Z=3.0"). Any other column (actor, isFearCue, ...)
    is kept in place. Rows are otherwise unchanged. If header doesn't have both groups of
    columns (e.g. behaviour.csv), it's returned unchanged.
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
        reshape_row(row, _combine_date(row, date_part_index), _combine_world_location(row, location_index))
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


def _subject_timestamps(index: int) -> tuple[str, str]:
    acq_dt = BASE_TIMESTAMP + index * SUBJECT_TIMESTAMP_STEP
    csv_dt = acq_dt + CSV_TIMESTAMP_OFFSET
    return acq_dt.strftime("%Y%m%d%H%M"), csv_dt.strftime("%Y%m%d%H%M")


def generate_dummy_longwalkv3_participant(
    template_folder: Path,
    output_folder: Path,
    subject_id: str,
    csv_timestamp: str,
    acq_timestamp: str,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
) -> DummyLongWalkV3ParticipantResult:
    acq_template = discover_acq_template(template_folder)
    behaviour_template = discover_behaviour_template(template_folder)
    actor_log_templates = discover_actor_log_templates(template_folder)

    acq_path = output_folder / f"{acq_timestamp}_{subject_id}_LongWalkV3Out.acq"
    shutil.copyfile(acq_template, acq_path)

    behaviour_header, behaviour_header_repeat_count, behaviour_rows = _read_repeated_header_csv(
        behaviour_template
    )

    behaviour_paths = []
    actor_log_paths = []
    for city_label in city_labels:
        behaviour_path = (
            output_folder / f"{csv_timestamp}_{subject_id}_ses-01task-{city_label}_run-000_behaviour.csv"
        )
        _write_repeated_header_csv(
            behaviour_path, behaviour_header, behaviour_header_repeat_count, behaviour_rows
        )
        behaviour_paths.append(behaviour_path)

        for suffix, template_path in actor_log_templates.items():
            header, header_repeat_count, rows = _read_repeated_header_csv(template_path)
            new_header, new_rows = reshape_actor_log(header, rows)
            actor_log_path = (
                output_folder / f"{csv_timestamp}_{subject_id}_ses-01_task-{city_label}_run-000_{suffix}"
            )
            _write_repeated_header_csv(actor_log_path, new_header, header_repeat_count, new_rows)
            actor_log_paths.append(actor_log_path)

    return DummyLongWalkV3ParticipantResult(subject_id, acq_path, behaviour_paths, actor_log_paths)


def generate_dummy_longwalkv3_dataset(
    template_folder: Path,
    output_folder: Path,
    n_subjects: int = 1,
    city_labels: tuple[str, ...] = DEFAULT_CITY_LABELS,
) -> list[DummyLongWalkV3ParticipantResult]:
    output_folder.mkdir(parents=True, exist_ok=True)

    results = []
    for index in range(n_subjects):
        subject_id = f"dummy{index + 1:02d}"
        acq_timestamp, csv_timestamp = _subject_timestamps(index)
        logger.info("Generating dummy longwalkv3 participant %s", subject_id)
        results.append(
            generate_dummy_longwalkv3_participant(
                template_folder, output_folder, subject_id, csv_timestamp, acq_timestamp, city_labels
            )
        )

    return results
