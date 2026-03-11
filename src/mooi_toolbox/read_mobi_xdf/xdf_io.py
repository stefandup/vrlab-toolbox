import pandas as pd
import numpy as np

def print_column_names(stream):
        channels = stream['info']['desc'][0]['channels'][0]['channel']
        column_names = [channel['label'][0] for channel in channels]
        print(f"Column Names for: {column_names}")

def extract_single_stream(streams, stream_name):
    """Extract the time series and time stamps from a specified stream in xdf data."""
    for s in streams:
        if s['info']['name'][0] == stream_name:
            single_stream = s
            single_stream_time_series = np.array(single_stream['time_series'])
            # print("sample time series:", single_stream_time_series[:5])
            single_stream_time_stamps = np.array(single_stream['time_stamps'])
            # print("sample time stamps:", single_stream_time_stamps[:5])

            # Make dataframe
            single_stream_df = pd.DataFrame(single_stream_time_series)
            # Add timestamps
            single_stream_df["time_stamps"] = single_stream_time_stamps
    return single_stream_df, single_stream

def add_column_names(single_stream_df, single_stream):
    """Add column names to the single stream dataframes."""
    
    # Check if channel description exists and is valid
    try:
        if (single_stream['info']['desc'][0] is not None and 
            'channels' in single_stream['info']['desc'][0]):
            
            channels = single_stream['info']['desc'][0]['channels'][0]['channel']
            column_names = [channel['label'][0] for channel in channels]
            print('Column names from metadata:', column_names)
            
        else:
            raise KeyError("No valid channel description")
            
    except (KeyError, TypeError, IndexError):
        # Create column names if they aren't provided 
        channel_count = int(single_stream['info']['channel_count'][0])
        stream_name = single_stream['info']['name'][0]
        column_names = [f"{stream_name}_ch{i+1}" for i in range(channel_count)]
        print(f'Channel labels not available for {stream_name}. Using generic names:', column_names)

    # Apply the column names
    num_cols = len(column_names)
    single_stream_df.columns = column_names + list(single_stream_df.columns[num_cols:])

    return single_stream_df