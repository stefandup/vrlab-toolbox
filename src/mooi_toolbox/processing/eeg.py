from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, sosfiltfilt, welch

from mooi_toolbox.processing.graphomotor_xdf import XdfStream


class EEGProcessingError(ValueError):
    """Raised when EEG processing fails."""


BAD_CHANNELS = [
    "TRG",
    "ACCT",
    "ACCX",
    "ACCY",
    "ACCZ",
    "X1",
    "X2",
    "X3",
    "A2",
    "Cz",
]


def get_effective_srate(stream: XdfStream) -> float:
    time_stamps = np.asarray(stream.get("time_stamps", []), dtype=float)

    if len(time_stamps) < 2:
        return 0.0

    duration = time_stamps[-1] - time_stamps[0]
    if duration <= 0:
        return 0.0

    return float(len(time_stamps) / duration)


def get_channel_names(stream: XdfStream, n_channels: int) -> list[str]:
    try:
        channels = stream["info"]["desc"][0]["channels"][0]["channel"]
        names = [channel["label"][0] for channel in channels]
    except (KeyError, TypeError, IndexError):
        return [f"Ch {i + 1}" for i in range(n_channels)]

    if len(names) == n_channels:
        return names

    return [f"Ch {i + 1}" for i in range(n_channels)]


def safe_float_array(values) -> np.ndarray:
    output = []

    for value in values:
        try:
            output.append(float(value))
        except (TypeError, ValueError):
            output.append(np.nan)

    return np.asarray(output, dtype=float)


def clean_eeg(data: np.ndarray, sampling_rate: float) -> np.ndarray:
    data = np.asarray(data, dtype=float).copy()
    data = data - np.nanmean(data, axis=0)

    b_notch, a_notch = iirnotch(w0=50, Q=30, fs=sampling_rate)
    data = filtfilt(b_notch, a_notch, data, axis=0)

    sos = butter(
        4,
        [1, 40],
        btype="bandpass",
        fs=sampling_rate,
        output="sos",
    )
    return sosfiltfilt(sos, data, axis=0)


def get_interval_signal(
    signal: np.ndarray,
    time_sec: np.ndarray,
    intervals: list[tuple[float, float]],
) -> np.ndarray:
    pieces = []

    for start, end in intervals:
        mask = (time_sec >= start) & (time_sec <= end)
        pieces.append(signal[mask])

    if not pieces:
        return np.asarray([])

    return np.concatenate(pieces)


def bandpower_welch(
    signal: np.ndarray,
    sampling_rate: float,
    band: tuple[int, int],
) -> float:
    signal = np.asarray(signal, dtype=float)
    signal = signal[np.isfinite(signal)]

    if len(signal) < int(sampling_rate * 2):
        return np.nan

    freqs, power = welch(
        signal,
        fs=sampling_rate,
        nperseg=min(int(sampling_rate * 2), len(signal)),
    )

    band_mask = (freqs >= band[0]) & (freqs <= band[1])
    if not np.any(band_mask):
        return np.nan

    return float(np.trapezoid(power[band_mask], freqs[band_mask]))
