import logging
from typing import TypedDict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from scipy.signal import welch

import mne
import plotly.graph_objects as go

logger = logging.getLogger(__name__)


class EEGProcessingError(Exception):
    """Raised when EEG QC processing fails."""


class EEGQCResult(TypedDict):
    total_time_min: float
    raw_before: mne.io.Raw
    raw_filtered: mne.io.Raw
    channel_qc: pd.DataFrame
    timestamp_qc: pd.DataFrame


DEFAULT_EEG_CHANNELS = [
    "P3", "C3", "F3", "Fz", "F4", "C4", "P4", "Cz",
    "A1", "Fp1", "Fp2", "T3", "T5", "O1", "O2",
    "F7", "F8", "A2", "T6", "T4", "Pz"
]


def get_available_channels(df, eeg_channels=None):
    if eeg_channels is None:
        eeg_channels = DEFAULT_EEG_CHANNELS

    return [ch for ch in eeg_channels if ch in df.columns]


def estimate_sampling_rate_from_timestamps(
    eeg_raw_timestamped,
    time_col="time_stamps",
    fallback_sampling_rate=300,
):
    if time_col not in eeg_raw_timestamped.columns:
        return fallback_sampling_rate

    timestamps = eeg_raw_timestamped[time_col].to_numpy()

    if len(timestamps) < 3:
        return fallback_sampling_rate

    diffs = np.diff(timestamps)
    diffs = diffs[np.isfinite(diffs)]
    diffs = diffs[diffs > 0]

    if len(diffs) == 0:
        return fallback_sampling_rate

    median_diff = np.median(diffs)

    if median_diff <= 0:
        return fallback_sampling_rate

    return float(1 / median_diff)


def make_mne_raw(
    eeg_timestamped_df,
    sampling_rate=300,
    eeg_channels=None,
    convert_uv_to_v=True,
):
    available_channels = get_available_channels(eeg_timestamped_df, eeg_channels)

    if len(available_channels) == 0:
        raise EEGProcessingError("No EEG channels found in dataframe.")

    data = eeg_timestamped_df[available_channels].to_numpy().T

    if convert_uv_to_v:
        data = data * 1e-6

    info = mne.create_info(
        ch_names=available_channels,
        sfreq=sampling_rate,
        ch_types="eeg",
    )

    raw = mne.io.RawArray(data, info, verbose=False)

    try:
        montage = mne.channels.make_standard_montage("standard_1020")
        raw.set_montage(montage, on_missing="ignore", verbose=False)
    except Exception as error:
        logger.warning("Could not set montage: %s", error)

    return raw


def crop_dataframe_by_seconds(
    df,
    sampling_rate,
    plot_start_sec=None,
    plot_end_sec=None,
    time_col="time_stamps",
):
    if plot_start_sec is None and plot_end_sec is None:
        return df.copy()

    if time_col in df.columns:
        first_ts = df[time_col].iloc[0]
        relative_time_sec = df[time_col] - first_ts

        if plot_start_sec is None:
            plot_start_sec = float(relative_time_sec.min())

        if plot_end_sec is None:
            plot_end_sec = float(relative_time_sec.max())

        return df[
            (relative_time_sec >= plot_start_sec)
            & (relative_time_sec <= plot_end_sec)
        ].copy()

    start_idx = 0 if plot_start_sec is None else int(plot_start_sec * sampling_rate)
    end_idx = len(df) if plot_end_sec is None else int(plot_end_sec * sampling_rate)

    start_idx = max(0, start_idx)
    end_idx = min(len(df), end_idx)

    return df.iloc[start_idx:end_idx].copy()


def compute_timestamp_qc(
    eeg_raw_timestamped,
    expected_sampling_rate=300,
    time_col="time_stamps",
):
    if time_col not in eeg_raw_timestamped.columns:
        return pd.DataFrame({
            "has_timestamps": [False],
            "n_samples": [len(eeg_raw_timestamped)],
            "estimated_sampling_rate": [np.nan],
            "expected_sampling_rate": [expected_sampling_rate],
            "median_sample_diff_sec": [np.nan],
            "max_sample_diff_sec": [np.nan],
            "n_large_gaps": [np.nan],
        })

    timestamps = eeg_raw_timestamped[time_col].to_numpy()
    diffs = np.diff(timestamps)

    valid_diffs = diffs[np.isfinite(diffs)]
    valid_diffs = valid_diffs[valid_diffs > 0]

    if len(valid_diffs) == 0:
        estimated_sampling_rate = np.nan
        median_diff = np.nan
        max_diff = np.nan
        n_large_gaps = np.nan
    else:
        median_diff = float(np.median(valid_diffs))
        max_diff = float(np.max(valid_diffs))
        estimated_sampling_rate = float(1 / median_diff)

        expected_diff = 1 / expected_sampling_rate
        large_gap_threshold = expected_diff * 3
        n_large_gaps = int(np.sum(valid_diffs > large_gap_threshold))

    return pd.DataFrame({
        "has_timestamps": [True],
        "n_samples": [len(eeg_raw_timestamped)],
        "estimated_sampling_rate": [estimated_sampling_rate],
        "expected_sampling_rate": [expected_sampling_rate],
        "median_sample_diff_sec": [median_diff],
        "max_sample_diff_sec": [max_diff],
        "n_large_gaps": [n_large_gaps],
    })


def compute_channel_qc(eeg_raw_timestamped, eeg_channels=None):
    available_channels = get_available_channels(eeg_raw_timestamped, eeg_channels)

    rows = []

    for ch in available_channels:
        signal = eeg_raw_timestamped[ch].to_numpy()
        signal = signal[np.isfinite(signal)]

        if len(signal) == 0:
            rows.append({
                "channel": ch,
                "mean": np.nan,
                "std": np.nan,
                "min": np.nan,
                "max": np.nan,
                "range": np.nan,
                "flat_flag": True,
                "high_noise_flag": False,
                "notes": "No valid values",
            })
            continue

        signal_std = float(np.std(signal))
        signal_range = float(np.max(signal) - np.min(signal))

        flat_flag = signal_std < 0.5
        high_noise_flag = signal_std > 200

        notes = []
        if flat_flag:
            notes.append("Possible flat channel")
        if high_noise_flag:
            notes.append("Possible noisy channel")

        rows.append({
            "channel": ch,
            "mean": float(np.mean(signal)),
            "std": signal_std,
            "min": float(np.min(signal)),
            "max": float(np.max(signal)),
            "range": signal_range,
            "flat_flag": flat_flag,
            "high_noise_flag": high_noise_flag,
            "notes": "; ".join(notes) if notes else "Looks okay",
        })

    return pd.DataFrame(rows)


def apply_basic_eeg_filter(
    raw,
    bad_channels=None,
    notch_freq=50,
    l_freq=1,
    h_freq=40,
    reference="average",
):
    raw_filtered = raw.copy()

    if bad_channels is not None:
        existing_bad_channels = [
            ch for ch in bad_channels if ch in raw_filtered.ch_names
        ]

        raw_filtered.info["bads"] = existing_bad_channels

        if len(existing_bad_channels) > 0:
            raw_filtered.drop_channels(existing_bad_channels)

    if notch_freq is not None:
        raw_filtered.notch_filter(
            freqs=[notch_freq],
            verbose=False,
        )

    raw_filtered.filter(
        l_freq=l_freq,
        h_freq=h_freq,
        verbose=False,
    )

    if reference == "average":
        raw_filtered.set_eeg_reference(
            ref_channels="average",
            verbose=False,
        )

    return raw_filtered


def plot_stacked_eeg_channels_matplotlib(
    ax,
    time_min,
    data_uv,
    channel_names,
    title,
    max_channels=10,
):
    n_channels = min(max_channels, len(channel_names))

    if n_channels == 0:
        ax.set_title(title)
        ax.text(0.5, 0.5, "No channels available", ha="center", va="center")
        return

    selected_data = data_uv[:n_channels]
    selected_names = channel_names[:n_channels]

    robust_scale = np.nanpercentile(np.abs(selected_data), 95)

    if not np.isfinite(robust_scale) or robust_scale == 0:
        robust_scale = 1

    spacing = robust_scale * 4

    for idx, ch in enumerate(selected_names):
        offset = idx * spacing
        ax.plot(
            time_min,
            selected_data[idx] + offset,
            linewidth=0.8,
            label=ch,
        )

    ax.set_yticks([idx * spacing for idx in range(n_channels)])
    ax.set_yticklabels(selected_names)
    ax.set_title(title)
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Channels")
    ax.grid(True, alpha=0.2)


def plot_stacked_eeg_channels_plotly(
    raw,
    title,
    max_channels=10,
    plot_start_sec=None,
    plot_end_sec=None,
    save_html_path=None,
):
    raw_plot = raw.copy()

    if plot_start_sec is not None or plot_end_sec is not None:
        tmin = 0 if plot_start_sec is None else plot_start_sec
        tmax = raw_plot.times[-1] if plot_end_sec is None else plot_end_sec

        raw_plot.crop(
            tmin=tmin,
            tmax=tmax,
            include_tmax=True,
        )

    data_uv = raw_plot.get_data() * 1e6
    time_min = raw_plot.times / 60
    channel_names = raw_plot.ch_names

    n_channels = min(max_channels, len(channel_names))

    if n_channels == 0:
        raise EEGProcessingError("No channels available for Plotly graph.")

    selected_data = data_uv[:n_channels]
    selected_names = channel_names[:n_channels]

    robust_scale = np.nanpercentile(np.abs(selected_data), 95)

    if not np.isfinite(robust_scale) or robust_scale == 0:
        robust_scale = 1

    spacing = robust_scale * 4

    fig = go.Figure()

    for idx, ch in enumerate(selected_names):
        fig.add_trace(
            go.Scatter(
                x=time_min,
                y=selected_data[idx] + idx * spacing,
                mode="lines",
                name=ch,
                line=dict(width=1),
                hovertemplate=(
                    f"Channel: {ch}<br>"
                    "Time: %{x:.3f} min<br>"
                    "Signal + offset: %{y:.2f} µV"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=title,
        height=700,
        template="plotly_white",
        hovermode="x unified",
        xaxis_title="Time (minutes)",
        yaxis_title="Channels",
        xaxis=dict(
            rangeslider=dict(visible=True),
            type="linear",
        ),
        yaxis=dict(
            tickmode="array",
            tickvals=[idx * spacing for idx in range(n_channels)],
            ticktext=selected_names,
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
        margin=dict(l=80, r=30, t=90, b=80),
    )

    if save_html_path is not None:
        fig.write_html(save_html_path)

    return fig


def plot_eeg_qc_static(
    eeg_raw_timestamped,
    eeg_qc_out,
    plot_start_sec=None,
    plot_end_sec=None,
    max_plot_channels=10,
    show_plots=False,
):
    raw_before = eeg_qc_out["raw_before"]
    raw_filtered = eeg_qc_out["raw_filtered"]
    channel_qc = eeg_qc_out["channel_qc"]
    timestamp_qc = eeg_qc_out["timestamp_qc"]

    sfreq = raw_before.info["sfreq"]

    cropped_df = crop_dataframe_by_seconds(
        df=eeg_raw_timestamped,
        sampling_rate=sfreq,
        plot_start_sec=plot_start_sec,
        plot_end_sec=plot_end_sec,
    )

    crop_start_sample = eeg_raw_timestamped.index.get_indexer(
        [cropped_df.index[0]],
        method=None,
    )[0]

    crop_end_sample = eeg_raw_timestamped.index.get_indexer(
        [cropped_df.index[-1]],
        method=None,
    )[0]

    crop_start_time = crop_start_sample / sfreq
    crop_end_time = crop_end_sample / sfreq

    raw_before_crop = raw_before.copy().crop(
        tmin=crop_start_time,
        tmax=crop_end_time,
        include_tmax=True,
    )

    raw_filtered_crop = raw_filtered.copy().crop(
        tmin=crop_start_time,
        tmax=crop_end_time,
        include_tmax=True,
    )

    time_min = raw_before_crop.times / 60

    raw_data_uv = raw_before_crop.get_data() * 1e6
    filtered_data_uv = raw_filtered_crop.get_data() * 1e6

    fig = plt.figure(figsize=(14, 12))
    gs = fig.add_gridspec(4, 1, height_ratios=[1.1, 2.5, 2.5, 1.8])

    ax_info = fig.add_subplot(gs[0, 0])
    ax_raw = fig.add_subplot(gs[1, 0])
    ax_filtered = fig.add_subplot(gs[2, 0])
    ax_channels = fig.add_subplot(gs[3, 0])

    ax_info.axis("off")

    ts_row = timestamp_qc.iloc[0]

    info_text = (
        f"EEG QC summary\n"
        f"Samples: {int(ts_row['n_samples'])}\n"
        f"Duration: {eeg_qc_out['total_time_min']:.2f} minutes\n"
        f"Expected sampling rate: {ts_row['expected_sampling_rate']:.2f} Hz\n"
        f"Estimated sampling rate: {ts_row['estimated_sampling_rate']:.2f} Hz\n"
        f"Median sample difference: {ts_row['median_sample_diff_sec']:.6f} sec\n"
        f"Maximum sample difference: {ts_row['max_sample_diff_sec']:.6f} sec\n"
        f"Large timestamp gaps: {ts_row['n_large_gaps']}"
    )

    ax_info.text(
        0.01,
        0.95,
        info_text,
        va="top",
        ha="left",
        fontsize=10,
        family="monospace",
    )

    plot_stacked_eeg_channels_matplotlib(
        ax=ax_raw,
        time_min=time_min,
        data_uv=raw_data_uv,
        channel_names=raw_before_crop.ch_names,
        title="Raw EEG Signal",
        max_channels=max_plot_channels,
    )

    plot_stacked_eeg_channels_matplotlib(
        ax=ax_filtered,
        time_min=time_min,
        data_uv=filtered_data_uv,
        channel_names=raw_filtered_crop.ch_names,
        title="Basic Filtered EEG: 50 Hz Notch + 1–40 Hz Bandpass + Average Reference",
        max_channels=max_plot_channels,
    )

    channel_qc_plot = channel_qc.copy()

    if len(channel_qc_plot) > 0:
        channel_qc_plot = channel_qc_plot.sort_values("std", ascending=False)

        ax_channels.bar(
            channel_qc_plot["channel"],
            channel_qc_plot["std"],
        )

        ax_channels.set_title("Channel Standard Deviation Check")
        ax_channels.set_xlabel("Channel")
        ax_channels.set_ylabel("Standard deviation")
        ax_channels.tick_params(axis="x", rotation=45)

        for _, row in channel_qc_plot.iterrows():
            if row["flat_flag"] or row["high_noise_flag"]:
                ax_channels.text(
                    row["channel"],
                    row["std"],
                    "flag",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                )

    plt.tight_layout()

    if show_plots:
        plt.show()

    return fig


def run_mne_eeg_qc_processing(
    eeg_raw_timestamped,
    sampling_rate=None,
    expected_sampling_rate=300,
    eeg_channels=None,
    bad_channels=None,
    notch_freq=50,
    l_freq=1,
    h_freq=40,
    reference="average",
    convert_uv_to_v=True,
):
    try:
        if sampling_rate is None:
            sampling_rate = estimate_sampling_rate_from_timestamps(
                eeg_raw_timestamped,
                fallback_sampling_rate=expected_sampling_rate,
            )

        total_time_min = len(eeg_raw_timestamped) / sampling_rate / 60

        timestamp_qc = compute_timestamp_qc(
            eeg_raw_timestamped,
            expected_sampling_rate=expected_sampling_rate,
        )

        channel_qc = compute_channel_qc(
            eeg_raw_timestamped,
            eeg_channels=eeg_channels,
        )

        raw_before = make_mne_raw(
            eeg_timestamped_df=eeg_raw_timestamped,
            sampling_rate=sampling_rate,
            eeg_channels=eeg_channels,
            convert_uv_to_v=convert_uv_to_v,
        )

        raw_filtered = apply_basic_eeg_filter(
            raw=raw_before,
            bad_channels=bad_channels,
            notch_freq=notch_freq,
            l_freq=l_freq,
            h_freq=h_freq,
            reference=reference,
        )

    except Exception as error:
        raise EEGProcessingError(
            f"Could not run EEG QC with sampling_rate={sampling_rate!r}, "
            f"expected_sampling_rate={expected_sampling_rate!r}, "
            f"notch_freq={notch_freq!r}, "
            f"l_freq={l_freq!r}, "
            f"h_freq={h_freq!r}, "
            f"reference={reference!r}"
        ) from error

    return {
        "total_time_min": total_time_min,
        "raw_before": raw_before,
        "raw_filtered": raw_filtered,
        "channel_qc": channel_qc,
        "timestamp_qc": timestamp_qc,
    }


def run_eeg_qc(
    eeg_raw_timestamped,
    sampling_rate=None,
    expected_sampling_rate=300,
    eeg_channels=None,
    bad_channels=None,
    notch_freq=50,
    l_freq=1,
    h_freq=40,
    reference="average",
    convert_uv_to_v=True,
    plot_start_sec=None,
    plot_end_sec=None,
    max_plot_channels=10,
    show_static_plots=False,
    show_interactive_plots=True,
    save_interactive_html=True,
):
    eeg_qc_out = run_mne_eeg_qc_processing(
        eeg_raw_timestamped=eeg_raw_timestamped,
        sampling_rate=sampling_rate,
        expected_sampling_rate=expected_sampling_rate,
        eeg_channels=eeg_channels,
        bad_channels=bad_channels,
        notch_freq=notch_freq,
        l_freq=l_freq,
        h_freq=h_freq,
        reference=reference,
        convert_uv_to_v=convert_uv_to_v,
    )

    static_fig = plot_eeg_qc_static(
        eeg_raw_timestamped=eeg_raw_timestamped,
        eeg_qc_out=eeg_qc_out,
        plot_start_sec=plot_start_sec,
        plot_end_sec=plot_end_sec,
        max_plot_channels=max_plot_channels,
        show_plots=show_static_plots,
    )

    raw_html = "interactive_raw_eeg.html" if save_interactive_html else None
    filtered_html = "interactive_filtered_eeg.html" if save_interactive_html else None

    raw_interactive_fig = plot_stacked_eeg_channels_plotly(
        raw=eeg_qc_out["raw_before"],
        title="Interactive Raw EEG Signal",
        max_channels=max_plot_channels,
        plot_start_sec=plot_start_sec,
        plot_end_sec=plot_end_sec,
        save_html_path=raw_html,
    )

    filtered_interactive_fig = plot_stacked_eeg_channels_plotly(
        raw=eeg_qc_out["raw_filtered"],
        title="Interactive Filtered EEG Signal: 50 Hz Notch + 1–40 Hz Bandpass + Average Reference",
        max_channels=max_plot_channels,
        plot_start_sec=plot_start_sec,
        plot_end_sec=plot_end_sec,
        save_html_path=filtered_html,
    )

    if show_interactive_plots:
        raw_interactive_fig.show()
        filtered_interactive_fig.show()

    timestamp_qc = eeg_qc_out["timestamp_qc"].add_prefix("EEG_")
    channel_qc = eeg_qc_out["channel_qc"]

    flagged_channels = channel_qc[
        (channel_qc["flat_flag"] == True)
        | (channel_qc["high_noise_flag"] == True)
    ]["channel"].tolist()

    qc_data_out = timestamp_qc.copy()
    qc_data_out["EEG_n_channels"] = len(channel_qc)
    qc_data_out["EEG_flagged_channels"] = ", ".join(flagged_channels)
    qc_data_out["EEG_n_flagged_channels"] = len(flagged_channels)

    return qc_data_out, static_fig, raw_interactive_fig, filtered_interactive_fig


if __name__ == "__main__":

    import pyxdf

    xdf_fn = "/Users/suzetteschulenburg/Desktop/PhD/MobiLab/Code/Code/MobiLab/DataTest/sub-TestZuk/ses-S001/eeg/sub-TestEEGk_ses-S001_task-Default_run-001_eeg.xdf"

    streams, _ = pyxdf.load_xdf(xdf_fn)

    eeg_stream = None

    for stream in streams:
        stream_type = stream["info"]["type"][0]

        if stream_type.upper() == "EEG":
            eeg_stream = stream
            break

    if eeg_stream is None:
        raise ValueError("No EEG stream found in XDF.")

    eeg_data = np.array(eeg_stream["time_series"])
    eeg_timestamps = np.array(eeg_stream["time_stamps"])

    channel_labels = [
        ch["label"][0]
        for ch in eeg_stream["info"]["desc"][0]["channels"][0]["channel"]
    ]

    eeg_df = pd.DataFrame(
        eeg_data,
        columns=channel_labels,
    )

    eeg_df["time_stamps"] = eeg_timestamps

    qc_data, static_fig, raw_fig, filtered_fig = run_eeg_qc(
        eeg_raw_timestamped=eeg_df,
        sampling_rate=None,
        expected_sampling_rate=300,

        # Example:
        # bad_channels=["F3"],
        bad_channels=None,

        # Use None for the full recording.
        # Or use seconds, for example:
        # plot_start_sec=0,
        # plot_end_sec=60,
        plot_start_sec=None,
        plot_end_sec=None,

        max_plot_channels=10,

        # Static matplotlib QC figure.
        show_static_plots=True,

        # Interactive Plotly figures with slider underneath.
        show_interactive_plots=True,

        # Saves:
        # interactive_raw_eeg.html
        # interactive_filtered_eeg.html
        save_interactive_html=True,
    )

    print(qc_data)

    print("\nSaved interactive files:")
    print("interactive_raw_eeg.html")
    print("interactive_filtered_eeg.html")