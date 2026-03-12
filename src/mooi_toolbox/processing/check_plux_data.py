import os
import pyxdf
import pandas as pd
from mooi_toolbox.read_mobi_xdf import xdf_io
from rich import print
import matplotlib.pyplot as plt
import neurokit2 as nk
from IPython import display
import sys

import warnings
from pandas.errors import SettingWithCopyWarning

plot_data = True

# Get xdf_fn from first command-line argument, if provided
if len(sys.argv) > 1:
    xdf_fn_cli = sys.argv[1]
    if not os.path.isabs(xdf_fn_cli):
        # If the path is relative, join it with the current working directory
        xdf_fn = os.path.join(os.getcwd(), xdf_fn_cli)
    else:
        xdf_fn = xdf_fn_cli
else:
    #xdf_fn_rel = r"local_MOBI_data\\sub-00003\\ses-S001\\philani\\sub-00003_ses-S001_task-Default_run-001_philani.xdf"
    xdf_fn_rel = r"local_MOBI_data\sub-00007\ses-S001\eeg\sub-00007_ses-S001_task-Default_run-001_eeg.xdf"
    work_dir = os.getcwd()
    xdf_fn = os.path.join(work_dir,xdf_fn_rel)

if not os.path.exists(xdf_fn):
    print(f"ERROR: {xdf_fn} does not exist")

streams, header = pyxdf.load_xdf(xdf_fn)

# Print information about the streams
print("-" * 40)
for stream in streams:
    print(f"Stream Name: {stream['info']['name'][0]}")
    print(f"Stream Type: {stream['info']['type'][0]}")
    print(f"Stream created at {stream['info']['created_at'][0]}")
    #print(pd.to_datetime(stream['info']['created_at'][0], unit="s", origin="unix"))
    print(f"Number of Channels: {stream['info']['channel_count'][0]}")
    print(f"Channel Format: {stream['info']['channel_format'][0]}")
    print(f"Sampling Rate: {stream['info']['nominal_srate'][0]}")
    print(f"Number of Samples: {len(stream['time_series'])}")
    # print("Sample Time Series Data:", stream[ 'time_series'][:5])
    # print("Sample Time Stamps:", stream['time_stamps'][:5])
    print("Dictionary Keys:", stream.keys())
    print("-"*40)


print("-"*40)
print("[blue]Stream: BIOSIGNALS[/blue]")
print("-"*40)
vr_marker_df, vr_marker_stream = xdf_io.extract_single_stream(streams,'VR_markers')
vr_marker_df = xdf_io.add_column_names(vr_marker_df, vr_marker_stream)
print(vr_marker_df.head(5))


#intervals = [
#    (vr_marker_df["time_stamps"].iloc[i], vr_marker_df["time_stamps"].iloc[i + 1])
#    for i in range(len(vr_marker_df) - 1)
#]

intervals = xdf_io.create_intervals_from_df(vr_marker_df)


biosignals_df, biosignals_stream = xdf_io.extract_single_stream(streams, 'OpenSignals')
biosignals_df = xdf_io.add_column_names(biosignals_df, biosignals_stream)
print(biosignals_df.head(5))

biosignal_interval_dfs = []

for i,interval in enumerate(intervals):
    biosignal_interval_dfs.append(xdf_io.cut_df_per_interval(interval,biosignals_df))

# TODO Use more extensive markers
vr_time_periods_dfs = xdf_io.divide_df_into_blocks(300,biosignal_interval_dfs[0])

print(pd.to_datetime(biosignals_df["time_stamps"], unit="s", origin="unix", utc=True))

### Biosignals sampling rate 

# Calcuate time difference between consecutive samples 
biosignals_df['time_diff'] = biosignals_df['time_stamps'].diff()

# Calculate sampling rate (Hz)
biosignals_df['sampling_rate'] = 1 / biosignals_df['time_diff']

# Display basic statistics
print("Sampling Rate Statistics:")
print(f"Mean sampling rate: {biosignals_df['sampling_rate'].mean():.2f} Hz")
print(f"Std sampling rate: {biosignals_df['sampling_rate'].std():.2f} Hz")
print(f"Min sampling rate: {biosignals_df['sampling_rate'].min():.2f} Hz")
print(f"Max sampling rate: {biosignals_df['sampling_rate'].max():.2f} Hz")

print("-"*40)
# print("timestamp min:", biosignals_df['time_stamps'].min())
# print("timestamp max:", biosignals_df['time_stamps'].max())
bio_duration_mins = (biosignals_df['time_stamps'].max() - biosignals_df['time_stamps'].min()) / 60
print(f"Duration of Biosignals Data: {bio_duration_mins} mins")

nominal_sample_rate=biosignals_stream['info']['nominal_srate'][0]

eda_raw = biosignals_df['EDA0'].values
eda_clean_methods = ['biosppy', 'neurokit']

eda_cleaned = {}

# Clean EDA with available methods. Biosppy seems consistently better, so using that as default.
for i, method in enumerate(eda_clean_methods):
    eda_cleaned[method] = nk.eda_clean(eda_raw, sampling_rate=nominal_sample_rate, method=method)

eda_decomposed = nk.eda_phasic(eda_cleaned['biosppy'], sampling_rate=nominal_sample_rate)
    
eda_peak_methods = ['neurokit', 'gamboa2008', 'kim2004', 'vanhalem2020', 'nabian2018']
peak_times_dict = {}

print("-" * 50)

for m in eda_peak_methods:
    try:
        eda_peaks_info = nk.eda_peaks(eda_decomposed["EDA_Phasic"], sampling_rate=nominal_sample_rate, method=m)
        scr_peak_times = eda_peaks_info[1]['SCR_Peaks']
        peak_times_dict[m] = len(scr_peak_times)
        print(f"Method: {m}, N peaks per min: {len(scr_peak_times)/bio_duration_mins}")
    except Exception as e:
        print(f"Method: {m} failed with error: {e}")
        peak_times_dict[m] = None

print("-" * 50)

ecg_raw = biosignals_df['ECG1'].values
ecg_clean_methods = ['neurokit', 'biosppy', 'pantompkins1985', 'hamilton2002', 'elgendi2010', 'engzeemod2012', 'templateconvolution', 'vg']

ecg_cleaned = {}

for i,method in enumerate(ecg_clean_methods):
    ecg_cleaned[method] = nk.ecg_clean(ecg_raw, sampling_rate=nominal_sample_rate, method=method)

# Again defaulting to biosppy for now

peak_info = nk.ecg_findpeaks(ecg_cleaned['biosppy'],nominal_sample_rate,method='neurokit',show=plot_data)

with warnings.catch_warnings():
    
    # TODO: Note nk has several warnings that will hopefully be addressed at update
    warnings.simplefilter("ignore", category=SettingWithCopyWarning)
    warnings.simplefilter("ignore", category=FutureWarning)

    waves,signals = nk.ecg_delineate(ecg_cleaned['biosppy'],
                                    peak_info['ECG_R_Peaks'],
                                    sampling_rate=nominal_sample_rate,
                                    method='peak',
                                    show=plot_data,
                                    show_type='peaks',
                                    check=True)
#display(waves)
tot_q_peak_count = (waves["ECG_Q_Peaks"] == 1).sum()

print(f"Avg Hr per min (Based on Q Peaks): {tot_q_peak_count/bio_duration_mins}")

# Compute HRV

hrv_df = nk.hrv(peak_info,sampling_rate=nominal_sample_rate,show=plot_data)

fig, axs = plt.subplots(1, len(eda_clean_methods), figsize=(12, 4), sharey=True)

if plot_data:

    if len(eda_clean_methods) == 1:
        axs = [axs]

    for i, method in enumerate(eda_clean_methods):
        axs[i].plot(biosignals_df['time_stamps'], eda_cleaned[method], label=f'EDA Cleaned ({method})')
        axs[i].set_title(f'EDA Cleaned - {method}')
        axs[i].set_xlabel('Time (s)')
        axs[i].set_ylabel('Amplitude')
        axs[i].legend()
        plt.tight_layout()
        plt.show()

    # Combine sampling rate, ECG, and EDA into separate subplots of a single figure
    fig, axs = plt.subplots(3, 1, figsize=(12, 10), sharex=True)

    # TODO: Organize output
    # Plot sampling rate over time
    axs[0].plot(biosignals_df['time_stamps'], biosignals_df['sampling_rate'], linestyle='-', marker=None)
    axs[0].set_title('Biosignals Sampling Rate Over Time')
    axs[0].set_ylabel('Sampling Rate (Hz)')
    axs[0].set_ylim(900, 1100)

    # Plot ECG signal over time
    axs[1].plot(biosignals_df['time_stamps'], biosignals_df['ECG1'], label='ECG signal', alpha=0.7)
    axs[1].set_title('Signal Over Time: ECG')
    axs[1].set_ylabel('ECG Signal')
    axs[1].legend()

    # Plot EDA signal over time
    axs[2].plot(biosignals_df['time_stamps'], biosignals_df['EDA0'], label='EDA signal', alpha=0.7)
    axs[2].set_title('Signal Over Time: EDA')
    axs[2].set_xlabel('Time (seconds)')
    axs[2].set_ylabel('EDA Signal')
    axs[2].legend()

    plt.tight_layout()
    plt.show()

# Re doing again TODO: Choose pipeline or look at out DFs Might not be needed even
#print("Reprocessing...")
#ecg_process_df,ecg_info = nk.ecg_process(ecg_raw, sampling_rate=nominal_sample_rate, method='neurokit')

# TODO: Fix ECG plots if needed
#nk.ecg_plot(ecg_process_df)

# VR FOH processing

