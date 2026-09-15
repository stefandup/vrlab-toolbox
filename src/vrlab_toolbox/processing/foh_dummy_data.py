"""Synthetic FOH LSL recording generator -- the FOH counterpart to crane_dummy_data.py and
longwalk_dummy_data.py.

Unlike crane (clone a real template .mat/.csv and perturb it), FOH's raw recording is a
single multi-stream .xdf file -- a binary format `pyxdf` can read but not write. So this
module builds recordings from scratch (like longwalk_dummy_data.py), via a small, private
XDF encoder (write_xdf below) covering just enough of the format for `pyxdf.load_xdf` to
read it back correctly: a FileHeader chunk, one StreamHeader/Samples/StreamFooter chunk
triplet per stream, no ClockOffset or Boundary chunks (unneeded for a single-clock synthetic
recording -- see pyxdf.pyxdf.load_xdf for the full chunk grammar this mirrors).

The four streams, their column names, the VR_trial event vocabulary, and the FOH_target CSV
row shape are all modelled on a real, de-identified example recording
(foh_examples/foh_templates/raw_lsl_data/sub-nomfusi3/...) that a human inspected and cleared
for this purpose -- see processing/foh_behaviour.py, foh_target_behaviour.py, foh_config.py
and lsl.py for the pipeline code that consumes them. Session durations are compressed well
below the real recording's (which ran ~15 minutes) purely to keep generated files small and
generation fast; the event *sequence* and *ratios* between baseline/stress/recovery follow the
reference recording.
"""

import logging
import struct
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

import neurokit2 as nk
import numpy as np

from vrlab_toolbox.processing.foh_config import TRIAL_NUMBERS

logger = logging.getLogger(__name__)

# --- Session timing, modelled on the reference recording -------------------------------
# LSL clocks are uptime-based, not zero-based -- real recordings start in the low hundreds
# of seconds. Every timestamp below is offset by this so it comfortably clears the ">= 1"
# check every raw-behaviour schema in this pipeline applies to "time_stamps".
CLOCK_OFFSET_SECONDS = 250.0
BASELINE_DURATION_SECONDS = 60.0
# Gap between "RaiseSafetyPlatform" (baseline end) and "RaiseMainPlatform" (stress start) --
# SafetyPlatformReachedMax fires in between, exactly as in the reference recording.
BASELINE_TO_STRESS_GAP_SECONDS = 10.0
STRESS_DURATION_SECONDS = 80.0
RECOVERY_DURATION_SECONDS = 20.0
# Gap between "RunFOHQuestions" (recovery end) and the final (empty) VR_trial_events sample.
END_MARGIN_SECONDS = 15.0
# OpenSignals starts recording before, and keeps recording briefly after, the VR markers --
# matches the reference recording having a wider physiology span than its VR event span.
PHYSIO_LEAD_SECONDS = 20.0
PHYSIO_TRAIL_SECONDS = 8.0

OPENSIGNALS_SAMPLING_FREQ_HZ = 250.0
OPENSIGNALS_CHANNEL_LABELS = ("nSeq", "EDA0", "ECG1")
# TRIAL_NUMBERS/TARGET_TYPES/TRIAL_TYPES come from foh_config.py -- imported below rather than
# hardcoded again here, so a config change is picked up automatically.

CLEAN_SCENARIO_LABEL = "clean"
ERROR_TYPES = (
    "missing_physiology",
    "missing_behaviour",
    "missing_target",
    "missing_baseline_start_marker",
    "srate_mismatch",
    "incomplete_target_trials",
)
SCENARIO_DESCRIPTIONS: dict[str, str] = {
    CLEAN_SCENARIO_LABEL: (
        "Well-formed recording -- OpenSignals physiology, VR markers/trial events and FOH "
        "target data all present. Exercises the ordinary happy-path pipeline run."
    ),
    "missing_physiology": (
        "No OpenSignals stream in the .xdf -- exercises handling of a recording with no "
        "physiology data (e.g. the BITalino device was never connected)."
    ),
    "missing_behaviour": (
        "No VR_trial_events stream in the .xdf -- exercises handling of a recording with no "
        "VR trial-state markers (ImportFohBehaviourDataStrategyStep raises on this)."
    ),
    "missing_target": (
        "No FOH_target stream in the .xdf -- exercises handling of a recording where the "
        "target-hitting task's own data never reached LSL."
    ),
    "missing_baseline_start_marker": (
        "The VR_markers stream is present but missing its baseline-start (event 10) sample -- "
        "exercises FOH_TRIAL_INTERVALS's fallback path (BASELINE_START_FALLBACK_SPEC), which "
        "derives the baseline start from RaiseSafetyPlatform - 300s instead. This one should "
        "still succeed, not error."
    ),
    "srate_mismatch": (
        "OpenSignals declares a nominal sampling rate that doesn't match its samples' actual "
        "timing (off by more than 10%) -- exercises the FOH crosscheck GUI's sampling-rate "
        "mismatch warning (see gui/foh_bids_crosscheck_gui.py's _srate_mismatch); the pipeline "
        "itself doesn't check this, only the crosscheck tool does."
    ),
    "incomplete_target_trials": (
        "Fewer FOH_target trial groups than foh_config.TRIAL_NUMBERS expects (2 baseline, 2 "
        "stress, 1 recovery instead of 3 each) -- modelled on the reference recording, which "
        "itself only had that many completed groups. Exercises the target-behaviour pipeline "
        "producing a wide row with some *_Target columns missing rather than failing outright."
    ),
}
DUMMY_DATA_LOG_FILENAME = "dummy_data_log.txt"


@dataclass
class DummyFohParticipantResult:
    subject_id: str
    scenario: str
    xdf_path: Path


# --- Minimal XDF writer -----------------------------------------------------------------
# Just enough of https://github.com/sccn/xdf/wiki/Specifications for pyxdf.load_xdf to read
# back what we write: FileHeader, StreamHeader/Samples/StreamFooter per stream. Every sample
# carries an explicit 8-byte timestamp (no delta-compression) -- simpler to write correctly,
# and the files here are small enough that it doesn't matter.

_XDF_MAGIC = b"XDF:"
_TAG_FILE_HEADER = 1
_TAG_STREAM_HEADER = 2
_TAG_SAMPLES = 3
_TAG_STREAM_FOOTER = 6
_TIMESTAMP_PRESENT_MARKER = b"\x08"

_NUMERIC_DTYPES = {
    "float32": "<f4",
    "double64": "<f8",
}


@dataclass
class XdfStreamSpec:
    name: str
    type: str
    channel_format: str
    nominal_srate: float
    channel_labels: tuple[str, ...]
    time_stamps: np.ndarray
    # 2D array [n_samples, n_channels] for a numeric channel_format, or a list of
    # [n_channels]-length string rows for channel_format == "string".
    time_series: np.ndarray | list[list[str]]


def _write_varlen_int(value: int) -> bytes:
    # Always the 4-byte-length form -- simpler than picking the smallest encoding, and well
    # within what pyxdf._read_varlen_int accepts (it also supports 1- and 8-byte forms).
    return struct.pack("<BI", 4, value)


def _write_chunk(file_obj, tag: int, stream_id: int | None, payload: bytes) -> None:
    body = struct.pack("<H", tag)
    if stream_id is not None:
        body += struct.pack("<I", stream_id)
    body += payload
    file_obj.write(_write_varlen_int(len(body)))
    file_obj.write(body)


def _stream_header_xml(stream: XdfStreamSpec) -> bytes:
    channel_tags = "".join(
        f"<channel><label>{escape(label)}</label></channel>" for label in stream.channel_labels
    )
    xml = (
        '<?xml version="1.0"?><info>'
        f"<name>{escape(stream.name)}</name><type>{escape(stream.type)}</type>"
        f"<channel_count>{len(stream.channel_labels)}</channel_count>"
        f"<channel_format>{stream.channel_format}</channel_format>"
        f"<nominal_srate>{stream.nominal_srate!r}</nominal_srate>"
        f"<desc><channels>{channel_tags}</channels></desc>"
        "</info>"
    )
    return xml.encode("utf-8")


def _file_header_xml() -> bytes:
    return b'<?xml version="1.0"?><info><version>1.0</version></info>'


def _stream_footer_xml(n_samples: int) -> bytes:
    return f'<?xml version="1.0"?><info><sample_count>{n_samples}</sample_count></info>'.encode()


def _encode_numeric_samples(stream: XdfStreamSpec) -> bytes:
    """Vectorized encoding via a structured array -- OpenSignals streams run to tens of
    thousands of samples, too many for a per-sample Python loop to build quickly."""
    n_samples = len(stream.time_stamps)
    n_channels = len(stream.channel_labels)
    dtype = np.dtype(
        [
            ("marker", "u1"),
            ("timestamp", "<f8"),
            ("values", _NUMERIC_DTYPES[stream.channel_format], (n_channels,)),
        ]
    )
    encoded = np.empty(n_samples, dtype=dtype)
    encoded["marker"] = _TIMESTAMP_PRESENT_MARKER[0]
    encoded["timestamp"] = stream.time_stamps
    encoded["values"] = stream.time_series
    return encoded.tobytes()


def _encode_string_samples(stream: XdfStreamSpec) -> bytes:
    parts = []
    for timestamp, row in zip(stream.time_stamps, stream.time_series, strict=True):
        parts.append(_TIMESTAMP_PRESENT_MARKER)
        parts.append(struct.pack("<d", float(timestamp)))
        for value in row:
            encoded_value = str(value).encode("utf-8")
            parts.append(_write_varlen_int(len(encoded_value)))
            parts.append(encoded_value)
    return b"".join(parts)


def write_xdf(path: Path, streams: list[XdfStreamSpec]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file_obj:
        file_obj.write(_XDF_MAGIC)
        _write_chunk(file_obj, _TAG_FILE_HEADER, None, _file_header_xml())

        for stream_id, stream in enumerate(streams, start=1):
            _write_chunk(file_obj, _TAG_STREAM_HEADER, stream_id, _stream_header_xml(stream))

            n_samples = len(stream.time_stamps)
            if stream.channel_format == "string":
                samples_payload = _encode_string_samples(stream)
            else:
                samples_payload = _encode_numeric_samples(stream)
            samples_content = _write_varlen_int(n_samples) + samples_payload
            _write_chunk(file_obj, _TAG_SAMPLES, stream_id, samples_content)

            _write_chunk(file_obj, _TAG_STREAM_FOOTER, stream_id, _stream_footer_xml(n_samples))


# --- Session/stream construction ---------------------------------------------------------


@dataclass
class _SessionTimeline:
    baseline_start: float
    baseline_end: float
    stress_start: float
    stress_end: float
    recovery_start: float
    recovery_end: float
    final_marker_time: float


def _build_timeline() -> _SessionTimeline:
    baseline_start = CLOCK_OFFSET_SECONDS
    baseline_end = baseline_start + BASELINE_DURATION_SECONDS
    stress_start = baseline_end + BASELINE_TO_STRESS_GAP_SECONDS
    stress_end = stress_start + STRESS_DURATION_SECONDS
    recovery_start = stress_end
    recovery_end = recovery_start + RECOVERY_DURATION_SECONDS
    final_marker_time = recovery_end + END_MARGIN_SECONDS
    return _SessionTimeline(
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        stress_start=stress_start,
        stress_end=stress_end,
        recovery_start=recovery_start,
        recovery_end=recovery_end,
        final_marker_time=final_marker_time,
    )


def _build_vr_markers_stream(
    timeline: _SessionTimeline, include_baseline_start: bool
) -> XdfStreamSpec:
    """Markers stream: event 10 = baseline start, 11/0 = end-of-session bookkeeping -- see
    foh_config.BASELINE_START_SPEC. `include_baseline_start=False` drops event 10, reproducing
    the "missing_baseline_start_marker" scenario.
    """
    time_stamps = []
    values = []
    if include_baseline_start:
        time_stamps.append(timeline.baseline_start)
        values.append(10.0)
    time_stamps.append(timeline.final_marker_time - 0.5)
    values.append(11.0)
    time_stamps.append(timeline.final_marker_time + 0.2)
    values.append(0.0)

    return XdfStreamSpec(
        name="VR_markers",
        type="Markers",
        channel_format="float32",
        nominal_srate=0.0,
        channel_labels=("Markers",),
        time_stamps=np.array(time_stamps, dtype=float),
        time_series=np.array(values, dtype=np.float32).reshape(-1, 1),
    )


def _build_vr_trial_events_stream(timeline: _SessionTimeline) -> XdfStreamSpec:
    """VR_trial event sequence, in the same order (and using the same vocabulary, from
    build_foh_raw_behav_schema's isin check) as the reference recording."""
    events = [
        (timeline.baseline_start + 0.5, "DoSTDQuestions"),
        (timeline.baseline_start + BASELINE_DURATION_SECONDS * 2 / 3, "DoSTDQuestions"),
        (timeline.baseline_end, "RaiseSafetyPlatform"),
        (timeline.stress_start, "SafetyPlatformReachedMax"),
        (timeline.stress_start, "RaiseMainPlatform"),
        (timeline.stress_start + 5.0, "MainPlatformAtMax"),
        (timeline.stress_start + 5.0, "DoSTDQuestions"),
        (timeline.stress_start + STRESS_DURATION_SECONDS * 3 / 4, "DoSTDQuestions"),
        (timeline.stress_end - 10.0, "MainPlatformLowering"),
        (timeline.stress_end, "MainPlatformAtMin"),
        (timeline.recovery_start + 5.0, "SafetyPlatformAtMin"),
        (timeline.recovery_end - 5.0, "DoSTDQuestions"),
        (timeline.recovery_end, "RunFOHQuestions"),
        (timeline.final_marker_time, ""),
    ]
    time_stamps, values = zip(*events, strict=True)

    return XdfStreamSpec(
        name="VR_trial_events",
        type="StringData",
        channel_format="string",
        nominal_srate=0.0,
        channel_labels=("VR_trial",),
        time_stamps=np.array(time_stamps, dtype=float),
        time_series=[[value] for value in values],
    )


def _build_opensignals_stream(
    timeline: _SessionTimeline,
    rng: np.random.Generator,
    actual_sampling_freq_hz: float | None = None,
) -> XdfStreamSpec:
    """OpenSignals: nSeq (rolling 0-15 counter), EDA0, ECG1 -- matches the reference
    recording's column labels, which biodata.normalize_data_labels then canonicalizes to
    nSeq/EDA/ECG. `actual_sampling_freq_hz`, if different from OPENSIGNALS_SAMPLING_FREQ_HZ,
    spaces the *actual* sample timestamps at that rate while the stream still *declares*
    OPENSIGNALS_SAMPLING_FREQ_HZ as nominal -- reproducing the "srate_mismatch" scenario.
    """
    start = timeline.baseline_start - PHYSIO_LEAD_SECONDS
    end = timeline.final_marker_time + PHYSIO_TRAIL_SECONDS
    real_srate = actual_sampling_freq_hz or OPENSIGNALS_SAMPLING_FREQ_HZ
    n_samples = int(round((end - start) * real_srate))

    time_stamps = start + np.arange(n_samples) / real_srate
    n_seq = (np.arange(n_samples) % 16).astype(float)
    eda = nk.eda_simulate(
        length=n_samples,
        sampling_rate=int(round(OPENSIGNALS_SAMPLING_FREQ_HZ)),
        scr_number=6,
        noise=0.01,
        drift=-0.01,
        random_state=rng,
    )
    ecg = nk.ecg_simulate(
        duration=n_samples / OPENSIGNALS_SAMPLING_FREQ_HZ,
        sampling_rate=int(round(OPENSIGNALS_SAMPLING_FREQ_HZ)),
        noise=0.01,
        random_state=rng,
    )
    # ecg_simulate's ecgsyn method doesn't always return exactly `duration * sampling_rate`
    # samples -- pad/trim to match eda/n_seq exactly.
    if len(ecg) < n_samples:
        ecg = np.pad(ecg, (0, n_samples - len(ecg)), mode="edge")
    else:
        ecg = ecg[:n_samples]
    time_series = np.column_stack([n_seq, eda, ecg])

    return XdfStreamSpec(
        name="OpenSignals",
        type="OpenSignals",
        channel_format="double64",
        nominal_srate=OPENSIGNALS_SAMPLING_FREQ_HZ,
        channel_labels=OPENSIGNALS_CHANNEL_LABELS,
        time_stamps=time_stamps,
        time_series=time_series,
    )


# Per-TargetType hit-latency ranges (seconds), modelled on the reference recording's own
# FOH_target rows (Short fastest, Long slowest).
_TARGET_LATENCY_RANGES_SECONDS = {"Short": (1.0, 1.4), "Medium": (1.4, 2.6), "Long": (1.8, 3.0)}
_TARGET_GROUP_OFFSETS_SECONDS = (0.0, 2.0, 4.5)  # Short, Medium, Long, within one trial group


def _target_group_times(interval_start: float, interval_end: float, n_groups: int) -> list[float]:
    """n_groups evenly spaced group-start times within [interval_start, interval_end], each
    leaving enough room for _TARGET_GROUP_OFFSETS_SECONDS's rows to land inside the interval."""
    margin = _TARGET_GROUP_OFFSETS_SECONDS[-1] + 1.0
    usable_end = interval_end - margin
    if n_groups == 1:
        return [interval_start + (usable_end - interval_start) / 2]
    return list(np.linspace(interval_start, usable_end, n_groups))


def _build_foh_target_stream(
    timeline: _SessionTimeline, rng: np.random.Generator, trial_numbers: dict[str, int]
) -> XdfStreamSpec:
    """FOH_target: a CSV-header row followed by data rows, all carried as single-column
    string samples -- exactly the shape ImportFohTargetBehaviourDataStrategyStep expects
    (see foh_target_behaviour.py). `trial_numbers` lets "incomplete_target_trials" ask for
    fewer groups per condition than foh_config.TRIAL_NUMBERS.
    """
    intervals = {
        "baseline": (timeline.baseline_start, timeline.baseline_end),
        "stress": (timeline.stress_start, timeline.stress_end),
        "recovery": (timeline.recovery_start, timeline.recovery_end),
    }

    time_stamps = [timeline.baseline_start - PHYSIO_LEAD_SECONDS / 2]
    rows = ["TimeSpawned,TimeHit,HitLatency,TargetType"]
    task_clock = 50.0

    target_types = ("Short", "Medium", "Long")
    for trial_type, (interval_start, interval_end) in intervals.items():
        group_times = _target_group_times(interval_start, interval_end, trial_numbers[trial_type])
        for group_time in group_times:
            offsets_and_types = zip(_TARGET_GROUP_OFFSETS_SECONDS, target_types, strict=True)
            for offset, target_type in offsets_and_types:
                sample_time = group_time + offset
                low, high = _TARGET_LATENCY_RANGES_SECONDS[target_type]
                latency = rng.uniform(low, high)
                time_spawned = task_clock
                time_hit = time_spawned + latency
                task_clock += latency + rng.uniform(0.5, 2.0)

                time_stamps.append(sample_time)
                rows.append(f"{time_spawned:.6f},{time_hit:.6f},{latency:.6f},{target_type}")

    return XdfStreamSpec(
        name="FOH_target",
        type="String",
        channel_format="string",
        nominal_srate=0.0,
        channel_labels=("FOH_target",),
        time_stamps=np.array(time_stamps, dtype=float),
        time_series=[[row] for row in rows],
    )


def generate_dummy_foh_participant(
    output_folder: Path,
    subject_id: str,
    rng: np.random.Generator,
    error_type: str | None = None,
) -> DummyFohParticipantResult:
    """Writes one synthetic FOH recording as
    output_folder/sub-{subject_id}/ses-S001/beh/sub-{subject_id}_ses-S001_task-foh_run-001_beh.xdf
    -- the already-crosschecked BIDS naming ParticipantConfig.from_lsl_data's glob
    (`sub-{id}*task-foh*_beh.xdf`) and mobi_FOH_process_batch's `*.xdf` scan both expect, since
    FOH's recording software writes this shape directly (see cli/foh_import_to_bids.py).
    """
    if error_type is not None and error_type not in ERROR_TYPES:
        raise ValueError(f"error_type must be one of {ERROR_TYPES}, got {error_type!r}")

    timeline = _build_timeline()
    trial_numbers = dict(TRIAL_NUMBERS)
    if error_type == "incomplete_target_trials":
        trial_numbers = {"baseline": 2, "stress": 2, "recovery": 1}

    streams = []
    if error_type != "missing_physiology":
        actual_srate = (
            OPENSIGNALS_SAMPLING_FREQ_HZ * 0.85 if error_type == "srate_mismatch" else None
        )
        streams.append(_build_opensignals_stream(timeline, rng, actual_srate))
    include_baseline_start = error_type != "missing_baseline_start_marker"
    streams.append(_build_vr_markers_stream(timeline, include_baseline_start))
    if error_type != "missing_behaviour":
        streams.append(_build_vr_trial_events_stream(timeline))
    if error_type != "missing_target":
        streams.append(_build_foh_target_stream(timeline, rng, trial_numbers))

    subject_folder = output_folder / f"sub-{subject_id}" / "ses-S001" / "beh"
    xdf_path = subject_folder / f"sub-{subject_id}_ses-S001_task-foh_run-001_beh.xdf"
    write_xdf(xdf_path, streams)

    return DummyFohParticipantResult(
        subject_id=subject_id, scenario=error_type or CLEAN_SCENARIO_LABEL, xdf_path=xdf_path
    )


def _dummy_data_log_line(result: DummyFohParticipantResult) -> str:
    description = SCENARIO_DESCRIPTIONS.get(result.scenario, result.scenario)
    return (
        f"{result.subject_id} [{result.scenario}]: {description} (recording={result.xdf_path.name})"
    )


def write_dummy_data_log(results: list[DummyFohParticipantResult], output_folder: Path) -> Path:
    path = output_folder / DUMMY_DATA_LOG_FILENAME
    lines = [_dummy_data_log_line(result) for result in results]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def generate_dummy_foh_dataset(
    output_folder: Path,
    n_clean: int,
    with_errors: bool,
    seed: int | None = None,
) -> list[DummyFohParticipantResult]:
    rng = np.random.default_rng(seed)
    output_folder.mkdir(parents=True, exist_ok=True)

    scenarios: list[str | None] = [None] * n_clean
    if with_errors:
        scenarios += list(ERROR_TYPES)

    results = []
    for index, error_type in enumerate(scenarios):
        subject_id = f"DUMMY{index:03d}"
        logger.info("Generating dummy FOH participant %s (%s)", subject_id, error_type or "clean")
        results.append(generate_dummy_foh_participant(output_folder, subject_id, rng, error_type))

    write_dummy_data_log(results, output_folder)
    return results
