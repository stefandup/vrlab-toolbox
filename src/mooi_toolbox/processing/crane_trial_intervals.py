import logging
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.biopac import BiopacDataImportStartegy
from mooi_toolbox.processing.crane_behaviour import (
    ImportCraneBehaviourDataStrategyStep,
    RawCraneBehaviourData,
)
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals, get_raw_biopac_trigger_intervals

logger = logging.getLogger(__name__)
EXPECTED_INTERVAL_NR = 23


class CraneGetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawCraneBehaviourData] = RawCraneBehaviourData

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawCraneBehaviourData
    ) -> tuple[TrialIntervals, PipelineStatus]:

        interval_pipeline_status = PipelineStatus()

        raw_biopac_triggers = get_raw_biopac_trigger_intervals(raw_biodata_in["Trigger"])

        if len(raw_biopac_triggers.intervals) != EXPECTED_INTERVAL_NR:
            logger.warning(
                "Interval count is %d and not %d for subject.",
                len(raw_biopac_triggers.intervals),
                EXPECTED_INTERVAL_NR,
            )
            interval_pipeline_status = interval_pipeline_status.merge(
                PipelineStatus(intervals=ProcessingStatus.ERROR)
            )

        corrected_triggers, corrected_status = remove_crane_known_false_triggers(
            raw_biopac_triggers
        )
        interval_pipeline_status = interval_pipeline_status.merge(
            PipelineStatus(intervals=corrected_status)
        )
        matched_triggers, match_status = match_crane_behav_intervals_with_trigger_intervals(
            corrected_triggers, raw_behaviour_data_in.raw_behav_df
        )
        interval_pipeline_status = interval_pipeline_status.merge(
            PipelineStatus(intervals=match_status)
        )

        return (matched_triggers, interval_pipeline_status)


def remove_crane_known_false_triggers(
    trigger_intervals_to_check: TrialIntervals,
) -> tuple[TrialIntervals, ProcessingStatus]:
    # TODO: Improve! This needs to update with partial
    # [start_end[1] - start_end[0] for start_end in trigger_interval_pairs]
    if not trigger_intervals_to_check.intervals:
        return (trigger_intervals_to_check, ProcessingStatus.ERROR)

    trigger_interval_pairs = list(trigger_intervals_to_check.intervals.values())

    tolerance = 0.1
    valid_trigger_interval_pairs = []

    status_out = ProcessingStatus.OK
    for pair_nr, (start_time, end_time) in enumerate(trigger_interval_pairs):
        if pair_nr == 0 and np.isclose(start_time, 0.0, atol=tolerance):
            logger.warning(
                "Removed first interval because its start is likely a false start: %s",
                start_time,
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        if np.isclose(end_time - start_time, 0.0, atol=tolerance):
            logger.warning(
                "Removed interval %.3f to %.3f because its duration is close to zero",
                start_time,
                end_time,
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        if end_time - start_time < 10.0:
            logger.warning(
                "Removed interval %.3f to %.3f because its duration is too short: %.3f (s)",
                start_time,
                end_time,
                end_time - start_time,
            )
            status_out = ProcessingStatus.CORRECTED
            continue

        valid_trigger_interval_pairs.append((start_time, end_time))

    valid_trigger_interval_pairs = TrialIntervals.from_raw_interval_pairs(
        valid_trigger_interval_pairs
    )

    return (valid_trigger_interval_pairs, status_out)


def get_crane_trigger_behav_intervals(
    validated_behav_df: pd.DataFrame,
) -> dict[str, tuple[float, float]]:
    # TODO: Needs to be generalized
    intervals_out = {}

    for _, row in validated_behav_df.iterrows():
        if row["Training"]:
            intervals_out.update(
                {
                    f"{row['BlockType']}_{row['TrialType']}_{row['TrialNr']}_Training": tuple(
                        [row["TrialStartTime"], row["TrialEndTime"]]
                    )
                }
            )
        else:
            intervals_out.update(
                {
                    f"{row['BlockType']}_{row['TrialType']}_{row['TrialNr']}": tuple(
                        [row["TrialStartTime"], row["TrialEndTime"]]
                    )
                }
            )

    return intervals_out


def get_crane_predicted_trigger_intervals(
    behav_intervals: dict[str, tuple[float, float]],
) -> tuple[dict[str, tuple[float, float]], float]:
    # TODO Still very patchy and specific to the crane game
    base = getattr(sys, "_MEIPASS", ".")  # Is this frozen exe bin or running from source
    reference_path = os.path.join(base, "references", "matched_debug_df_testa.parquet")
    reference_df = pd.read_parquet(reference_path)

    # Control for the relative start difference.
    X = (
        reference_df["behav_start"].loc[1 : len(behav_intervals)]
        - reference_df["behav_start"].iloc[0]
    ).values.reshape(-1, 1)
    y = (
        reference_df["trigger_start"].loc[1 : len(behav_intervals)]
        - reference_df["trigger_start"].iloc[0]
    ).values.reshape(-1, 1)

    model = make_pipeline(PolynomialFeatures(degree=2, include_bias=False), LinearRegression())

    model.fit(X, y)
    newX = np.array([start_end_time[0] for start_end_time in behav_intervals.values()]).reshape(
        -1, 1
    )
    newX_rel = newX - newX[0]
    mean_trial_len = np.mean(
        [start_end_times[1] - start_end_times[0] for start_end_times in behav_intervals.values()]
    )
    train_pred_y = model.predict(X)
    absolute_errors = np.abs(np.ravel(y) - np.ravel(train_pred_y))
    max_expected_delta = np.percentile(absolute_errors, 95) * 10

    pred_trigger_y = model.predict(newX_rel)

    pred_trigger_intervals = {
        key: (pred_trigger_y[nr].item(), pred_trigger_y[nr].item() + mean_trial_len)
        for nr, key in enumerate(behav_intervals.keys())
    }
    return (pred_trigger_intervals, max_expected_delta)


def match_crane_behav_intervals_with_trigger_intervals(
    trial_intervals_in: TrialIntervals, validated_behav_df: pd.DataFrame
) -> tuple[TrialIntervals, ProcessingStatus]:
    # TODO: Make more robust
    trigger_intervals = trial_intervals_in.intervals
    behav_intervals = get_crane_trigger_behav_intervals(validated_behav_df)
    pred_trigger_intervals, max_expected_delta = get_crane_predicted_trigger_intervals(
        behav_intervals
    )
    status = ProcessingStatus.OK
    experiment_start = next(iter(trigger_intervals.values()))[0]  # Get first value of dict

    remaining_trigger_intervals = trigger_intervals.copy()
    matched_intervals = {}
    unmatched_behav_keys = set(behav_intervals.keys())
    max_start_delta = max_expected_delta
    best_deltas = []

    for pred_key, pred_start_end in pred_trigger_intervals.items():
        rel_pred_start = pred_start_end[0]
        best_trigger_key = None
        best_delta = float("inf")

        for trigger_interval_key, trigger_start_end in remaining_trigger_intervals.items():
            rel_trigger_start = trigger_start_end[0] - experiment_start
            delta = abs(rel_pred_start - rel_trigger_start)

            if delta < best_delta:
                best_trigger_key = trigger_interval_key
                best_delta = delta
                best_deltas.append(best_delta)

        if best_trigger_key is None:
            continue

        if best_delta > max_start_delta:
            logger.warning(
                "Max delta exceeded for trigger %s. Delta: %s", best_trigger_key, best_delta
            )

        unmatched_behav_keys.remove(pred_key)
        matched_intervals[pred_key] = remaining_trigger_intervals.pop(best_trigger_key)

        # print(f"Selected: {best_trigger_key}. Best delta: {best_delta}. Matched {pred_key}")

    if len(unmatched_behav_keys) != 0:
        logger.warning("Could not match %s", unmatched_behav_keys)
        logger.debug("Best deltas where: %s", best_deltas)
        status = ProcessingStatus.ERROR

    matched_trial_intervals_out = TrialIntervals(intervals=matched_intervals)

    return (matched_trial_intervals_out, status)


# QC


def run_crane_interval_qc(config_in: ParticipantConfig) -> None:
    try:
        raw_bio_data = BiopacDataImportStartegy().run(config_in)
    except (FileNotFoundError, ValueError) as e:
        logger.error(
            "Couldnt find Biopac data for %s at %s. %s",
            config_in.subject_id,
            config_in.physiology_fn,
            e,
        )
        return

    try:
        raw_behav_data = ImportCraneBehaviourDataStrategyStep().run(config_in)
    except (FileNotFoundError, ValueError) as e:
        logger.warning(
            "Problem with behaviour file for %s. Trying to continue. Error: %s",
            config_in.subject_id,
            e,
        )
        raw_behav_data = None

    try:
        raw_biopac_trigger_intervals = get_raw_biopac_trigger_intervals(raw_bio_data["Trigger"])
    except (FileNotFoundError, ValueError) as e:
        logger.error(
            "Trouble importing trigger data from physiology for %s. Have to skip. %s",
            config_in.subject_id,
            e,
        )
        raw_biopac_trigger_intervals = TrialIntervals(intervals={})

    try:
        corrected_trigger_intervals, corrected_status = remove_crane_known_false_triggers(
            raw_biopac_trigger_intervals
        )
    except (FileNotFoundError, ValueError) as e:
        logger.warning(
            "Error removing false triggers for %s. Trying to continue. %s", config_in.subject_id, e
        )
        corrected_trigger_intervals = TrialIntervals(intervals={})

    if raw_behav_data is None:
        behav_matched_trigger_intervals = TrialIntervals(intervals={})
        raw_behav_interval_validated = TrialIntervals(intervals={})
    else:
        try:
            behav_matched_trigger_intervals, _ = match_crane_behav_intervals_with_trigger_intervals(
                corrected_trigger_intervals, raw_behav_data.raw_behav_df
            )
        except (FileNotFoundError, ValueError) as e:
            logger.warning(
                "Could not match behaviour to triggers for %s. Trying to continue. %s",
                config_in.subject_id,
                e,
            )
            behav_matched_trigger_intervals = TrialIntervals(intervals={})

        try:
            # TODO: Fix that this works with TrialIntervals class. Change througout!
            raw_behav_intervals = get_crane_trigger_behav_intervals(raw_behav_data.raw_behav_df)
            raw_behav_interval_validated = TrialIntervals(intervals=raw_behav_intervals)
        except (FileNotFoundError, ValueError) as e:
            logger.warning(
                "Could not get raw behav intervals for %s. Trying to continue. %s",
                config_in.subject_id,
                e,
            )
            raw_behav_interval_validated = TrialIntervals(intervals={})

    time_stamp_series = raw_bio_data.raw_data["Trigger"]["time_stamps"]
    fig, axes = plt.subplots(
        4,
        1,
        sharex=True,
        figsize=(19.2, 10.8),
        dpi=300,
        gridspec_kw={"height_ratios": [1, 2, 2, 2]},
    )
    axes[0].set_xlim(0, 25)

    # Row 0: raw trigger voltage signal
    trigger_time_stamps, trigger_signal = get_raw_trigger_signal(raw_bio_data["Trigger"])
    trigger_time_min = (trigger_time_stamps - time_stamp_series.iloc[0]) / 60
    axes[0].plot(trigger_time_min, trigger_signal, color="black", linewidth=0.5)
    axes[0].set_title("Raw Trigger Voltage")
    # TODO: Flag points where voltage drops below ~4.8V (Arduino signal instability)

    # Row 1: raw biopac vs raw behav, unprocessed baseline
    plot_interval_ax(
        axes[1],
        raw_biopac_trigger_intervals,
        time_stamp_series,
        color_nr=0,
        title="Raw",
        source_label="Raw biopac",
    )
    plot_interval_ax(
        axes[1],
        raw_behav_interval_validated,
        time_stamp_series,
        color_nr=1,
        source_label="Raw behav",
        show_gaps=True,
    )

    # Row 2: same baseline, with corrected trigger intervals overlaid to show the shift
    plot_interval_ax(
        axes[2],
        raw_biopac_trigger_intervals,
        time_stamp_series,
        color_nr=0,
        title="Corrected",
        source_label="Raw biopac",
    )
    plot_interval_ax(
        axes[2],
        raw_behav_interval_validated,
        time_stamp_series,
        color_nr=1,
        source_label="Raw behav",
        show_gaps=True,
    )
    plot_interval_ax(
        axes[2],
        corrected_trigger_intervals,
        time_stamp_series,
        color_nr=2,
        source_label="Shrt Trigs Rmoved",
    )

    # Row 3: final matched trigger intervals, labeled by behaviour key
    plot_interval_ax(
        axes[3],
        behav_matched_trigger_intervals,
        time_stamp_series,
        color_nr=3,
        title="Matched with Behav",
        source_label="Matched with Behav",
        show_gaps=True,
    )

    fig.suptitle(config_in.subject_id)
    out_dir = Path(config_in.behav_folder) / "interval_qc"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{config_in.subject_id}_interval_qc.png"
    fig.savefig(out_path)
    plt.close(fig)


def plot_interval_ax(
    axis_in,
    trial_intervals_in: TrialIntervals,
    time_stamp_series: pd.Series,
    color_nr: int,
    title: str | None = None,
    source_label: str | None = None,
    show_gaps: bool = False,
):

    if title is not None:
        axis_in.set_title(title)

    trial_intervals = trial_intervals_in.intervals

    if trial_intervals:
        color = f"C{color_nr % 10}"  # cycle through matplotlib default colors
        y0 = color_nr * 1.2  # each color gets its own horizontal lane
        height = 1
        bars = []

        for interval_name, (interval_start, interval_end) in trial_intervals.items():
            interval_start_min = (interval_start - time_stamp_series.iloc[0]) / 60
            interval_end_min = (interval_end - time_stamp_series.iloc[0]) / 60
            bars.append((interval_start_min, interval_end_min - interval_start_min))

            label_text = (
                interval_name.replace("_", "\n") if len(interval_name) > 5 else interval_name
            )
            duration_seconds = interval_end - interval_start

            # One label per interval, centered on its own bar
            axis_in.text(
                (interval_start_min + interval_end_min) / 2,
                y0 + height / 2,
                label_text,
                color="black",
                fontweight="bold",
                va="center",
                ha="center",
                fontsize=8,
            )

            # Trial length in seconds, pinned to the bottom of the bar
            axis_in.text(
                (interval_start_min + interval_end_min) / 2,
                y0,
                f"{duration_seconds:.1f}s",
                color="black",
                va="bottom",
                ha="center",
                fontsize=6,
            )

        # One bar per interval, spanning its start to end
        axis_in.broken_barh(bars, (y0, height), color=color, alpha=0.8, label=source_label)

        if source_label is not None:
            axis_in.legend(loc="upper right", fontsize=7)

        if show_gaps:
            sorted_intervals = sorted(trial_intervals.values())
            for (_, prev_end), (next_start, _) in zip(
                sorted_intervals, sorted_intervals[1:], strict=False
            ):
                gap_seconds = next_start - prev_end
                gap_start_min = (prev_end - time_stamp_series.iloc[0]) / 60
                gap_end_min = (next_start - time_stamp_series.iloc[0]) / 60

                # Gap between consecutive intervals, pinned to the bottom
                axis_in.text(
                    (gap_start_min + gap_end_min) / 2,
                    y0,
                    f"{gap_seconds:.1f}s",
                    color="dimgray",
                    va="bottom",
                    ha="center",
                    fontsize=6,
                )


def get_raw_trigger_signal(raw_trigger_data: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Extracts the raw trigger voltage signal and its timestamps, ready for plotting."""
    time_stamps = raw_trigger_data["time_stamps"]
    trigger_signal = raw_trigger_data["Trigger"]

    return time_stamps, trigger_signal
