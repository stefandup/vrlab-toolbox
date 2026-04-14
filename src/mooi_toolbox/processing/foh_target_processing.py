import pandas as pd
import io
import numpy as np

def run_processing(FOH_target_df,vr_intervals):
    # TODO: Now with changes not picking up the other conditions except Baseline...
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

    return target_data_out, df2