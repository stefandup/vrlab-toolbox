"""LongwalkV3 D2 interval rules (longwalk3_trial_intervals.py), on hand-made pulses."""

import numpy as np
import pandas as pd

from vrlab_toolbox.processing.longwalk3_trial_intervals import (
    build_actor_instance_intervals,
    get_behaviour_pulses,
    map_pulses_to_biopac_time,
)
from vrlab_toolbox.processing.processing_status import ProcessingStatus


def test_interval_runs_until_a_different_instance_pulses():
    intervals = build_actor_instance_intervals(
        np.array([1.0, 2.0, 3.0, 5.0, 8.0]), ["npc_0", "npc_0", "phone_0", "npc_0", "npc_0"]
    )
    assert intervals.intervals == {
        "npc_0": (1.0, 3.0),
        "phone_0": (3.0, 5.0),
        "npc_0__2": (5.0, 8.0),
    }


def test_birds_never_pulse_and_heatmap_only_once():
    df = pd.DataFrame(
        {
            "onset": [1.0, 1.5, 2.0, 2.5, 3.0],
            "trigger_BPHeatmapManagerC": ["heat_1", "heat_1", None, None, None],
            "trigger_BPBirdsFlyingC": [None, None, "bird_0", None, None],
            "trigger_BPNPCC": [None, None, None, "npc_0", "npc_0"],
        }
    )
    pulses = get_behaviour_pulses(df)
    assert pulses["instance"].tolist() == ["heat_1", "npc_0", "npc_0"]


def test_pulses_too_close_for_biopac_are_merged():
    df = pd.DataFrame({"onset": [1.0, 1.01, 2.0], "trigger_BPNPCC": ["a", "b", "c"]})
    assert get_behaviour_pulses(df)["instance"].tolist() == ["a", "c"]


def test_matching_counts_use_the_biopac_edges_so_drift_cannot_accumulate():
    behaviour = np.array([0.0, 60.0, 120.0])
    edges = np.array([10.0, 70.05, 130.1])  # Biopac drifting 50 ms/min behind
    times, status = map_pulses_to_biopac_time(behaviour, edges)
    assert status is ProcessingStatus.OK
    assert np.allclose(times, edges)


def test_stray_edge_is_ignored():
    times, status = map_pulses_to_biopac_time(
        np.array([0.0, 30.0, 60.0]), np.array([10.0, 40.0, 50.0, 70.0])
    )
    assert status is ProcessingStatus.OK
    assert np.allclose(times, [10.0, 40.0, 70.0])


def test_pulse_after_recording_ended_is_interpolated_from_drift():
    behaviour = np.array([0.0, 60.0, 120.0, 180.0])
    edges = np.array([10.0, 70.1, 130.2])  # recording stopped before the last pulse
    times, status = map_pulses_to_biopac_time(behaviour, edges)
    assert status is ProcessingStatus.CORRECTED
    assert np.allclose(times[:3], edges)
    assert np.isclose(times[3], 180.0 + 10.2)  # last known offset held


def test_recording_started_late_still_matches_the_rest():
    behaviour = np.array([0.0, 5.0, 60.0, 100.0, 180.0])
    edges = np.array([70.0, 110.05, 190.1])  # first two pulses before the recording
    times, status = map_pulses_to_biopac_time(behaviour, edges)
    assert status is ProcessingStatus.CORRECTED
    assert np.allclose(times[2:], edges)


def test_no_edges_is_an_error():
    times, status = map_pulses_to_biopac_time(np.array([1.0]), np.array([]))
    assert status is ProcessingStatus.ERROR
    assert np.isnan(times).all()
