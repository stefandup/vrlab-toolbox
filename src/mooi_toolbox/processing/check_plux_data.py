import os
import pyxdf
from mooi_toolbox.read_mobi_xdf import xdf_io
from rich import print
import matplotlib.pyplot as plt
import neurokit2 as nk

example_data = r"local_MOBI_data\\sub-00003\\ses-S001\\philani\\sub-00003_ses-S001_task-Default_run-001_philani.xdf"
work_dir = os.getcwd()


example_data_fn = os.path.join(work_dir,example_data)

if not os.path.exists(example_data):
    print(f"ERROR: {example_data} does not exist")

streams, header = pyxdf.load_xdf(example_data_fn)

# Print information about the streams
print("-" * 40)
for stream in streams:
    print(f"Stream Name: {stream['info']['name'][0]}")
    print(f"Stream Type: {stream['info']['type'][0]}")
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
biosignals_df, biosignals_stream = xdf_io.extract_single_stream(streams, 'OpenSignals')
biosignals_df = xdf_io.add_column_names(biosignals_df, biosignals_stream)
print(biosignals_df.head(5))


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
bio_duration = (biosignals_df['time_stamps'].max() - biosignals_df['time_stamps'].min()) / 60
print(f"Duration of Biosignals Data: {bio_duration} mins")

print("-"*40)

# Plot sampling rate over time as a line graph
plt.figure()
plt.plot(biosignals_df['time_stamps'], biosignals_df['sampling_rate'], linestyle='-', marker=None)
plt.title('Biosignals Sampling Rate Over Time')
plt.ylabel('Sampling Rate (Hz)')
plt.xlabel('Time (seconds)')
plt.ylim(900, 1100)
plt.show()

# ECG
plt.figure(figsize=(10, 4))
plt.plot(biosignals_df['time_stamps'], biosignals_df['ECG1'], label='signals', alpha=0.7)
plt.title('Signal Over Time: ECG')
plt.xlabel('Time Stamps')
plt.ylabel('Signal')
plt.legend()
plt.show()

# EDA
plt.figure(figsize=(10, 4))
plt.plot(biosignals_df['time_stamps'], biosignals_df['EDA0'], label='signals', alpha=0.7)
plt.title('Signal Over Time: EDA')
plt.xlabel('Time Stamps')
plt.ylabel('Signal')
plt.legend()
plt.show()

eda_raw = biosignals_df['EDA0'].values
eda_clean_methods = ['biosppy', 'neurokit']

fig, axs = plt.subplots(1, len(eda_clean_methods), figsize=(12, 4), sharey=True)

if len(eda_clean_methods) == 1:
    axs = [axs]
eda_cleaned = {}
for i, method in enumerate(eda_clean_methods):
    eda_cleaned[method] = nk.eda_clean(eda_raw, sampling_rate=biosignals_df['sampling_rate'].mean(), method=method)
    axs[i].plot(biosignals_df['time_stamps'], eda_cleaned[method], label=f'EDA Cleaned ({method})')
    axs[i].set_title(f'EDA Cleaned - {method}')
    axs[i].set_xlabel('Time (s)')
    axs[i].set_ylabel('Amplitude')
    axs[i].legend()
plt.tight_layout()
plt.show()


eda_decomposed = nk.eda_phasic(eda_cleaned['biosppy'], sampling_rate=biosignals_df['sampling_rate'].mean())
    
eda_peak_methods = ['neurokit', 'gamboa2008', 'kim2004', 'vanhalem2020', 'nabian2018']
peak_times_dict = {}

print("-" * 50)

for m in eda_peak_methods:
    try:
        eda_peaks_info = nk.eda_peaks(eda_decomposed["EDA_Phasic"], sampling_rate=biosignals_df['sampling_rate'].mean(), method=m)
        scr_peak_times = eda_peaks_info[1]['SCR_Peaks']
        peak_times_dict[m] = len(scr_peak_times)
        print(f"Method: {m}, N peaks per min: {len(scr_peak_times)/bio_duration}")
    except Exception as e:
        print(f"Method: {m} failed with error: {e}")
        peak_times_dict[m] = None

print("-" * 50)