import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TypedDict

import matplotlib.pyplot as plt
import neurokit2 as nk
import pandas as pd
import pandera.pandas as pa
from matplotlib.figure import Figure

from mooi_toolbox.processing import trial_intervals
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.output_data import PipelineOutputData
from mooi_toolbox.processing.pipeline import ProcessPhysiologyFallbackStrategy

logger = logging.getLogger(__name__)


def build_eda_physiology_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema(
        {
            r"^.+_SCR_per_min$": pa.Column(
                float,
                nullable=True,
                coerce=True,
                required=False,
                regex=True,
            )
        },
        coerce=True,
        strict=False,
    )


@dataclass
class EdaPhysiologyOutputData(PipelineOutputData):
    validation_schema: pa.DataFrameSchema = field(
        default_factory=build_eda_physiology_output_schema
    )


class EDAProcessingError(Exception):
    """Raised when EDA processing fails."""


class nkEDAProcessingResult(TypedDict):
    """
    Neurokit2 out: Return class that combines cleaned, decomposed and peaks info from the
    neurokit2 toolbox.
    """

    total_time_min: float
    eda_cleaned: pd.Series
    eda_decomposed: pd.DataFrame
    eda_peaks_info: tuple[pd.DataFrame, dict]


class ProcessEdaPhysiologyFallbackStrategyStep:
    def run(self, config_in: ParticipantConfig, biodata_in: RawBioData) -> EdaPhysiologyOutputData:
        trial_interval_data = trial_intervals.get_raw_biopac_trigger_intervals(
            biodata_in.raw_data["Trigger"]
        )

        scr_df_out = run_eda_intervals(biodata_in.raw_data["EDA"], trial_interval_data.intervals)
        eda_pipeline_out = EdaPhysiologyOutputData(config_in.subject_id)
        eda_pipeline_out.append_dataframe(scr_df_out, {})
        eda_pipeline_out.figure_data_out["eda_qc"] = run_eda_qc(
            biodata_in.raw_data["EDA"], scr_df_out, trial_interval_data.intervals
        )
        return eda_pipeline_out


@dataclass
class ProcessEdaPhysiologyDataStrategyStep:
    input_data_type: type[RawBioData] = RawBioData
    fallback_strategy: ProcessPhysiologyFallbackStrategy[RawBioData] | None = field(
        default_factory=ProcessEdaPhysiologyFallbackStrategyStep
    )

    def run(
        self,
        config_in: ParticipantConfig,
        biodata_in: RawBioData,
        trial_interval_data: trial_intervals.TrialIntervals,
    ) -> EdaPhysiologyOutputData:

        scr_df = run_eda_intervals(biodata_in.raw_data["EDA"], trial_interval_data.intervals)
        scr_df_corrected = correct_order(scr_df)
        eda_pipeline_out = EdaPhysiologyOutputData(config_in.subject_id)
        eda_pipeline_out.append_dataframe(scr_df_corrected, {})
        eda_pipeline_out.figure_data_out["eda_qc"] = run_eda_qc(
            biodata_in.raw_data["EDA"], scr_df_corrected, trial_interval_data.intervals
        )
        return eda_pipeline_out


def run_eda_qc(
    eda_raw_timestamped: pd.DataFrame,
    eda_data_out: pd.DataFrame | None = None,
    vr_intervals: dict[str, tuple[float, float]] | None = None,
) -> Figure:
    """Runs optional QC which includes plotting the whole timeseries and outputting basic info"""
    # Plot the entire timeseries
    complete_ts_eda_out: nkEDAProcessingResult = run_nk_eda_processing(eda_raw_timestamped["EDA"])
    return plot_eda(eda_raw_timestamped, eda_data_out, complete_ts_eda_out, vr_intervals)


def run_nk_eda_processing(
    eda_raw_series_df: pd.Series,
    clean_method: str = "biosppy",
    peak_detect_method: str = "vanhalem2020",
    sampling_rate: float = 1000,
) -> nkEDAProcessingResult:
    """
    Wrap neurokit2 toolbox EDA functions on one set of timeseries data and return values as a
    combined dictionary.

    """
    try:
        total_time_min: float = (len(eda_raw_series_df) / sampling_rate) / 60
        eda_cleaned = nk.eda_clean(
            eda_raw_series_df, sampling_rate=sampling_rate, method=clean_method
        )  # type: ignore
        eda_decomposed = nk.eda_phasic(eda_cleaned, sampling_rate=sampling_rate)  # type: ignore
        eda_peaks_info = nk.eda_peaks(
            eda_decomposed["EDA_Phasic"], sampling_rate=sampling_rate, method=peak_detect_method
        )  # type: ignore
    except (ValueError, TypeError, KeyError) as error:
        raise EDAProcessingError(
            f"Could not process EDA with clean_method={clean_method!r}, "
            f"peak_detect_method={peak_detect_method!r}, "
            f"sampling_rate={sampling_rate!r}"
        ) from error

    return {
        "total_time_min": total_time_min,
        "eda_cleaned": eda_cleaned,
        "eda_decomposed": eda_decomposed,
        "eda_peaks_info": eda_peaks_info,
    }


def run_eda_intervals(
    eda_raw_timestamped_full_ts: pd.DataFrame, vr_intervals: dict[str, tuple[float, float]]
) -> pd.DataFrame:
    """
    Wraps run_eda_processing. Loops over vr intervals and slices the biosignal_df into parts for
    individual processing. Those parts are then concatenated into an out dataframe.
    Note can also do one interval.
    """
    biosignals_dfs_dict = trial_intervals.slice_data_frame(
        eda_raw_timestamped_full_ts, vr_intervals
    )
    eda_parts = []

    for key, eda_raw_interval_timestamped in biosignals_dfs_dict.items():
        try:
            eda_raw_interval = eda_raw_interval_timestamped["EDA"]
            eda_info_out = run_nk_eda_processing(eda_raw_interval)
            eda_data_out = get_eda_data_out(eda_info_out, interval_label=f"{key}_")
            eda_parts.append(eda_data_out)
        except EDAProcessingError:
            logger.warning("Skipping EDA for interval %s", key)
            continue

    return pd.concat(eda_parts, axis=1)


def plot_eda(
    eda_raw_timestamped: pd.DataFrame,
    scr_participant_data: pd.DataFrame | None = None,
    nk_complete_ts_out: nkEDAProcessingResult | None = None,
    vr_intervals=None,
    show_plots=False,
) -> Figure:

    fig = plt.figure(figsize=(12, 8))
    gs = fig.add_gridspec(4, 1)
    axs = [
        fig.add_subplot(gs[0, 0]),
        fig.add_subplot(gs[1, 0], sharex=None),
        fig.add_subplot(gs[2, 0], sharex=None),
        fig.add_subplot(gs[3, 0]),
    ]
    axs[1].sharex(axs[0])
    axs[2].sharex(axs[0])
    time_min = (
        eda_raw_timestamped["time_stamps"] - eda_raw_timestamped["time_stamps"].iloc[0]
    ) / 60

    # Plot raw EDA signal and decomposed tonic component if available
    axs[0].plot(time_min, eda_raw_timestamped["EDA"], label="Raw EDA signal", alpha=0.7)

    if nk_complete_ts_out is not None:
        axs[0].plot(
            time_min,
            nk_complete_ts_out["eda_decomposed"]["EDA_Tonic"],
            label="EDA Tonic",
            alpha=0.7,
        )

    axs[0].set_title("Signal Over Time: EDA")
    axs[0].set_xlabel("Time (minutes)")
    axs[0].set_ylabel("EDA Signal (µS)")
    axs[0].legend(loc="upper left")

    if scr_participant_data is not None and nk_complete_ts_out is not None:
        # Plot cleaned EDA signal if available
        axs[1].plot(time_min, nk_complete_ts_out["eda_cleaned"], label="EDA Cleaned")
        axs[1].set_title("EDA Cleaned")
        axs[1].set_xlabel("Time (minutes)")
        axs[1].set_ylabel("Amplitude (µS)")
        axs[1].legend(loc="upper left")

        # Plot decomposed phasic component in the last subplot if available

        axs[2].plot(
            time_min,
            nk_complete_ts_out["eda_decomposed"]["EDA_Phasic"],
            label="EDA Phasic",
            alpha=0.7,
            color="orange",
        )
        axs[2].set_title("EDA Phasic Component")
        axs[2].set_xlabel("Time (minutes)")
        axs[2].set_ylabel("EDA Phasic (µS)")
        axs[2].legend(loc="upper left")

        scr_participant_data.filter(like="SCR_per_min").iloc[0].plot(
            kind="bar",
            ax=axs[3],
        )
        labels = [label.get_text().split("_", 1)[0] for label in axs[3].get_xticklabels()]
        axs[3].set_xticklabels(labels)

        axs[3].set_xlabel("Timepoints")
        axs[3].set_ylabel("SCR per min")
        axs[3].set_title("FOH EDA")

    # Add interval data if available

    if vr_intervals is not None:
        for i, (interval_name, (interval_start, interval_end)) in enumerate(vr_intervals.items()):
            color = f"C{i % 10}"  # cycle through matplotlib default colors
            interval_start_min = (interval_start - eda_raw_timestamped["time_stamps"].iloc[0]) / 60
            interval_end_min = (interval_end - eda_raw_timestamped["time_stamps"].iloc[0]) / 60
            # Add a vertical line on every subplot for interval start and end
            for ax in axs[:3]:
                ax.axvline(interval_start_min, color=color, linestyle="--", alpha=0.8)
                ax.text(
                    interval_start_min,
                    ax.get_ylim()[1],
                    f"{interval_name} start",
                    color=color,
                    rotation=90,
                    va="top",
                    ha="left",
                    fontsize=8,
                )
                ax.axvline(interval_end_min, color=color, linestyle=":", alpha=0.8)
                ax.text(
                    interval_end_min,
                    ax.get_ylim()[1],
                    f"{interval_name} end",
                    color=color,
                    rotation=90,
                    va="top",
                    ha="right",
                    fontsize=8,
                )

    plt.tight_layout()

    if show_plots:
        plt.show()

    return fig


def get_eda_data_out(eda_proc_out: nkEDAProcessingResult, interval_label: str = "") -> pd.DataFrame:
    """Count EDA SCR peaks and calculate mean of the Tonic signal. Return as a DataFrame."""
    time_min = eda_proc_out["total_time_min"]

    return pd.DataFrame(
        {
            f"{interval_label}SCR_per_min": [
                len(eda_proc_out["eda_peaks_info"][1]["SCR_Peaks"]) / time_min
            ]
        }
    )


def correct_order(df_in: pd.DataFrame) -> pd.DataFrame:
    split_cols = [col.split("_") for col in df_in.columns]

    new_cols_parts = []
    for split_c in split_cols:
        new_split = []
        for c in split_c:
            new_c = "".join(re.sub(r"\d+", "", c))
            if new_c != "":
                new_split.append(new_c)
        new_cols_parts.append(new_split)

    new_cols = ["_".join(new_col_part) for new_col_part in new_cols_parts]

    counts = defaultdict(int)

    corrected_cols = []

    for col in new_cols:
        counts[col] += 1
        corrected_cols.append(f"{col}_{counts[col]}")

    df_out = df_in.copy()
    df_out.columns = corrected_cols

    return df_out
