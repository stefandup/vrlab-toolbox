import logging
from dataclasses import dataclass
from pathlib import Path

import neurokit2 as nk
import numpy as np
import scipy.io as sio

from vrlab_toolbox.processing.longwalk_behaviour import LONGWALK_EVENTS_LABELS

logger = logging.getLogger(__name__)

# One rising edge per green-marker trial boundary, so N trial intervals need N+1 pulses (matches
# longwalk_pipeline.EXPECTED_INTERVAL_NR=12 for the 11 entries in LONGWALK_EVENTS_LABELS).
N_TRIGGER_PULSES = len(LONGWALK_EVENTS_LABELS) + 1
TOTAL_DURATION_SECONDS = 600.0
SAMPLING_FREQ_HZ = 2000.0
# Keeps the first/last pulse off the very start/end of the recording.
PULSE_MARGIN_SECONDS = 5.0
TRIGGER_BASELINE_VOLTS = 0.15
TRIGGER_HIGH_VOLTS = 4.8
TRIGGER_PULSE_DURATION_SECONDS = 0.1

# Mirrors the label/unit spelling found in a real Biopac export (e.g.
# crane_examples/crane_templates) so clean_biopac_labels() strips them down to "Trigger"/"EDA"
# the same way it does for real data.
CHANNEL_LABELS = ("Trigger", "EDA - EDA100C")
CHANNEL_UNITS = ("Volts", "microsiemens")


@dataclass
class DummyLongWalkParticipantResult:
    subject_id: str
    mat_path: Path


def _trigger_pulse_times(
    total_duration_seconds: float, n_pulses: int, margin_seconds: float
) -> np.ndarray:
    return np.linspace(margin_seconds, total_duration_seconds - margin_seconds, n_pulses)


def _build_trigger_channel(
    n_samples: int, sampling_freq_hz: float, pulse_times: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    trigger = TRIGGER_BASELINE_VOLTS + rng.normal(0, 0.01, size=n_samples)
    pulse_samples = int(round(TRIGGER_PULSE_DURATION_SECONDS * sampling_freq_hz))

    for pulse_time in pulse_times:
        start = int(round(pulse_time * sampling_freq_hz))
        end = min(start + pulse_samples, n_samples)
        trigger[start:end] = TRIGGER_HIGH_VOLTS

    return trigger


def _build_eda_channel(
    n_samples: int, sampling_freq_hz: float, n_events: int, rng: np.random.Generator
) -> np.ndarray:
    # nk.eda_simulate does integer-only arithmetic (e.g. np.linspace(..., num=sampling_rate))
    # internally, so a float sampling_rate like SAMPLING_FREQ_HZ raises a TypeError.
    return nk.eda_simulate(
        length=n_samples,
        sampling_rate=int(sampling_freq_hz),
        scr_number=n_events,
        noise=0.01,
        drift=-0.01,
        random_state=rng,
    )


def generate_dummy_longwalk_participant(
    subject_id: str,
    date_string: str,
    output_folder: Path,
    rng: np.random.Generator,
) -> DummyLongWalkParticipantResult:
    """Writes a raw {subject_id}_{date}.mat Biopac file -- the input longwalk_bids.py's
    convert_longwalk_to_bids() expects, not the BIDS layout the pipeline reads.
    """
    n_samples = int(round(TOTAL_DURATION_SECONDS * SAMPLING_FREQ_HZ))
    pulse_times = _trigger_pulse_times(
        TOTAL_DURATION_SECONDS, N_TRIGGER_PULSES, PULSE_MARGIN_SECONDS
    )

    trigger = _build_trigger_channel(n_samples, SAMPLING_FREQ_HZ, pulse_times, rng)
    eda = _build_eda_channel(n_samples, SAMPLING_FREQ_HZ, len(LONGWALK_EVENTS_LABELS), rng)

    mat_dict = {
        "data": np.column_stack([trigger, eda]),
        "labels": np.array(CHANNEL_LABELS),
        "units": np.array(CHANNEL_UNITS),
        "isi": np.array([[1000.0 / SAMPLING_FREQ_HZ]]),
        "isi_units": np.array(["ms"]),
        "start_sample": np.array([[0]], dtype=np.uint8),
    }

    mat_path = output_folder / f"{subject_id}_{date_string}.mat"
    sio.savemat(mat_path, mat_dict)

    return DummyLongWalkParticipantResult(subject_id, mat_path)


def generate_dummy_longwalk_dataset(
    output_folder: Path,
    n_subjects: int,
    seed: int | None = None,
) -> list[DummyLongWalkParticipantResult]:
    rng = np.random.default_rng(seed)
    output_folder.mkdir(parents=True, exist_ok=True)

    results = []
    for index in range(n_subjects):
        subject_id = f"DUMMY{index:03d}"
        date_string = f"2026{100 + index}"
        logger.info("Generating dummy longwalk participant %s", subject_id)
        results.append(
            generate_dummy_longwalk_participant(subject_id, date_string, output_folder, rng)
        )

    return results
