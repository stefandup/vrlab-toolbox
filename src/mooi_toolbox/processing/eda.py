import neurokit2 as nk
import pandas as pd

def run_eda_processing(eda_raw,clean_method = 'biosppy',peak_detect_method='vanhalem2020',sampling_rate=1000):

    eda_cleaned = nk.eda_clean(eda_raw, sampling_rate=sampling_rate, method=clean_method)
    eda_decomposed = nk.eda_phasic(eda_cleaned, sampling_rate=sampling_rate)
    eda_peaks_info = nk.eda_peaks(eda_decomposed["EDA_Phasic"], sampling_rate=sampling_rate, method=peak_detect_method)

    return {
        "eda_cleaned" : eda_cleaned,
        "eda_decomposed" : eda_decomposed,
        "eda_peaks_info": eda_peaks_info
    }

def plot_eda(eda_proc_out,interval_label,show_plots):
    pass

def get_eda_data_out(eda_proc_out,interval_label=''):

    return pd.DataFrame({f'{interval_label}Tonic_mean': [eda_proc_out['eda_decomposed']['EDA_Tonic'].mean()],
             f'{interval_label}SCR_total_peaks': len(eda_proc_out['eda_peaks_info'][1]['SCR_Peaks'])})