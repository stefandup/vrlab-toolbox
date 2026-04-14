
def calculate_sampling_rate(biosignals_df):
    
    # Calcuate time difference between consecutive samples 
    biosignals_df['time_diff'] = biosignals_df['time_stamps'].diff()

    # Calculate sampling rate (Hz)
    biosignals_df['sampling_rate'] = 1 / biosignals_df['time_diff']

    return biosignals_df