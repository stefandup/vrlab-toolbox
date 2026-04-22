import matplotlib.pyplot as plt
import pandas as pd

def calculate_sampling_rate(biosignals_df : pd.DataFrame):
    """Calculate sampling rate mainly to monitor for signal drops."""
    # Calcuate time difference between consecutive samples 
    biosignals_df['time_diff'] = biosignals_df['time_stamps'].diff()

    # Calculate sampling rate (Hz)
    biosignals_df['sampling_rate'] = 1 / biosignals_df['time_diff']

    return biosignals_df

def plot_sampling_rate(biosignals_df : pd.DataFrame):

    # Plot biosignals sampling rate over time
    plt.figure(figsize=(12, 4))
    plt.plot(biosignals_df['time_stamps'], biosignals_df['sampling_rate'], linestyle='-')
    plt.title('Biosignals Sampling Rate Over Time')
    plt.xlabel('Time (s)')
    plt.ylabel('Sampling Rate (Hz)')
    plt.ylim(900, 1100)
    plt.tight_layout()