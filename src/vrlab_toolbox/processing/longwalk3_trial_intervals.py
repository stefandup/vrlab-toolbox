"""LongwalkV3 trial intervals (docs/longwalk3_plan.md, D2).

An interval starts at the first Biopac pulse sent by an actor instance and ends when a pulse
arrives from a *different* actor instance; its label is the actor instance name (repeats get a
"__2", "__3" suffix). Consecutive pulses from the same instance extend its interval.

Which rows pulse comes from the combined events.tsv: every `trigger_<class>` cell that is
filled is one pulse sent by the instance it names -- except the classes in
NON_PULSE_ACTOR_CLASSES (never pulse) and FIRST_ROW_PULSE_ACTOR_CLASSES (only their first row
pulses). These mirror the generator's `_NON_PULSE_SUFFIXES`/`_FIRST_ROW_PULSE_SUFFIXES` in
longwalk3_dummy_data.py and are still a working assumption until the Unreal side confirms it.

Clock drift (same problem as crane, see trial_intervals.align_biopac_trigger_drift_from_behav_
file): each behaviour pulse is matched to its rising edge on the Biopac Trigger channel,
re-anchoring the clock offset on every match (see map_pulses_to_biopac_time), and every
interval boundary is taken from the matched *edge*, so drift never accumulates. Pulses with
no recorded edge (recording started late / stopped early) get their neighbours' offset
(status CORRECTED); with fewer than two matches nothing can be placed (status ERROR).
"""

import logging
from typing import cast

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.input_data import PhysiologyFileFormat
from vrlab_toolbox.processing.longwalk3_behaviour import RawLongWalkV3BehaviourData
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import (
    TrialIntervals,
    get_raw_biopac_trigger_intervals,
    plot_biopac_interval_qc,
)

logger = logging.getLogger(__name__)

TRIGGER_COLUMN_PREFIX = "trigger_"
NON_PULSE_ACTOR_CLASSES: tuple[str, ...] = ("BPBirdsFlyingC",)
FIRST_ROW_PULSE_ACTOR_CLASSES: tuple[str, ...] = ("BPHeatmapManagerC",)
# Biopac pulses last ~0.1 s, so pulses sent closer together than this show up as a single
# rising edge -- behaviour pulses within this gap are merged before matching.
MIN_PULSE_GAP_SECONDS = 0.15
# An edge counts as a pulse's match only within this much of where the drift-tracked offset
# predicts it. Drift is ~0.1 s/min at most, and matches re-anchor the offset every pulse.
MATCH_TOLERANCE_SECONDS = 0.5
# Starting alignments tried: each of the first N pulses against each of the first N edges.
ALIGNMENT_CANDIDATES = 5


def get_behaviour_pulses(raw_behav_df: pd.DataFrame) -> pd.DataFrame:
    """One row per Biopac pulse the run should have sent, in time order: `onset` (seconds,
    behaviour timeline) and `instance` (the actor instance that sent it)."""
    pulses = []
    for column in raw_behav_df.columns:
        if not str(column).startswith(TRIGGER_COLUMN_PREFIX):
            continue
        actor_class = str(column)[len(TRIGGER_COLUMN_PREFIX) :]
        if actor_class in NON_PULSE_ACTOR_CLASSES:
            continue
        rows = raw_behav_df.loc[raw_behav_df[column].notna(), ["onset", column]]
        rows = rows.dropna(subset=["onset"]).sort_values("onset")
        if actor_class in FIRST_ROW_PULSE_ACTOR_CLASSES:
            rows = rows.head(1)
        pulses.append(
            pd.DataFrame({"onset": rows["onset"].astype(float), "instance": rows[column]})
        )
    if not pulses:
        return pd.DataFrame({"onset": pd.Series(dtype=float), "instance": pd.Series(dtype=str)})
    all_pulses = pd.concat(pulses, ignore_index=True).sort_values("onset", kind="stable")
    keep = all_pulses["onset"].diff().fillna(np.inf) >= MIN_PULSE_GAP_SECONDS
    return cast(pd.DataFrame, all_pulses[keep].reset_index(drop=True))


def get_biopac_pulse_times(raw_trigger_df: pd.DataFrame) -> np.ndarray:
    """Rising-edge times on the Biopac Trigger channel (same edge detection as
    trial_intervals.get_raw_biopac_trigger_intervals)."""
    raw_intervals = get_raw_biopac_trigger_intervals(raw_trigger_df)
    starts = [start for start, _ in raw_intervals.intervals.values()]
    if raw_intervals.intervals:
        starts.append(list(raw_intervals.intervals.values())[-1][1])
    return np.asarray(sorted(starts), dtype=float)


def _track_matches(onsets: np.ndarray, edges: np.ndarray, offset: float) -> tuple[np.ndarray, int]:
    """Walks the pulses in order, matching each to the nearest unused edge within
    MATCH_TOLERANCE_SECONDS of where the current offset predicts it, and re-anchoring the
    offset on every match -- so a slowly growing clock drift is followed, not accumulated.
    Returns each pulse's matched edge time (NaN if none) and the number matched."""
    matched = np.full(len(onsets), np.nan)
    next_edge = 0
    n_matched = 0
    for i, onset in enumerate(onsets):
        expected = onset + offset
        remaining = edges[next_edge:]
        if remaining.size == 0:
            break
        nearest = int(np.argmin(np.abs(remaining - expected)))
        if abs(remaining[nearest] - expected) <= MATCH_TOLERANCE_SECONDS:
            matched[i] = remaining[nearest]
            offset = remaining[nearest] - onset
            next_edge += nearest + 1
            n_matched += 1
    return matched, n_matched


def map_pulses_to_biopac_time(
    behaviour_onsets: np.ndarray, biopac_edges: np.ndarray
) -> tuple[np.ndarray, ProcessingStatus]:
    """Each behaviour pulse's time on the Biopac clock.

    Pulses are matched to Biopac rising edges by `_track_matches`, trying the first few
    pulse/edge pairings as the starting alignment and keeping the one that matches most (so
    a recording that starts late or stops early doesn't throw the rest off). Every pulse
    matched: OK. Some unmatched (no edge recorded for them): their time comes from the
    neighbouring matches' offset (interpolated, held constant past either end) -- CORRECTED.
    Fewer than two matches: all NaN -- ERROR.
    """
    n_pulses = len(behaviour_onsets)
    if n_pulses == 0 or len(biopac_edges) < 2:
        return np.full(n_pulses, np.nan), ProcessingStatus.ERROR

    best_matched, best_count = np.full(n_pulses, np.nan), 0
    for i in range(min(ALIGNMENT_CANDIDATES, n_pulses)):
        for j in range(min(ALIGNMENT_CANDIDATES, len(biopac_edges))):
            matched, count = _track_matches(
                behaviour_onsets, biopac_edges, biopac_edges[j] - behaviour_onsets[i]
            )
            if count > best_count:
                best_matched, best_count = matched, count

    if best_count < 2:
        logger.warning("Could not match behaviour pulses to Biopac trigger edges")
        return np.full(n_pulses, np.nan), ProcessingStatus.ERROR
    if best_count == n_pulses:
        return best_matched, ProcessingStatus.OK

    logger.warning(
        "%d of %d behaviour pulses have no Biopac trigger edge (%d edges recorded) -- their "
        "times are interpolated from the neighbouring matched pulses",
        n_pulses - best_count,
        n_pulses,
        len(biopac_edges),
    )
    is_matched = ~np.isnan(best_matched)
    offsets = best_matched[is_matched] - behaviour_onsets[is_matched]
    interpolated = behaviour_onsets + np.interp(
        behaviour_onsets, behaviour_onsets[is_matched], offsets
    )
    return np.where(is_matched, best_matched, interpolated), ProcessingStatus.CORRECTED


def build_actor_instance_intervals(pulse_times: np.ndarray, instances: list[str]) -> TrialIntervals:
    """D2 intervals from time-ordered pulses: a new interval whenever the sending instance
    changes; it ends at the next interval's first pulse (the last one at its own last pulse)."""
    labels: dict[str, int] = {}
    starts: list[tuple[str, float]] = []
    previous_instance = None
    for time, instance in zip(pulse_times, instances, strict=True):
        if instance == previous_instance or np.isnan(time):
            continue
        labels[instance] = labels.get(instance, 0) + 1
        label = instance if labels[instance] == 1 else f"{instance}__{labels[instance]}"
        starts.append((label, float(time)))
        previous_instance = instance

    intervals: dict[str, tuple[float, float]] = {}
    for (label, start), (_, next_start) in zip(starts, starts[1:], strict=False):
        intervals[label] = (start, next_start)
    if starts:
        last_label, last_start = starts[-1]
        valid_times = pulse_times[~np.isnan(pulse_times)]
        intervals[last_label] = (last_start, float(max(last_start, valid_times.max())))
    return TrialIntervals(intervals=intervals, physiology_file_format=PhysiologyFileFormat.BIOPAC)


class LongWalkV3GetTrialIntervalStrategyStep:
    input_bio_data_type: type[RawBioData] = RawBioData
    input_behaviour_data_type: type[RawLongWalkV3BehaviourData] = RawLongWalkV3BehaviourData
    fallback_strategy = None

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawLongWalkV3BehaviourData
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]:
        status = PipelineStatus()
        trigger_df = raw_biodata_in["Trigger"]

        raw_biopac_triggers = get_raw_biopac_trigger_intervals(trigger_df)
        biopac_edges = get_biopac_pulse_times(trigger_df)
        pulses = get_behaviour_pulses(raw_behaviour_data_in.raw_behav_df)

        pulse_times, match_status = map_pulses_to_biopac_time(
            pulses["onset"].to_numpy(dtype=float), biopac_edges
        )
        status.set(TrialIntervals, match_status)
        trial_intervals_out = build_actor_instance_intervals(
            pulse_times, pulses["instance"].astype(str).tolist()
        )
        logger.info(
            "%d behaviour pulses, %d Biopac edges -> %d actor-instance intervals (%s)",
            len(pulses),
            len(biopac_edges),
            len(trial_intervals_out),
            match_status.name,
        )

        behaviour_timeline_intervals = build_actor_instance_intervals(
            pulses["onset"].to_numpy(dtype=float), pulses["instance"].astype(str).tolist()
        )
        interval_qc_figure_out = plot_biopac_interval_qc(
            trigger_df,
            raw_biopac_trigger_intervals=raw_biopac_triggers,
            behav_matched_trigger_intervals=trial_intervals_out,
            raw_behav_trial_intervals=behaviour_timeline_intervals,
        )
        return (trial_intervals_out, interval_qc_figure_out, status)
