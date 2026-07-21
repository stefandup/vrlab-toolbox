import logging
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from mooi_toolbox.processing.biopac import BiopacDataImportStartegy
from mooi_toolbox.processing.crane_behaviour import ImportCraneBehaviourDataStrategyStep
from mooi_toolbox.processing.crane_trial_intervals import (
    TrialIntervals,
    get_crane_trigger_behav_intervals,
    get_raw_biopac_trigger_intervals,
    match_crane_behav_intervals_with_trigger_intervals,
    remove_crane_known_false_triggers,
)
from mooi_toolbox.processing.input_data import ParticipantConfig

logger = logging.getLogger(__name__)
# TODO: Shouldnt this rather live in crane_trial_intervals?


def run(config_in: ParticipantConfig) -> None:
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
    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(19.2, 10.8), dpi=300)
    axes[0].set_xlim(0, 25)

    # Row 1: raw biopac vs raw behav, unprocessed baseline
    plot_interval_ax(
        axes[0],
        raw_biopac_trigger_intervals,
        time_stamp_series,
        color_nr=0,
        title="Raw",
        source_label="Raw biopac",
    )
    plot_interval_ax(
        axes[0],
        raw_behav_interval_validated,
        time_stamp_series,
        color_nr=1,
        source_label="Raw behav",
    )

    # Row 2: same baseline, with corrected trigger intervals overlaid to show the shift
    plot_interval_ax(
        axes[1],
        raw_biopac_trigger_intervals,
        time_stamp_series,
        color_nr=0,
        title="Corrected",
        source_label="Raw biopac",
    )
    plot_interval_ax(
        axes[1],
        raw_behav_interval_validated,
        time_stamp_series,
        color_nr=1,
        source_label="Raw behav",
    )
    plot_interval_ax(
        axes[1],
        corrected_trigger_intervals,
        time_stamp_series,
        color_nr=2,
        source_label="Shrt Trigs Rmoved",
    )

    # Row 3: final matched trigger intervals, labeled by behaviour key
    plot_interval_ax(
        axes[2],
        behav_matched_trigger_intervals,
        time_stamp_series,
        color_nr=3,
        title="Matched with Behav",
        source_label="Matched with Behav",
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
