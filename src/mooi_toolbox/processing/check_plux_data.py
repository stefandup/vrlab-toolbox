import os
import pyxdf
import pandas as pd
from mooi_toolbox.read_mobi_xdf import xdf_io
from rich import print
import matplotlib.pyplot as plt
import neurokit2 as nk
from IPython import display
import sys
import io
import numpy as np

import warnings
from pandas.errors import SettingWithCopyWarning

plot_data = False

def run_eda_processing(nominal_sample_rate,biosignals_df,plot_data=False,data_label=''):

    eda_raw = biosignals_df['EDA0'].values

    if eda_raw is None or eda_raw.size == 0:
        print("No values for this timeframe. Skipping...")
        return 

    bio_duration_mins = (biosignals_df['time_stamps'].max() - biosignals_df['time_stamps'].min()) / 60
    
    print(type(eda_raw))

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
            return
            

    print("-" * 50)

    single_subject_eda_df_out = pd.DataFrame({
        f'{data_label}Tonic_mean': [eda_decomposed['EDA_Tonic'].mean()],
        f'{data_label}SCR_per_min': [peak_times_dict['vanhalem2020'] / bio_duration_mins]
    })

    # TODO: Fix EDA plotting
    if plot_data:
        # Plot all EDA subplots on one figure
        fig, axs = plt.subplots(1, len(eda_clean_methods) + 2, figsize=(20, 4), sharey=True)
        
        # Plot each cleaned EDA signal
        for i, method in enumerate(eda_clean_methods):
            axs[i].plot(biosignals_df['time_stamps'], eda_cleaned[method], label=f'EDA Cleaned ({method})')
            axs[i].set_title(f'EDA Cleaned - {method}')
            axs[i].set_xlabel('Time (s)')
            axs[i].set_ylabel('Amplitude')
            axs[i].legend()
        
        # Plot raw EDA signal and decomposed tonic component in the second-to-last subplot
        axs[-2].plot(biosignals_df['time_stamps'], biosignals_df['EDA0'], label='Raw EDA signal', alpha=0.7)
        axs[-2].plot(biosignals_df['time_stamps'], eda_decomposed['EDA_Tonic'], label='EDA Tonic', alpha=0.7)
        axs[-2].set_title('Signal Over Time: EDA')
        axs[-2].set_xlabel('Time (seconds)')
        axs[-2].set_ylabel('EDA Signal')
        axs[-2].legend()

        # Plot decomposed phasic component in the last subplot
        axs[-1].plot(biosignals_df['time_stamps'], eda_decomposed['EDA_Phasic'], label='EDA Phasic', alpha=0.7, color='orange')
        axs[-1].set_title('EDA Phasic Component')
        axs[-1].set_xlabel('Time (seconds)')
        axs[-1].set_ylabel('EDA Phasic')
        axs[-1].legend()

        plt.tight_layout()
        plt.show()

    return single_subject_eda_df_out

def run_ecg_processing(nominal_sample_rate,biosignals_df,bio_duration_mins,plot_data=False):
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

    if plot_data:
        plt.figure(figsize=(12, 4))
        plt.plot(biosignals_df['time_stamps'], biosignals_df['ECG1'], label='ECG signal', alpha=0.7)
        plt.title('Signal Over Time: ECG')
        plt.xlabel('Time (seconds)')
        plt.ylabel('ECG Signal')
        plt.legend()
        plt.tight_layout()
        plt.show()

def run_target_processing(FOH_target_df,vr_intervals):
    #target_csvdata_df = pd.read_csv(FOH_target_df["FOH_target"])
    lines = FOH_target_df["FOH_target"].dropna().astype(str).tolist()
    #print(f"Header: {lines[0]}")
    #print(f"Fields: {lines[1].split(",")}")

    csv_text = "\n".join(lines)
    #print(csv_text)

    target_csvdata_df = pd.read_csv(io.StringIO(csv_text), header=0)
    # Remove rows where 'FOH_target' is any unwanted header string or is empty
    unwanted_rows = ["TimeSpawned,TimeHit,HitLatency,TargetType", ""]
    filtered_FOH_target_df = FOH_target_df[~FOH_target_df["FOH_target"].isin(unwanted_rows)]
    filtered_FOH_target_df = filtered_FOH_target_df[~FOH_target_df["FOH_target"].isna()]
    filtered_FOH_target_df[["time_stamps"]]

    # Concatenate target_csvdata_df with FOH_target_df["time_stamps"] horizontally

    target_csvdata_df = pd.concat(
        [target_csvdata_df, filtered_FOH_target_df[["time_stamps"]].reset_index(drop=True)],
        axis=1
    )

    print(target_csvdata_df)

    for interval_id,interval in vr_intervals.items():

        if interval_id == "Complete":
            print(f"Skipping {interval_id}")
            continue

        print(f"Trial is {interval_id} if Time Stamp between {interval[0]} and {interval[1]}")

        idx =  (
            (target_csvdata_df["time_stamps"] >= interval[0]) & 
            (target_csvdata_df["time_stamps"] <= interval[1])
            )
        
        target_csvdata_df.loc[idx,"TrialType"] = interval_id

    print(target_csvdata_df)

    # Summarize Target info

    order = ["Short","Medium", "Long"]
    df = target_csvdata_df.copy()

    # Arrange in order
    df["TargetType"] = pd.Categorical(df["TargetType"],categories=order,ordered=True)

    df2 = df.copy()

    # Additional Baseline labels

    Baseline_mask = df2["TrialType"].eq("Baseline")
    df2["Baseline_idx"] = np.nan
    df2.loc[Baseline_mask, "Baseline_idx"] = (
        df2.loc[Baseline_mask].groupby("TargetType").cumcount()
    )

    df2["Baseline_idx"] = df2["Baseline_idx"].astype("Int64")

    # Additional Stress labels

    stress_mask = df2["TrialType"].eq("Stress")
    df2["stress_idx"] = np.nan
    df2.loc[stress_mask, "stress_idx"] = (
        df2.loc[stress_mask].groupby("TargetType").cumcount()
    )

    df2["stress_idx"] = df2["stress_idx"].astype("Int64")

    # start with normal labels
    df2["wide_col"] = df2["TrialType"] + "_" + df2["TargetType"].astype(str) + "_Target"

    # overwrite only Baseline rows
    Baseline_mask = df2["TrialType"].eq("Baseline")
    df2.loc[Baseline_mask, "wide_col"] = (
        "Baseline_"
        + df2.loc[Baseline_mask, "Baseline_idx"].astype("Int64").astype(str)
        + "_"
        + df2.loc[Baseline_mask, "TargetType"].astype(str)
        + "_Target"
    )

    # overwrite only stress rows
    stress_mask = df2["TrialType"].eq("Stress")
    df2.loc[stress_mask, "wide_col"] = (
        "Stress_"
        + df2.loc[stress_mask, "stress_idx"].astype("Int64").astype(str)
        + "_"
        + df2.loc[stress_mask, "TargetType"].astype(str)
        + "_Target"
    )
    print(df2)

    # Wide (single row)
    target_wide = df2.pivot_table(index=None, columns="wide_col", values="HitLatency", aggfunc="first")
    target_data_out = target_wide.reset_index(drop=True)

    return target_data_out
def resolve_xdf_path(argv=None):

    # Get xdf_fn from first command-line argument, if provided

    args = sys.argv[1:] if argv is None else argv

    if len(args) > 0:
        xdf_fn_cli = args[0]
        if not os.path.isabs(xdf_fn_cli):
            # If the path is relative, join it with the current working directory
            xdf_fn = os.path.join(os.getcwd(), xdf_fn_cli)
        else:
            xdf_fn = xdf_fn_cli
    else:
        #xdf_fn_rel = r"local_MOBI_data\\sub-00003\\ses-S001\\philani\\sub-00003_ses-S001_task-Default_run-001_philani.xdf"
        #xdf_fn_rel = r"local_MOBI_data\sub-00007\ses-S001\eeg\sub-00007_ses-S001_task-Default_run-001_eeg.xdf"
        #xdf_fn_rel = r"local_lsl_data\sub-TestZuk\ses-S001\eeg\sub-TestZuk_ses-S001_task-Default_run-001_eeg.xdf"
        #xdf_fn_rel = r"local_lsl_data\sub-TargetTest\ses-S001\eeg\sub-TargetTest_ses-S001_task-Default_run-001_eeg.xdf"
        xdf_fn_rel = r"local_lsl_data\sub-TestTarget2\ses-S001\eeg\sub-TestTarget2_ses-S001_task-Default_run-001_eeg.xdf"

        work_dir = os.getcwd()
        xdf_fn = os.path.join(work_dir,xdf_fn_rel)

    if not os.path.exists(xdf_fn):
        raise ValueError(f"ERROR: {xdf_fn} does not exist")

    return xdf_fn

def main(argv=None):

    xdf_fn = resolve_xdf_path(argv)
    print(f"Loading {xdf_fn}...")
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
    print("[blue]Stream: VR TRIAL EVENTS[/blue]")
    print("-"*40)

    try:
        VR_trial_events_df, VR_trial_events_stream = xdf_io.extract_single_stream(streams, "VR_trial_events")
        # Add column names to the extracted VR_trial_events_df stream
        VR_trial_events_df = xdf_io.add_column_names(VR_trial_events_df, VR_trial_events_stream)
        print(VR_trial_events_df.head(5))
    except Exception as e:
        raise ValueError("Failed to extract the 'VR_trial_events' stream from XDF data.") from e

    try:
        vr_markers_df, vr_markers_stream = xdf_io.extract_single_stream(streams, 'VR_markers')
        vr_markers_df = xdf_io.add_column_names(vr_markers_df, vr_markers_stream)

        print(vr_markers_df.head(5))

    except Exception as e:
        raise ValueError("Failed to extract the 'VR_markers' stream from XDF data.") from e

    # Extract Main markers

    vr_total_time_mins = (vr_markers_df["time_stamps"].max() - vr_markers_df["time_stamps"].min())/60
    vr_start_time = vr_markers_df["time_stamps"].min()
    vr_end_time = vr_markers_df["time_stamps"].max()
    print(f"Loaded VR marker stream with {len(vr_markers_df)} events spanning {vr_total_time_mins:.2f} minutes. (Start: {vr_start_time}, End: {vr_end_time})")

    print(f"VR task started at: {vr_start_time}")
    print(f"VR tasks ended at {vr_end_time}")

    # Create list of start/end times
    vr_intervals = {}

    vr_intervals.update({"Complete" : (vr_start_time,vr_end_time)})

    # Extract exact timing data

    RaiseSafetyPlatform_time = VR_trial_events_df["time_stamps"][VR_trial_events_df["VR_trial"] == "RaiseSafetyPlatform"].iloc[0]
    baseline_duration_min = (RaiseSafetyPlatform_time - vr_start_time) / 60
    print(f"Baseline: {vr_start_time} to {RaiseSafetyPlatform_time} (Duration: {baseline_duration_min:.2f} minutes)")

    vr_intervals.update({"Baseline" : (vr_start_time,RaiseSafetyPlatform_time)})

    RaiseMainPlatform_time = VR_trial_events_df["time_stamps"][VR_trial_events_df["VR_trial"] == "RaiseMainPlatform"].iloc[0]
    MainPlatformLowering_time = VR_trial_events_df["time_stamps"][VR_trial_events_df["VR_trial"] == "MainPlatformLowering"].iloc[0]
    stress_duration_min = (MainPlatformLowering_time - RaiseMainPlatform_time) / 60
    print(f"Stress: {RaiseMainPlatform_time} to {MainPlatformLowering_time} (Duration: {stress_duration_min:.2f} minutes)")

    vr_intervals.update({"Stress" : (RaiseMainPlatform_time,MainPlatformLowering_time)})

    LastDoSTDQuestions_time = VR_trial_events_df["time_stamps"][VR_trial_events_df["VR_trial"] == "DoSTDQuestions"].iloc[-1]
    RunFOHQuestions_time = VR_trial_events_df["time_stamps"][VR_trial_events_df["VR_trial"] == "RunFOHQuestions"].iloc[0]

    recovery_duration_min = (RunFOHQuestions_time - LastDoSTDQuestions_time) / 60
    print(f"Recovery: {LastDoSTDQuestions_time} to {RunFOHQuestions_time} (Duration: {recovery_duration_min:.2f} minutes)")

    vr_intervals.update({"Recovery" : (LastDoSTDQuestions_time,RunFOHQuestions_time)})

    out_data_frames = []

    print("-"*40)
    print("[blue]Stream: BIOSIGNALS[/blue]")
    print("-"*40)

    try:
        biosignals_df, biosignals_stream = xdf_io.extract_single_stream(streams, 'OpenSignals')
        biosignals_df = xdf_io.add_column_names(biosignals_df, biosignals_stream)
        print(biosignals_df.head(5))
    except Exception as e:
        print("No opensignals data found. Skipping...")

    if biosignals_df is not None and not biosignals_df.empty:

        biosignal_intervals = {}

        for key,start_end in vr_intervals.items():
            print(f"Interval {key}: {start_end}. Data type: {type(start_end)}")
            biosignal_intervals.update({f"{key}" : xdf_io.cut_df_per_interval(start_end,biosignals_df)})
            #biosignal_interval_dfs.append(xdf_io.cut_df_per_interval(interval,biosignals_df))

        biosignals_df = biosignal_intervals["Complete"]

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

        if plot_data:

            # Plot biosignals sampling rate over time
            plt.figure(figsize=(12, 4))
            plt.plot(biosignals_df['time_stamps'], biosignals_df['sampling_rate'], linestyle='-')
            plt.title('Biosignals Sampling Rate Over Time')
            plt.xlabel('Time (s)')
            plt.ylabel('Sampling Rate (Hz)')
            plt.ylim(900, 1100)
            plt.tight_layout()
            plt.show()

        nominal_sample_rate=float(biosignals_stream['info']['nominal_srate'][0])

        if 'EDA0' in biosignals_df.columns:
            eda_df_out = pd.DataFrame()

            eda_parts = []
            for key, dataframe in biosignal_intervals.items():
                eda_part = run_eda_processing(nominal_sample_rate, dataframe, plot_data=False, data_label=f'{key}_')
                eda_parts.append(eda_part)

            eda_df_out = pd.concat(eda_parts, axis=1)

            if plot_data:

                print(eda_df_out['Baseline_SCR_per_min'])
                plt.bar(["Baseline", "Stress", "Recovery"],
                        [eda_df_out['Baseline_SCR_per_min'][0],
                        eda_df_out['Stress_SCR_per_min'][0],
                        eda_df_out['Recovery_SCR_per_min'][0]])
                plt.xlabel("Timepoints")
                plt.ylabel("SCR per min")
                plt.title("FOH EDA")
                plt.tight_layout()
                plt.show()

            print(eda_df_out)
            out_data_frames.append(eda_df_out)

    # Only run ECG processing if ECG data is present in biosignals_df
        if 'ECG1' in biosignals_df.columns:
            run_ecg_processing(nominal_sample_rate, biosignals_df,bio_duration_mins, plot_data=plot_data)
        else:
            print("No ECG data found in biosignals_df. Skipping ECG processing.")

        #TODO: Add ECG out DF

    print("-"*40)
    print("[blue]Stream: VR TRIAL EVENTS[/blue]")
    print("-"*40)

    # Behavioural data:

    print("-"*40)
    print("Stream: FOH_targets")
    print("-"*40)
    FOH_target_df, FOH_target = xdf_io.extract_single_stream(streams, "FOH_target")
    FOH_target_df = xdf_io.add_column_names(FOH_target_df, FOH_target)
    print(FOH_target_df)
    print("-"*40)

    target_data_out = run_target_processing(FOH_target_df,vr_intervals)
    out_data_frames.append(target_data_out)

    participant_out_df = pd.concat(out_data_frames,axis=1)

    #participant_out_df["Subject_ID"] =

    print(participant_out_df)
    
    return participant_out_df

if __name__ == "__main__":

    main()