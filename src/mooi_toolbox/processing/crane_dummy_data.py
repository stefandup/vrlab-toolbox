import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.io as sio

from mooi_toolbox.processing.biopac import clean_biopac_labels
from mooi_toolbox.processing.crane_behaviour import (
    EMOTIONS_TESTED,
    build_crane_raw_behav_file_schema,
)
from mooi_toolbox.processing.crane_debrief_behaviour import REDCAP_FN, emotion_cols

logger = logging.getLogger(__name__)

ERROR_TYPES = (
    "missing_physiology",
    "missing_behaviour",
    "missing_debrief",
    "date_mismatch",
    "bad_trigger_count",
    "short_trigger",
)

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


def _remove_one_trigger_pulse(trigger: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Flattens one whole trigger pulse to baseline, dropping one rising edge."""
    mutated = trigger.copy()
    edges = _rising_edge_indices(mutated)
    interior_edges = edges[(edges > len(mutated) * 0.1) & (edges < len(mutated) * 0.9)]
    chosen = int(rng.choice(interior_edges))
    baseline = mutated[chosen - 1]
    high_value = mutated[chosen]

    end = chosen
    while end < len(mutated) - 1 and abs(mutated[end] - high_value) < 0.47:
        end += 1

    mutated[chosen:end] = baseline
    return mutated


def _insert_short_trigger_pulse(
    trigger: np.ndarray, rng: np.random.Generator, sampling_freq_hz: float
) -> np.ndarray:
    """
    Adds a brief extra pulse shortly after a real one, producing an anomalously short interval.
    """
    mutated = trigger.copy()
    edges = _rising_edge_indices(mutated)
    interior_edges = edges[(edges > len(mutated) * 0.1) & (edges < len(mutated) * 0.8)]
    chosen = int(rng.choice(interior_edges))
    high_value = mutated[chosen]

    gap_samples = int(TRIGGER_PULSE_GAP_SECONDS * sampling_freq_hz)
    burst_samples = max(int(0.1 * sampling_freq_hz), 1)
    insert_start = chosen + gap_samples
    insert_end = min(insert_start + burst_samples, len(mutated))

    mutated[insert_start:insert_end] = high_value
    return mutated


def _mutate_physiology_dict(
    mat_dict: dict, rng: np.random.Generator, error_type: str | None
) -> dict:
    mutated = {key: value for key, value in mat_dict.items() if not key.startswith("__")}
    data = mutated["data"].copy()
    trigger_idx = _trigger_channel_index(mutated)

    for channel_idx in range(data.shape[1]):
        if channel_idx == trigger_idx:
            continue
        channel = data[:, channel_idx]
        data[:, channel_idx] = channel + rng.normal(0, channel.std() * 0.02, size=channel.shape)

    if error_type == "bad_trigger_count":
        data[:, trigger_idx] = _remove_one_trigger_pulse(data[:, trigger_idx], rng)
    elif error_type == "short_trigger":
        data[:, trigger_idx] = _insert_short_trigger_pulse(
            data[:, trigger_idx], rng, _sampling_freq_hz(mutated)
        )

    mutated["data"] = data
    return mutated


def _build_debrief_rows(subject_id: str, rng: np.random.Generator) -> pd.DataFrame:
    rows: list[dict[str, str | int]] = [
        {
            "Subject_ID": subject_id,
            "Subject_Names": f"Dummy Participant {subject_id}",
            "started_with_Crane_MobiLab": str(rng.choice(["Yes", "No"])),
            "High_at_start_end": str(rng.choice(["High", "Low"])),
            "BARREL": barrel,
            **{emotion: int(rng.integers(1, 6)) for emotion in emotion_cols},
        }
        for barrel in ("GREEN", "RED")
    ]
    return pd.DataFrame(rows)


def generate_dummy_participant(
    csv_template: Path,
    mat_template: Path,
    subject_id: str,
    csv_date_string: str,
    mat_date_string: str,
    output_folder: Path,
    rng: np.random.Generator,
    error_type: str | None = None,
) -> tuple[DummyParticipantResult, pd.DataFrame]:
    csv_path = None
    mat_path = None
    debrief_rows = pd.DataFrame()

    if error_type != "missing_behaviour":
        behav_df = _mutate_behaviour_df(pd.read_csv(csv_template), rng)
        csv_path = output_folder / f"{csv_date_string}_{subject_id}_CraneOut.csv"
        behav_df.to_csv(csv_path, index=False)

    if error_type != "missing_physiology":
        mat_dict = _mutate_physiology_dict(sio.loadmat(mat_template), rng, error_type)
        mat_path = output_folder / f"{mat_date_string}_{subject_id}_CraneOut.mat"
        sio.savemat(mat_path, mat_dict)

    if error_type != "missing_debrief":
        debrief_rows = _build_debrief_rows(subject_id, rng)

    result = DummyParticipantResult(subject_id, error_type or "clean", csv_path, mat_path)
    return result, debrief_rows


def generate_dummy_debrief_workbook(debrief_rows: list[pd.DataFrame], output_folder: Path) -> Path:
    workbook_path = output_folder / REDCAP_FN
    combined = pd.concat(debrief_rows, ignore_index=True) if debrief_rows else pd.DataFrame()
    combined.to_excel(workbook_path, index=False, engine="openpyxl")
    return workbook_path


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
    return results
