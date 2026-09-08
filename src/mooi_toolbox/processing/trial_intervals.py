import logging
import math
from dataclasses import dataclass, field

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from typing_extensions import deprecated

from mooi_toolbox import config as cfg
from mooi_toolbox.processing import lsl
from mooi_toolbox.processing.input_data import PhysiologyFileFormat
from mooi_toolbox.processing.lsl import LslEventSpecification
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus

logger = logging.getLogger(__name__)
UNREAL_START_DELAY_SECONDS = 5
START_TOLERANCE_SECONDS = 5


# TODO: Look into using types.MappingProxyType to guard the sorted nature of "intervals"
# TODO: Add Dunder overrides to simplify
@dataclass
class TrialIntervals:
    """
    Trial intervals are named time periods in the experiment at the subject level, encoded
    as (start, end) time pairs keyed by a str name.

    For example:
    "Baseline": (0, 5) — the "Baseline" trial spans from 0 to 5 seconds.
    """

    intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
    physiology_file_format: PhysiologyFileFormat | None = None

    def __post_init__(self):
        self.sort()

    def sort(self):
        self.intervals = dict(sorted(self.intervals.items(), key=lambda item: item[1]))

    def fill_in_gaps(self) -> "TrialIntervals":

        gap_filled_intervals = self.intervals.copy()
        sorted_interval_values = sorted(self.intervals.values())

        if not math.isclose(
            sorted_interval_values[0][0],
            0,
            abs_tol=START_TOLERANCE_SECONDS + UNREAL_START_DELAY_SECONDS,
        ):
            sorted_interval_values.insert(0, (0, 0))
        counter = 0
        for (_, prev_end), (next_start, _) in zip(
            sorted_interval_values, sorted_interval_values[1:], strict=False
        ):
            if next_start > prev_end:
                gap_filled_intervals.update({f"ITI_{counter}": (prev_end, next_start)})
                counter = counter + 1

        return TrialIntervals(
            intervals=gap_filled_intervals, physiology_file_format=self.physiology_file_format
        )

    def relabel_with_intervals(self, other: "TrialIntervals") -> "TrialIntervals":
        relabelled_trial_intervals = self.intervals.copy()

        if not isinstance(other, TrialIntervals):
            raise ValueError("Cannot relabel of non TrialInterval class")

        if len(self) != len(other):
            raise ValueError("Cannot relabel when the other set of intervals is not the same size.")

        other_intervals_sorted = dict(sorted(other.intervals.items(), key=lambda item: item[1]))

        for other_item_key, self_item_key in zip(
            other_intervals_sorted.keys(), self.intervals.keys(), strict=False
        ):
            relabelled_trial_intervals[other_item_key] = relabelled_trial_intervals.pop(
                self_item_key
            )

        relabelled_intervals_out = TrialIntervals(
            intervals=relabelled_trial_intervals, physiology_file_format=self.physiology_file_format
        )

        return relabelled_intervals_out

    def get_overlap(self, other) -> list[float]:
        if not isinstance(other, TrialIntervals):
            raise ValueError("Cannot get overlap of non TrialInterval class")

        if len(self.intervals) != len(other.intervals):
            raise ValueError(
                "Cannot get overlap when the other set of intervals is not the same size."
            )

        deltas = []
        for other_vals, self_vals in zip(
            other.intervals.values(),
            self.intervals.values(),
            strict=False,
        ):
            other_duration = other_vals[1] - other_vals[0]
            self_duration = self_vals[1] - self_vals[0]
            deltas.append(self_duration - other_duration)

        return deltas

    def shift_intervals_forward_by(self, nr_of_steps: int):
        padding = dict(
            [(f"ITI{nr}", (float("nan"), float("nan"))) for nr in range(0, nr_of_steps, 1)]
        )

        self.intervals = {**padding, **self.intervals}

    def drop_nan_intervals(self):
        self.intervals = {
            key: interval
            for key, interval in self.intervals.items()
            if not any(math.isnan(t) for t in interval)
        }

    @classmethod
    def from_raw_interval_pairs(
        cls,
        trial_interval_pairs: list[tuple[float, float]],
        physiology_file_format_in: PhysiologyFileFormat | None = None,
    ) -> "TrialIntervals":
        return cls(
            intervals={
                f"TP{i}": (float(start), float(end))
                for i, (start, end) in enumerate(trial_interval_pairs)
            },
            physiology_file_format=physiology_file_format_in,
        )

    def __len__(self):
        return len(self.intervals)


# LSL interval concerns


def get_lsl_event_time(xdf_df_in: pd.DataFrame, col_id: str, event_id: str | int) -> float:
    """Takes xdf marker streams in and extracts timestaps based on predefined markers.
    See pyproject.toml for event definitions"""
    try:
        matches = xdf_df_in["time_stamps"][xdf_df_in[col_id] == event_id]
    except KeyError as e:
        raise ValueError(f"Error in finding {event_id}") from e
    if matches.empty:
        raise ValueError(f"Can not find {col_id} with id {event_id}")

    return float(matches.iloc[0])


def get_lsl_event_time_from_spec(
    event_sources: dict[str, pd.DataFrame], event_spec: LslEventSpecification
) -> float:
    event_time = get_lsl_event_time(
        event_sources[event_spec.stream],
        event_spec.column,
        event_spec.event,
    )

    return event_time + event_spec.offset_seconds


def get_lsl_event_time_with_fallback(
    event_sources: dict,
    primary_event: LslEventSpecification,
    fallback_event: LslEventSpecification | None = None,
) -> float:
    """Sometimes the first markers are missing. Here we use a fallback."""
    try:
        return get_lsl_event_time_from_spec(event_sources, primary_event)
    except ValueError as e:
        if fallback_event is None:
            raise ValueError(f"No fallback event for {primary_event}!") from e

        logger.warning(
            "Using fallback event %s because primary event %s was missing",
            fallback_event.event,
            primary_event.event,
        )
    try:
        return get_lsl_event_time_from_spec(event_sources, fallback_event)
    except ValueError as fallback_error:
        raise ValueError(
            f"Primary event {primary_event} and fallback event {fallback_event} unavailable."
        ) from fallback_error


@deprecated("Older non pipeline method of creating intervals")
def create_lsl_trial_intervals(
    vr_markers_df: pd.DataFrame, VR_trial_events_df: pd.DataFrame
) -> dict[str, tuple[float, float]]:
    """
    Takes marker info from VR LSL streams vr_markers and VR_trial_events and creates intervals.
    """
    event_sources = {"VR_markers": vr_markers_df, "VR_trial_events": VR_trial_events_df}

    trial_intervals = {}

    for interval_name, interval_events in cfg.get_trial_intervals().items():  # type: ignore
        start_event = interval_events["start"]
        start_fallback = interval_events.get("start_fallback")

        end_event = interval_events["end"]
        end_fallback = interval_events.get("end_fallback")

        try:
            start_time = get_lsl_event_time_with_fallback(
                event_sources,
                start_event,
                start_fallback,
            )

            end_time = get_lsl_event_time_with_fallback(
                event_sources,
                end_event,
                end_fallback,
            )

        except ValueError:
            logger.warning(
                "Could not create interval %s from start event %s to end event %s",
                interval_name,
                start_event["event"],
                end_event["event"],
            )
            continue

        trial_intervals[interval_name] = (start_time, end_time)

    return trial_intervals


def slice_data_frame(
    timestamped_df_in: pd.DataFrame, trial_intervals: dict[str, tuple[float, float]]
) -> dict[str, pd.DataFrame]:
    """Takes any dataframe in and subdivides into intervals given."""
    df_dict_out = {}

    for key, start_end in trial_intervals.items():
        df_dict_out.update({f"{key}": lsl.cut_df_per_interval(start_end, timestamped_df_in)})

    return df_dict_out


# Plotting


def plot_biopac_interval_qc(
    trigger_df: pd.DataFrame,
    raw_biopac_trigger_intervals: TrialIntervals | None = None,
    corrected_trigger_intervals: TrialIntervals | None = None,
    behav_matched_trigger_intervals: TrialIntervals | None = None,
    raw_behav_trial_intervals: TrialIntervals | None = None,
) -> Figure:

    if raw_biopac_trigger_intervals is None:
        raw_biopac_trigger_intervals = TrialIntervals()

    if corrected_trigger_intervals is None:
        corrected_trigger_intervals = TrialIntervals()

    if behav_matched_trigger_intervals is None:
        behav_matched_trigger_intervals = TrialIntervals()

    if raw_behav_trial_intervals is None:
        raw_behav_trial_intervals = TrialIntervals()

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
    trigger_time_stamps, trigger_signal = get_biopac_raw_trigger_signal_for_plot(trigger_df)
    time_stamp_series = trigger_df["Trigger"]
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
        raw_behav_trial_intervals,
        time_stamp_series,
        color_nr=1,
        source_label="Raw behav",
        show_gaps=True,
    )

    # Row 2: same baseline, with corrected trigger intervals overlaid to show the shift

    plot_interval_ax(
        axes[2],
        raw_behav_trial_intervals,
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

    return fig


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


# Biopac interval concerns
def get_raw_biopac_trigger_intervals(
    trigger_df_in: pd.DataFrame,
) -> TrialIntervals:
    """
    Uses the biopac intervals and gets all the intervals and assigns a TP nr
    to them regardless of nr
    """
    trigger_times = trigger_df_in["time_stamps"][trigger_df_in["Trigger"].diff() > 0.47]
    trigger_events_df = trigger_times.to_frame(name="trigger_times")
    interval_pairs = list(
        zip(
            trigger_events_df["trigger_times"].iloc[:-1],
            trigger_events_df["trigger_times"].iloc[1:],
            strict=False,
        )
    )

    trigger_intervals_out = TrialIntervals.from_raw_interval_pairs(
        interval_pairs, physiology_file_format_in=PhysiologyFileFormat.BIOPAC
    )

    return trigger_intervals_out


def get_biopac_raw_trigger_signal_for_plot(
    raw_trigger_data: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Extracts the raw trigger voltage signal and its timestamps, ready for plotting."""
    time_stamps = raw_trigger_data["time_stamps"]
    trigger_signal = raw_trigger_data["Trigger"]

    return time_stamps, trigger_signal


def remove_biopac_known_false_triggers(
    trigger_intervals_to_check: TrialIntervals,
) -> tuple[TrialIntervals, ProcessingStatus]:
    # TODO: Improve! This needs to update with partial
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
        valid_trigger_interval_pairs, physiology_file_format_in=PhysiologyFileFormat.BIOPAC
    )

    return (valid_trigger_interval_pairs, status_out)


def align_biopac_trigger_drift_from_behav_file(
    trigger_intervals_in: TrialIntervals,
    behav_trial_intervals_in: TrialIntervals,
) -> tuple[TrialIntervals, PipelineStatus]:
    """
    Corrects clock drift between the biopac trigger signal and the Unreal
    behavioural trial timeline.

    Each trial's trigger pulse is sent from Unreal to Biopac via an Arduino,
    which introduces a small latency between the true (behavioural) trial
    start and the recorded trigger edge. This latency is not constant: it
    varies trial to trial (likely due to Unreal briefly lagging its own
    trial-start signal), so the trigger-derived intervals run slightly
    longer than their nominal behavioural duration. Because there is no
    re-sync between trials, this per-trial excess accumulates, causing the
    biopac trigger timeline to drift progressively later relative to the
    behavioural (Unreal) timeline over the course of the session.

    This function re-anchors the behavioural trial intervals onto the biopac
    trigger onsets, correcting for the accumulated drift and expressing the
    result in the physiology (biopac) timeframe.

    """

    pipeline_status = PipelineStatus()

    if len(trigger_intervals_in) < len(behav_trial_intervals_in):
        trigger_intervals_in.shift_intervals_forward_by(
            len(behav_trial_intervals_in) - len(trigger_intervals_in)
        )
        logger.warning(
            "There are less trigger intervals than trial intervals. Shifting to compensate."
        )
        pipeline_status.set(TrialIntervals, ProcessingStatus.CORRECTED)

    try:
        deltas = trigger_intervals_in.get_overlap(behav_trial_intervals_in)
        logger.info(
            f"Mean difference between trigger and behav intervals is: {np.nanmean(np.abs(deltas))}"
        )
        relabelled_trigger_intervals = trigger_intervals_in.relabel_with_intervals(
            behav_trial_intervals_in
        )
        relabelled_trigger_intervals.drop_nan_intervals()
        pipeline_status.set(TrialIntervals, ProcessingStatus.OK)
    except ValueError as error:
        logger.warning(f"Error in matching intervals: {error}")
        pipeline_status.set(TrialIntervals, ProcessingStatus.ERROR)
        relabelled_trigger_intervals = TrialIntervals()

    return (relabelled_trigger_intervals, pipeline_status)
