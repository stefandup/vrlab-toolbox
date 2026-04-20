import neurokit2 as nk
import warnings
from pandas.errors import SettingWithCopyWarning

class ECGProcessingError(Exception):
    """Raised when ECG processing fails."""

def run_ecg_processing(ecg_raw,clean_method = 'biosppy',peak_detect_method='neurokit',sampling_rate=1000):
    ecg_cleaned =nk.ecg_clean(ecg_raw, sampling_rate=sampling_rate, method=clean_method,)
    peak_info = nk.ecg_findpeaks(ecg_cleaned,sampling_rate,method=peak_detect_method,show=False)
    
    with warnings.catch_warnings():
    
        # TODO: Note nk has several warnings that will hopefully be addressed at update
        warnings.simplefilter("ignore", category=SettingWithCopyWarning)
        warnings.simplefilter("ignore", category=FutureWarning)

        waves,signals = nk.ecg_delineate(ecg_cleaned,
                                        peak_info,
                                        sampling_rate=sampling_rate,
                                        method='peak',
                                        show=False,
                                        show_type='peaks',
                                        check=True)
    #TODO: Combine all these outputs together... maybe a dictionary?
    hrv_df = nk.hrv(peak_info,sampling_rate=sampling_rate,show=False)

    tot_q_peak_count = (waves["ECG_Q_Peaks"] == 1).sum()
    print(f"Total peak count: {tot_q_peak_count}")

    return hrv_df
