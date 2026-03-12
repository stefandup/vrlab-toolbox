import pandas as pd
import numpy as np

def create_intervals_from_df(marker_df): 
    return [(marker_df["time_stamps"].iloc[i], marker_df["time_stamps"].iloc[i + 1])
    for i in range(len(marker_df) - 1)]

def cut_df_per_interval(start_end_in: tuple,df_in):
    start, end = start_end_in

    mask = (df_in["time_stamps"] >= start) & (df_in["time_stamps"] <= end)

    return df_in.loc[mask]

def divide_df_into_blocks(time_in_seconds,df_in):
    df_list_out = []
    t_min = df_in["time_stamps"].min()
    t_max = df_in["time_stamps"].max()

    time_markers = np.arange(t_min,t_max,time_in_seconds)

    for i in range(len(time_markers)):
        start = time_markers[i]
        end = time_markers[i + 1] if i + 1 < len(time_markers) else t_max
        mask = (df_in["time_stamps"] >= start) & (df_in["time_stamps"] <= end)
        df_list_out.append(df_in.loc[mask])
    
    return df_list_out

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