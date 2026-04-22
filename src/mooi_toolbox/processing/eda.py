import neurokit2 as nk
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from typing import TypedDict

class EDAProcessingError(Exception):
    """Raised when EDA processing fails."""

class EDAProcessingResult(TypedDict):
    """Return class that combines cleaned, decomposed and peaks info from the neurokit2 toolbox."""
    total_time_min: int
    eda_cleaned: pd.Series
    eda_decomposed: pd.DataFrame
    eda_peaks_info: tuple[pd.DataFrame,dict]

def run_eda_processing(eda_raw,clean_method = 'biosppy',peak_detect_method='vanhalem2020',sampling_rate=1000)  -> EDAProcessingResult:
    """Wrap neurokit2 toolbox EDA functions and return values as a combined dictionary."""
    try:
        total_time_min : int = (len(eda_raw)/sampling_rate) / 60
        eda_cleaned = nk.eda_clean(eda_raw, sampling_rate=sampling_rate, method=clean_method)
        eda_decomposed = nk.eda_phasic(eda_cleaned, sampling_rate=sampling_rate)
        eda_peaks_info = nk.eda_peaks(eda_decomposed["EDA_Phasic"], sampling_rate=sampling_rate, method=peak_detect_method)
    except (ValueError, TypeError, KeyError) as error:
            raise EDAProcessingError(
                f"Could not process EDA with clean_method={clean_method!r}, "
                f"peak_detect_method={peak_detect_method!r}, "
                f"sampling_rate={sampling_rate!r}"
            ) from error

    return {
        "total_time_min" : total_time_min,
        "eda_cleaned" : eda_cleaned,
        "eda_decomposed" : eda_decomposed,
        "eda_peaks_info": eda_peaks_info
    }

def plot_eda(biosignals_df : pd.DataFrame,eda_df : pd.DataFrame | None = None , 
             nk_complete_ts_out : EDAProcessingResult | None = None,vr_intervals=None,
             show_plots=False) -> Figure:

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
    time_min = (biosignals_df['time_stamps'] - biosignals_df['time_stamps'].iloc[0]) / 60

    # Plot raw EDA signal and decomposed tonic component if available
    axs[0].plot(time_min, biosignals_df['EDA0'], label='Raw EDA signal', alpha=0.7)
    
    if nk_complete_ts_out is not None:
        axs[0].plot(time_min, nk_complete_ts_out['eda_decomposed']['EDA_Tonic'], label='EDA Tonic', alpha=0.7)
    
    axs[0].set_title('Signal Over Time: EDA')
    axs[0].set_xlabel('Time (minutes)')
    axs[0].set_ylabel('EDA Signal (µS)')
    axs[0].legend()

    if eda_df is not None:
        # Plot cleaned EDA signal if available
        axs[1].plot(time_min, nk_complete_ts_out['eda_cleaned'], label='EDA Cleaned')
        axs[1].set_title('EDA Cleaned')
        axs[1].set_xlabel('Time (minutes)')
        axs[1].set_ylabel('Amplitude (µS)')
        axs[1].legend()
        
        # Plot decomposed phasic component in the last subplot if available

        axs[2].plot(time_min, nk_complete_ts_out['eda_decomposed']['EDA_Phasic'], label='EDA Phasic', alpha=0.7, color='orange')
        axs[2].set_title('EDA Phasic Component')
        axs[2].set_xlabel('Time (minutes)')
        axs[2].set_ylabel('EDA Phasic (µS)')
        axs[2].legend()

    # Add interval data if available

        if vr_intervals is not None and len(eda_df.columns) == 6:

            axs[3].bar(["Baseline", "Stress", "Recovery"],
                    [eda_df['baseline_SCR_per_min'][0],
                    eda_df['stress_SCR_per_min'][0],
                    eda_df['recovery_SCR_per_min'][0]])
            axs[3].set_xlabel("Timepoints")
            axs[3].set_ylabel("SCR per min")
            axs[3].set_title("FOH EDA")

            for i, (interval_name, (interval_start, interval_end)) in enumerate(vr_intervals.items()):
                color = f"C{i % 10}"  # cycle through matplotlib default colors
                interval_start_min = (interval_start - biosignals_df['time_stamps'].iloc[0]) / 60
                interval_end_min = (interval_end - biosignals_df['time_stamps'].iloc[0]) / 60
                # Add a vertical line on every subplot for interval start and end
                for ax in axs[:3]:
                    ax.axvline(interval_start_min, color=color, linestyle='--', alpha=0.8)
                    ax.text(interval_start_min, ax.get_ylim()[1], f"{interval_name} start", color=color, rotation=90, va='top', ha='left', fontsize=8)
                    ax.axvline(interval_end_min, color=color, linestyle=':', alpha=0.8)
                    ax.text(interval_end_min, ax.get_ylim()[1], f"{interval_name} end", color=color, rotation=90, va='top', ha='right', fontsize=8)
 
        
    plt.tight_layout()

    if show_plots:
        plt.show()

    return fig

def get_eda_data_out(eda_proc_out : EDAProcessingResult,interval_label : str ='') -> pd.DataFrame:
    """Count EDA SCR peaks and calculate mean of the Tonic signal. Return as a DataFrame."""
    time_min = eda_proc_out['total_time_min']
    return pd.DataFrame({f'{interval_label}Tonic_mean': [eda_proc_out['eda_decomposed']['EDA_Tonic'].mean()],
             f'{interval_label}SCR_per_min': len(eda_proc_out['eda_peaks_info'][1]['SCR_Peaks'])/time_min})
