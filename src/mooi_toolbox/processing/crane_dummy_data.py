import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pandera.pandas as pa
import scipy.io as sio

from mooi_toolbox.processing.biopac import clean_biopac_labels
from mooi_toolbox.processing.crane_behaviour import (
    EMOTIONS_TESTED,
    build_crane_raw_behav_file_schema,
)
from mooi_toolbox.processing.crane_debrief_behaviour import (
    GROUP_REDCAP_GLOB,
    crane_raw_debrief_file_schema,
)

logger = logging.getLogger(__name__)

ERROR_TYPES = (
    "missing_physiology",
    "missing_behaviour",
    "missing_debrief",
    "date_mismatch",
    "bad_trigger_count",
    "short_trigger",
)

# Trigger-anomaly scenarios driven by a reference recording's pulse timing rather than a random
# choice — see generate_dummy_participant_matching_reference().
REFERENCE_ERROR_TYPES = (
    "missing_initial_trigger",
    "missing_last_trigger",
    "double_initial_trigger",
)
MIN_DOUBLE_TRIGGER_GAP_SECONDS = 0.5

RATING_COLUMNS = ("Nausea", "Dizzy", "Stressed")
OUTCOME_COUNT_COLUMNS = (
    "CurrentScore",
    "TotalDropped",
    "nrFrustrationBarrels",
    "NrErrorSlips",
    "NrSlips",
    "NrOtherSlips",
    "NrNoReasonSlips",
    "NrForcedSlips",
)
TRIGGER_PULSE_GAP_SECONDS = 3.0
# A literal filename matching GROUP_REDCAP_GLOB's wildcard -- the dummy debrief data doesn't
# have a real export date, so the wildcard is filled with a fixed token instead.
DUMMY_GROUP_DEBRIEF_FN = GROUP_REDCAP_GLOB.replace("*", "dummy")

CLEAN_SCENARIO_LABEL = "clean"
# One-line explanation of what each scenario is for, keyed the same way generate_dummy_participant
# labels its DummyParticipantResult.scenario (error_type, or CLEAN_SCENARIO_LABEL for None) --
# written into every dummy folder's log so a human opening it later doesn't have to read this
# module's source to know why e.g. one participant has no physiology file.
SCENARIO_DESCRIPTIONS: dict[str, str] = {
    CLEAN_SCENARIO_LABEL: (
        "Well-formed participant -- physiology, behaviour and debrief all present. Exercises "
        "the ordinary happy-path conversion/pipeline run."
    ),
    "missing_physiology": (
        "No .mat physiology file generated -- exercises handling of a subject with no "
        "physiology recording."
    ),
    "missing_behaviour": (
        "No behaviour .csv file generated -- exercises handling of a subject with no "
        "behaviour recording."
    ),
    "missing_debrief": (
        "No debrief row added to the group export -- exercises handling of a subject whose "
        "debrief never got exported (e.g. a record_id mismatch)."
    ),
    "date_mismatch": (
        "Behaviour and physiology files carry different date prefixes -- exercises detection "
        "of an inconsistent acquisition date across a subject's raw files."
    ),
    "bad_trigger_count": (
        "One interior trigger pulse is flattened out of the physiology trigger channel -- "
        "exercises detection of a wrong overall trigger count."
    ),
    "short_trigger": (
        "An extra trigger pulse is inserted shortly after a real one -- exercises detection "
        "of an anomalously short inter-trigger interval."
    ),
    "missing_initial_trigger": (
        "The first trigger pulse is flattened out -- exercises detection of a recording "
        "that's missing its initial trigger."
    ),
    "missing_last_trigger": (
        "The last trigger pulse is flattened out -- exercises detection of a recording "
        "that's missing its final trigger."
    ),
    "double_initial_trigger": (
        "The first trigger pulse is duplicated shortly after itself -- exercises detection "
        "of a double initial trigger."
    ),
}
DUMMY_DATA_LOG_FILENAME = "dummy_data_log.txt"


@dataclass
class DummyParticipantResult:
    subject_id: str
    scenario: str
    csv_path: Path | None
    mat_path: Path | None


def discover_template_pairs(template_folder: Path) -> list[tuple[Path, Path]]:
    pairs = [
        (csv_path, csv_path.with_suffix(".mat"))
        for csv_path in sorted(template_folder.glob("*_CraneOut.csv"))
        if csv_path.with_suffix(".mat").exists()
    ]
    if not pairs:
        raise FileNotFoundError(f"No template CraneOut csv/mat pairs found under {template_folder}")
    return pairs


def _mutate_behaviour_df(behav_df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    mutated = behav_df.copy()
    n_rows = len(mutated)

    for column in OUTCOME_COUNT_COLUMNS:
        mutated[column] = rng.integers(0, int(mutated[column].max()) + 3, size=n_rows)

    mutated["AvgVelocity"] = np.clip(
        mutated["AvgVelocity"] + rng.normal(0, 10, size=n_rows), 0, None
    )

    for column in RATING_COLUMNS:
        mutated[column] = rng.integers(1, 6, size=n_rows)

    mutated["EmotionFeedback"] = rng.choice(EMOTIONS_TESTED, size=n_rows)

    return build_crane_raw_behav_file_schema().validate(mutated)


def _trigger_channel_index(mat_dict: dict) -> int:
    return clean_biopac_labels(mat_dict["labels"]).index("Trigger")


def _sampling_freq_hz(mat_dict: dict) -> float:
    isi_ms = float(np.squeeze(mat_dict["isi"]))
    return 1000.0 / isi_ms


def _rising_edge_indices(trigger: np.ndarray) -> np.ndarray:
    return np.where(np.diff(trigger) > 0.47)[0] + 1


def _flatten_pulse_at_edge(trigger: np.ndarray, edge_index: int) -> np.ndarray:
    """Flattens the single trigger pulse starting at edge_index down to its pre-pulse baseline."""
    mutated = trigger.copy()
    baseline = mutated[edge_index - 1]
    high_value = mutated[edge_index]

    end = edge_index
    while end < len(mutated) - 1 and abs(mutated[end] - high_value) < 0.47:
        end += 1

    mutated[edge_index:end] = baseline
    return mutated


def _insert_pulse_after(
    trigger: np.ndarray,
    edge_index: int,
    gap_seconds: float,
    sampling_freq_hz: float,
    burst_seconds: float = 0.1,
) -> np.ndarray:
    """Inserts a brief extra high-voltage burst gap_seconds after the pulse starting at edge_index."""
    mutated = trigger.copy()
    high_value = mutated[edge_index]

    gap_samples = int(gap_seconds * sampling_freq_hz)
    burst_samples = max(int(burst_seconds * sampling_freq_hz), 1)
    insert_start = edge_index + gap_samples
    insert_end = min(insert_start + burst_samples, len(mutated))

    mutated[insert_start:insert_end] = high_value
    return mutated


def _remove_one_trigger_pulse(trigger: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Flattens one random interior trigger pulse to baseline, dropping one rising edge."""
    edges = _rising_edge_indices(trigger)
    interior_edges = edges[(edges > len(trigger) * 0.1) & (edges < len(trigger) * 0.9)]
    chosen = int(rng.choice(interior_edges))
    return _flatten_pulse_at_edge(trigger, chosen)


def _remove_first_trigger_pulse(trigger: np.ndarray) -> np.ndarray:
    """Flattens the first trigger pulse, reproducing a missing-initial-trigger recording."""
    edges = _rising_edge_indices(trigger)
    if len(edges) < 2:
        raise ValueError("Trigger channel has too few pulses to drop the initial one.")
    return _flatten_pulse_at_edge(trigger, int(edges[0]))


def _remove_last_trigger_pulse(trigger: np.ndarray) -> np.ndarray:
    """Flattens the last trigger pulse, reproducing a missing-final-trigger recording."""
    edges = _rising_edge_indices(trigger)
    if len(edges) < 2:
        raise ValueError("Trigger channel has too few pulses to drop the last one.")
    return _flatten_pulse_at_edge(trigger, int(edges[-1]))


def _insert_short_trigger_pulse(
    trigger: np.ndarray, rng: np.random.Generator, sampling_freq_hz: float
) -> np.ndarray:
    """Adds a brief extra pulse shortly after a random real one, producing an anomalously short interval."""
    edges = _rising_edge_indices(trigger)
    interior_edges = edges[(edges > len(trigger) * 0.1) & (edges < len(trigger) * 0.8)]
    chosen = int(rng.choice(interior_edges))
    return _insert_pulse_after(trigger, chosen, TRIGGER_PULSE_GAP_SECONDS, sampling_freq_hz)


def _insert_double_initial_trigger_pulse(
    trigger: np.ndarray, sampling_freq_hz: float, gap_seconds: float
) -> np.ndarray:
    """Duplicates the first pulse shortly after itself, reproducing a double-initial-trigger recording."""
    edges = _rising_edge_indices(trigger)
    if len(edges) == 0:
        raise ValueError("Trigger channel has no pulses to duplicate.")
    return _insert_pulse_after(trigger, int(edges[0]), gap_seconds, sampling_freq_hz)


@dataclass
class ReferenceTriggerProfile:
    """
    Trigger-channel timing fingerprint measured from a reference recording — pulse count and
    gap lengths only. Never holds any physiological signal values, so it's safe to build from a
    real participant's file without that file's actual data reaching the synthetic output.
    """

    n_pulses: int
    sampling_freq_hz: float
    min_gap_seconds: float
    median_gap_seconds: float


def characterize_reference_trigger_pattern(reference_mat_path: Path) -> ReferenceTriggerProfile:
    """Measures pulse count/timing from a reference .mat file's trigger channel only."""
    mat_dict = sio.loadmat(reference_mat_path)
    trigger = mat_dict["data"][:, _trigger_channel_index(mat_dict)]
    sampling_freq_hz = _sampling_freq_hz(mat_dict)
    edges = _rising_edge_indices(trigger)

    if len(edges) < 2:
        raise ValueError(
            f"{reference_mat_path} has fewer than 2 trigger pulses — not enough to characterize."
        )

    gap_seconds = np.diff(edges) / sampling_freq_hz
    return ReferenceTriggerProfile(
        n_pulses=len(edges),
        sampling_freq_hz=sampling_freq_hz,
        min_gap_seconds=float(gap_seconds.min()),
        median_gap_seconds=float(np.median(gap_seconds)),
    )


def _mutate_physiology_dict(
    mat_dict: dict,
    rng: np.random.Generator,
    error_type: str | None,
    reference_gap_seconds: float | None = None,
) -> dict:
    mutated = {key: value for key, value in mat_dict.items() if not key.startswith("__")}
    data = mutated["data"].copy()
    trigger_idx = _trigger_channel_index(mutated)

    for channel_idx in range(data.shape[1]):
        if channel_idx == trigger_idx:
            continue
        channel = data[:, channel_idx]
        data[:, channel_idx] = channel + rng.normal(0, channel.std() * 0.02, size=channel.shape)

    sampling_freq_hz = _sampling_freq_hz(mutated)

    if error_type == "bad_trigger_count":
        data[:, trigger_idx] = _remove_one_trigger_pulse(data[:, trigger_idx], rng)
    elif error_type == "short_trigger":
        data[:, trigger_idx] = _insert_short_trigger_pulse(data[:, trigger_idx], rng, sampling_freq_hz)
    elif error_type == "missing_initial_trigger":
        data[:, trigger_idx] = _remove_first_trigger_pulse(data[:, trigger_idx])
    elif error_type == "missing_last_trigger":
        data[:, trigger_idx] = _remove_last_trigger_pulse(data[:, trigger_idx])
    elif error_type == "double_initial_trigger":
        if reference_gap_seconds is None:
            raise ValueError("double_initial_trigger requires reference_gap_seconds")
        data[:, trigger_idx] = _insert_double_initial_trigger_pulse(
            data[:, trigger_idx], sampling_freq_hz, reference_gap_seconds
        )

    mutated["data"] = data
    return mutated


def _isin_check_values(column: pa.Column) -> list | None:
    """The allowed-value list from a `Check.isin(...)` on this schema column, if it has one --
    lets _build_debrief_rows pull e.g. the likert scale's valid values straight from
    crane_raw_debrief_file_schema instead of duplicating them here by hand.
    """
    for check in column.checks:
        if check.name == "isin":
            return list(check.statistics["allowed_values"])
    return None


def _build_debrief_rows(subject_id: str, rng: np.random.Generator) -> pd.DataFrame:
    """One dummy debrief row, shaped by crane_raw_debrief_file_schema itself rather than a
    hand-maintained column list -- so a schema change (e.g. a new emotion added to
    EMOTIONS_TESTED) is picked up here automatically instead of silently producing a row
    missing a column that the schema's strict=True would later reject elsewhere. Only the
    three free-text columns the schema doesn't constrain the values of get a hardcoded
    plausible value below; every other column's allowed values come straight from its own
    Check.isin() (e.g. the likert-scale emotion ratings).
    """
    row: dict[str, str | int] = {
        "record_id": subject_id,
        "started": str(rng.choice(["1", "2"])),
        "height": str(rng.integers(150, 195)),
        "High_at_start_end": str(rng.choice(["High", "Low"])),
    }
    for column_name, column in crane_raw_debrief_file_schema.columns.items():
        if column_name in row:
            continue
        allowed_values = _isin_check_values(column)
        if allowed_values is None:
            raise ValueError(
                f"Don't know how to generate a dummy value for debrief column {column_name!r} "
                "-- add it to _build_debrief_rows."
            )
        row[column_name] = rng.choice(allowed_values)

    return crane_raw_debrief_file_schema.validate(pd.DataFrame([row]))


def generate_dummy_participant(
    csv_template: Path,
    mat_template: Path,
    subject_id: str,
    csv_date_string: str,
    mat_date_string: str,
    output_folder: Path,
    rng: np.random.Generator,
    error_type: str | None = None,
    reference_gap_seconds: float | None = None,
) -> tuple[DummyParticipantResult, pd.DataFrame]:
    csv_path = None
    mat_path = None
    debrief_rows = pd.DataFrame()

    if error_type != "missing_behaviour":
        behav_df = _mutate_behaviour_df(pd.read_csv(csv_template), rng)
        csv_path = output_folder / f"{csv_date_string}_{subject_id}_CraneOut.csv"
        behav_df.to_csv(csv_path, index=False)

    if error_type != "missing_physiology":
        mat_dict = _mutate_physiology_dict(
            sio.loadmat(mat_template), rng, error_type, reference_gap_seconds
        )
        mat_path = output_folder / f"{mat_date_string}_{subject_id}_CraneOut.mat"
        sio.savemat(mat_path, mat_dict)

    if error_type != "missing_debrief":
        debrief_rows = _build_debrief_rows(subject_id, rng)

    result = DummyParticipantResult(subject_id, error_type or CLEAN_SCENARIO_LABEL, csv_path, mat_path)
    return result, debrief_rows


def generate_dummy_debrief_workbook(debrief_rows: list[pd.DataFrame], output_folder: Path) -> Path:
    csv_path = output_folder / DUMMY_GROUP_DEBRIEF_FN
    combined = pd.concat(debrief_rows, ignore_index=True) if debrief_rows else pd.DataFrame()
    combined.to_csv(csv_path, index=False)
    return csv_path


def _dummy_data_log_line(result: DummyParticipantResult) -> str:
    description = SCENARIO_DESCRIPTIONS.get(result.scenario, result.scenario)
    behaviour = result.csv_path.name if result.csv_path else "(none)"
    physiology = result.mat_path.name if result.mat_path else "(none)"
    return (
        f"{result.subject_id} [{result.scenario}]: {description} "
        f"(behaviour={behaviour}, physiology={physiology})"
    )


def write_dummy_data_log(results: list[DummyParticipantResult], output_folder: Path) -> Path:
    """Writes output_folder/DUMMY_DATA_LOG_FILENAME, one line per participant explaining what
    their scenario is for -- e.g. that one participant has no physiology file *on purpose*,
    because it's exercising the missing-physiology error path, not a generation bug. Overwrites
    any previous log, same as generate_dummy_debrief_workbook overwrites the previous debrief
    export -- both reflect a fresh generate_dummy_dataset() run, not an accumulation across runs.
    """
    path = output_folder / DUMMY_DATA_LOG_FILENAME
    lines = [_dummy_data_log_line(result) for result in results]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def append_dummy_data_log_entry(result: DummyParticipantResult, output_folder: Path) -> Path:
    """Appends one line to output_folder/DUMMY_DATA_LOG_FILENAME for a single participant
    generated outside generate_dummy_dataset() (generate_dummy_participant_matching_reference)
    -- keeps whatever's already logged there, same as _append_debrief_rows_to_workbook keeps
    existing debrief rows rather than overwriting them.
    """
    path = output_folder / DUMMY_DATA_LOG_FILENAME
    with path.open("a", encoding="utf-8") as log_file:
        log_file.write(_dummy_data_log_line(result) + "\n")
    return path


def generate_dummy_dataset(
    template_folder: Path,
    output_folder: Path,
    n_clean: int,
    with_errors: bool,
    seed: int | None = None,
) -> list[DummyParticipantResult]:
    rng = np.random.default_rng(seed)
    template_pairs = discover_template_pairs(template_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    scenarios: list[str | None] = [None] * n_clean
    if with_errors:
        scenarios += list(ERROR_TYPES)

    results = []
    debrief_rows = []

    for index, error_type in enumerate(scenarios):
        csv_template, mat_template = template_pairs[index % len(template_pairs)]
        subject_id = f"DUMMY{index:03d}"
        csv_date_string = f"2026{100 + index}"
        mat_date_string = f"2026{900 + index}" if error_type == "date_mismatch" else csv_date_string

        logger.info("Generating dummy participant %s (%s)", subject_id, error_type or "clean")

        result, participant_debrief_rows = generate_dummy_participant(
            csv_template,
            mat_template,
            subject_id,
            csv_date_string,
            mat_date_string,
            output_folder,
            rng,
            error_type,
        )
        results.append(result)
        if not participant_debrief_rows.empty:
            debrief_rows.append(participant_debrief_rows)

    generate_dummy_debrief_workbook(debrief_rows, output_folder)
    write_dummy_data_log(results, output_folder)
    return results


def _append_debrief_rows_to_workbook(debrief_rows: pd.DataFrame, output_folder: Path) -> Path:
    """Merges debrief_rows into output_folder's debrief CSV, keeping rows already there."""
    csv_path = output_folder / DUMMY_GROUP_DEBRIEF_FN
    if csv_path.exists():
        existing_rows = pd.read_csv(csv_path)
        combined_rows = pd.concat([existing_rows, debrief_rows], ignore_index=True)
    else:
        combined_rows = debrief_rows
    combined_rows.to_csv(csv_path, index=False)
    return csv_path


def find_reference_mat_file(reference_folder: Path, reference_subject_id: str) -> Path:
    """Locates a participant's .mat file by ID under reference_folder, without reading it."""
    matches = sorted(reference_folder.rglob(f"*_{reference_subject_id}_*.mat"))
    if not matches:
        raise FileNotFoundError(
            f"No .mat file found for participant {reference_subject_id!r} under {reference_folder}"
        )
    return matches[0]


def generate_dummy_participant_matching_reference(
    template_folder: Path,
    output_folder: Path,
    reference_folder: Path,
    reference_subject_id: str,
    reference_error_type: str,
    subject_id: str | None = None,
    seed: int | None = None,
) -> DummyParticipantResult:
    """
    Generates one synthetic participant whose trigger-channel anomaly is shaped after a real
    reference recording (e.g. one of the trigger-anomaly cases in
    tests/test_crane_pipeline.py's TestCraneGetIntervalStrategy), without copying any of that
    recording's actual signal values.

    reference_folder may point at a real, gitignored crane_data/ folder — only
    characterize_reference_trigger_pattern() reads from it, and only for trigger-pulse timing.
    Meant to be run locally against real data yourself; the output written to output_folder is
    built entirely from template_folder's synthetic templates.
    """
    if reference_error_type not in REFERENCE_ERROR_TYPES:
        raise ValueError(
            f"reference_error_type must be one of {REFERENCE_ERROR_TYPES}, "
            f"got {reference_error_type!r}"
        )

    rng = np.random.default_rng(seed)
    csv_template, mat_template = discover_template_pairs(template_folder)[0]
    reference_mat_path = find_reference_mat_file(reference_folder, reference_subject_id)
    reference_profile = characterize_reference_trigger_pattern(reference_mat_path)
    output_folder.mkdir(parents=True, exist_ok=True)

    subject_id = subject_id or f"REF{reference_subject_id}"
    date_string = "2026999"
    reference_gap_seconds = max(reference_profile.min_gap_seconds, MIN_DOUBLE_TRIGGER_GAP_SECONDS)

    logger.info(
        "Generating %s as %s, matching reference participant %s",
        subject_id,
        reference_error_type,
        reference_subject_id,
    )

    result, debrief_rows = generate_dummy_participant(
        csv_template,
        mat_template,
        subject_id,
        date_string,
        date_string,
        output_folder,
        rng,
        error_type=reference_error_type,
        reference_gap_seconds=reference_gap_seconds,
    )
    if not debrief_rows.empty:
        _append_debrief_rows_to_workbook(debrief_rows, output_folder)
    append_dummy_data_log_entry(result, output_folder)
    return result
