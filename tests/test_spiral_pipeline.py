import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from vrlab_toolbox.cli.vrlab_spiral_process import clean_final_output
from vrlab_toolbox.processing.graphomotor_xdf import (
    get_pen_drawing_window,
    get_pen_movement_intervals,
    is_current_eeg_xdf,
    is_pen_stream,
)
from vrlab_toolbox.processing.spiral import (
    detect_spiral_start_times,
    estimate_spiral_centre,
    estimate_spiral_centre_radius,
    get_hand_drawing_intervals,
    get_hand_switch_time,
    get_spiral_attempt_features,
    get_spiral_attempt_intervals,
    label_spiral_hands,
    select_completed_spiral_attempts,
)


def make_stream(name, stream_type="", timestamps=None, data=None, channel_names=None):
    """Build a minimal fake XDF stream dict, shaped like pyxdf's output."""
    if timestamps is None:
        timestamps = np.arange(10, dtype=float)
    timestamps = np.asarray(timestamps, dtype=float)

    if data is None:
        data = np.zeros((len(timestamps), 1))
    data = np.asarray(data)
    if data.ndim == 1:
        data = data[:, None]

    if channel_names is None:
        channel_names = [f"channel_{i}" for i in range(data.shape[1])]
    channels = [{"label": [name]} for name in channel_names]

    return {
        "info": {
            "name": [name],
            "type": [stream_type],
            "nominal_srate": ["100"],
            "desc": [{"channels": [{"channel": channels}]}],
        },
        "time_stamps": timestamps,
        "time_series": data,
    }


class TestPenStreamDetection(unittest.TestCase):
    def test_opensignals_is_not_pen(self):
        """Regression test for the OpenSignals/pen substring bug."""
        timestamps = np.arange(0, 10, 0.01)
        data = np.column_stack([np.sin(timestamps), np.cos(timestamps)])
        stream = make_stream(
            "OpenSignals", timestamps=timestamps, data=data, channel_names=["EDA", "ECG"]
        )

        self.assertFalse(is_pen_stream(stream))

    def test_current_eeg_filename_detection(self):
        current = Path("sub-PID123_ses-S001_task-Default_run-001_eeg.xdf")
        old = Path("sub-PID123_ses-S001_task-Default_run-001_eeg_old1.xdf")

        self.assertTrue(is_current_eeg_xdf(current))
        self.assertFalse(is_current_eeg_xdf(old))


class TestPenDrawingDetection(unittest.TestCase):
    def test_stationary_pen_is_not_drawing(self):
        """Repeated non-zero x/y coordinates must not count as drawing."""
        timestamps = np.arange(0, 20, 0.1)
        x = np.full(len(timestamps), 0.5)
        y = np.full(len(timestamps), 0.7)
        stream = make_stream(
            "MindLogger", "live_event", timestamps, np.column_stack([x, y]), ["x", "y"]
        )

        drawing_detected, _, _, active_duration = get_pen_drawing_window(stream)

        self.assertFalse(drawing_detected)
        self.assertEqual(active_duration, 0.0)

    def test_long_pause_splits_drawing(self):
        """A long timestamp gap should create two drawing intervals."""
        timestamps = np.concatenate([np.arange(0, 5, 0.1), np.arange(10, 15, 0.1)])
        x = y = np.arange(len(timestamps), dtype=float)
        stream = make_stream(
            "MindLogger", "live_event", timestamps, np.column_stack([x, y]), ["x", "y"]
        )

        intervals, _, _, _ = get_pen_movement_intervals(stream)

        self.assertEqual(len(intervals), 2)


class TestSpiralAttemptDetection(unittest.TestCase):
    def test_pen_lift_away_from_centre_does_not_start_new_spiral(self):
        timestamps = np.asarray([0.0, 0.1, 0.2, 0.3, 1.0, 1.1, 1.2])
        x = np.asarray([0.0, 0.05, 0.4, 1.0, 0.6, 0.8, 1.0])
        y = np.zeros(len(timestamps))

        starts = detect_spiral_start_times(
            timestamps,
            x,
            y,
            centre=(0.0, 0.0),
            centre_radius=0.15,
        )

        self.assertEqual(starts, [0.1])

    def test_return_to_centre_starts_new_spiral(self):
        timestamps = np.asarray([0.0, 0.1, 0.2, 0.3, 1.0, 1.1, 2.0, 2.1, 2.2])
        x = np.asarray([0.0, 0.05, 0.4, 1.0, 0.8, 1.0, 0.0, 0.05, 0.4])
        y = np.zeros(len(timestamps))

        starts = detect_spiral_start_times(
            timestamps,
            x,
            y,
            centre=(0.0, 0.0),
            centre_radius=0.15,
        )

        self.assertEqual(starts, [0.1, 2.0])

    def test_centre_restart_after_failed_start_is_new_attempt(self):
        timestamps = np.asarray([0.0, 0.1, 0.2, 1.0, 1.1, 1.2])
        x = np.asarray([0.0, 0.05, 0.1, 0.0, 0.05, 0.4])
        y = np.zeros(len(timestamps))

        starts = detect_spiral_start_times(
            timestamps,
            x,
            y,
            centre=(0.0, 0.0),
            centre_radius=0.15,
            restart_gap_sec=0.5,
        )

        self.assertEqual(starts, [0.1, 1.0])

    def test_attempt_intervals_end_before_next_centre_start(self):
        timestamps = np.asarray([0.0, 0.1, 0.2, 0.3, 1.9, 2.0, 2.1, 3.9, 4.0, 4.1])
        starts = [0.1, 2.0, 4.0]

        intervals = get_spiral_attempt_intervals(timestamps, starts)

        self.assertEqual(
            intervals,
            [
                (0.1, 1.9),
                (2.0, 3.9),
                (4.0, 4.1),
            ],
        )

    def test_retry_is_kept_as_separate_attempt(self):
        timestamps = np.asarray([0.0, 0.1, 0.2, 0.9, 1.0, 1.1, 1.2, 2.0])
        starts = [0.1, 1.0]

        intervals = get_spiral_attempt_intervals(timestamps, starts)

        self.assertEqual(
            intervals,
            [
                (0.1, 0.9),
                (1.0, 2.0),
            ],
        )

    def test_spiral_attempt_features_measure_full_spiral(self):
        theta = np.linspace(0, 4 * np.pi, 100)
        radius = np.linspace(0, 1, 100)
        timestamps = np.linspace(0, 10, 100)
        x = radius * np.cos(theta)
        y = radius * np.sin(theta)

        features = get_spiral_attempt_features(
            timestamps,
            x,
            y,
            centre=(0.0, 0.0),
            attempt_intervals=[(0.0, 10.0)],
        )

        self.assertEqual(len(features), 1)
        self.assertAlmostEqual(features.iloc[0]["Duration_sec"], 10.0)
        self.assertAlmostEqual(features.iloc[0]["Max_Radius"], 1.0, places=2)
        self.assertGreater(features.iloc[0]["Angular_Travel_rad"], 12.0)
        self.assertGreater(features.iloc[0]["Path_Length"], 1.0)

    def test_small_failed_attempt_has_small_radius_and_rotation(self):
        timestamps = np.linspace(0, 1, 20)
        x = np.linspace(0, 0.1, 20)
        y = np.zeros(20)

        features = get_spiral_attempt_features(
            timestamps,
            x,
            y,
            centre=(0.0, 0.0),
            attempt_intervals=[(0.0, 1.0)],
        )

        self.assertEqual(len(features), 1)
        self.assertLess(features.iloc[0]["Max_Radius"], 0.2)
        self.assertLess(features.iloc[0]["Angular_Travel_rad"], 1.0)

    def test_failed_attempt_is_rejected_when_more_than_16_attempts_exist(self):
        rows = []

        for attempt in range(1, 18):
            rows.append(
                {
                    "Attempt": attempt,
                    "Start_Time": float(attempt),
                    "End_Time": float(attempt) + 5.0,
                    "Duration_sec": 5.0,
                    "Max_Radius": 1.0,
                    "Angular_Travel_rad": 12.0,
                    "Path_Length": 8.0,
                }
            )

        rows[5]["Max_Radius"] = 0.1
        rows[5]["Angular_Travel_rad"] = 0.2
        rows[5]["Path_Length"] = 0.2

        features = pd.DataFrame(rows)

        selected = select_completed_spiral_attempts(features)

        self.assertEqual(len(selected), 16)
        self.assertNotIn(6, selected["Attempt"].tolist())

    def test_selected_spirals_are_returned_in_drawing_order(self):
        features = pd.DataFrame(
            [
                {
                    "Attempt": attempt,
                    "Start_Time": float(attempt),
                    "End_Time": float(attempt) + 5.0,
                    "Duration_sec": 5.0,
                    "Max_Radius": 1.0,
                    "Angular_Travel_rad": 12.0,
                    "Path_Length": 8.0,
                }
                for attempt in range(1, 18)
            ]
        )

        features.loc[features["Attempt"] == 4, "Max_Radius"] = 0.1
        features.loc[features["Attempt"] == 4, "Angular_Travel_rad"] = 0.2
        features.loc[features["Attempt"] == 4, "Path_Length"] = 0.2

        selected = select_completed_spiral_attempts(features)

        self.assertEqual(selected["Attempt"].tolist(), sorted(selected["Attempt"].tolist()))

    def test_fewer_than_16_attempts_are_not_hidden(self):
        features = pd.DataFrame(
            [
                {
                    "Attempt": attempt,
                    "Start_Time": float(attempt),
                    "End_Time": float(attempt) + 5.0,
                    "Duration_sec": 5.0,
                    "Max_Radius": 1.0,
                    "Angular_Travel_rad": 12.0,
                    "Path_Length": 8.0,
                }
                for attempt in range(1, 15)
            ]
        )

        selected = select_completed_spiral_attempts(features)

        self.assertEqual(len(selected), 14)

    def test_first_eight_spirals_are_dominant_and_last_eight_are_nondominant(self):
        selected = pd.DataFrame(
            [
                {
                    "Attempt": attempt,
                    "Start_Time": float(attempt * 10),
                    "End_Time": float(attempt * 10 + 5),
                }
                for attempt in range(1, 17)
            ]
        )

        labelled, switch_time = label_spiral_hands(selected)

        self.assertEqual(
            labelled["Hand"].tolist(),
            ["Dominant"] * 8 + ["NonDominant"] * 8,
        )
        self.assertEqual(labelled["Spiral_Number"].tolist(), list(range(1, 17)))
        self.assertAlmostEqual(switch_time, 87.5)

    def test_switch_is_between_spiral_eight_and_nine(self):
        selected = pd.DataFrame(
            [
                {
                    "Attempt": attempt,
                    "Start_Time": float(attempt),
                    "End_Time": float(attempt) + 0.5,
                }
                for attempt in range(1, 17)
            ]
        )

        _, switch_time = label_spiral_hands(selected)

        expected_switch = (8.5 + 9.0) / 2

        self.assertAlmostEqual(switch_time, expected_switch)

    def test_incomplete_task_does_not_assign_hand_labels(self):
        selected = pd.DataFrame(
            [
                {
                    "Attempt": attempt,
                    "Start_Time": float(attempt),
                    "End_Time": float(attempt) + 0.5,
                }
                for attempt in range(1, 15)
            ]
        )

        labelled, switch_time = label_spiral_hands(selected)

        self.assertNotIn("Hand", labelled.columns)
        self.assertIsNone(switch_time)

    def test_spiral_centre_is_estimated_from_repeated_starts(self):
        timestamps = np.asarray(
            [
                0.0,
                0.1,
                0.2,
                1.0,
                1.1,
                1.2,
                2.0,
                2.1,
                2.2,
                3.0,
                3.1,
                3.2,
            ]
        )
        x = np.asarray(
            [
                0.50,
                0.51,
                1.20,
                0.49,
                0.50,
                1.10,
                0.52,
                0.51,
                1.30,
                0.50,
                0.49,
                1.25,
            ]
        )
        y = np.asarray(
            [
                0.50,
                0.49,
                1.10,
                0.51,
                0.50,
                1.20,
                0.48,
                0.50,
                1.15,
                0.49,
                0.51,
                1.30,
            ]
        )

        centre = estimate_spiral_centre(
            timestamps,
            x,
            y,
            restart_gap_sec=0.5,
        )

        self.assertAlmostEqual(centre[0], 0.5, places=1)
        self.assertAlmostEqual(centre[1], 0.5, places=1)

    def test_isolated_restart_away_from_centre_does_not_move_estimated_centre(self):
        timestamps = np.asarray(
            [
                0.0,
                0.1,
                1.0,
                1.1,
                2.0,
                2.1,
                3.0,
                3.1,
                4.0,
                4.1,
            ]
        )
        x = np.asarray(
            [
                0.50,
                1.0,
                0.51,
                1.1,
                0.49,
                1.2,
                2.5,
                2.8,
                0.50,
                1.0,
            ]
        )
        y = np.asarray(
            [
                0.50,
                1.0,
                0.49,
                1.1,
                0.51,
                1.2,
                2.5,
                2.8,
                0.50,
                1.0,
            ]
        )

        centre = estimate_spiral_centre(
            timestamps,
            x,
            y,
            restart_gap_sec=0.5,
        )

        self.assertAlmostEqual(centre[0], 0.5, places=1)
        self.assertAlmostEqual(centre[1], 0.5, places=1)

    def test_centre_radius_follows_repeated_start_cluster(self):
        timestamps = np.asarray([0.0, 0.1, 1.0, 1.1, 2.0, 2.1, 3.0, 3.1])
        x = np.asarray([0.50, 1.0, 0.52, 1.1, 0.48, 1.2, 0.51, 1.0])
        y = np.asarray([0.50, 1.0, 0.49, 1.1, 0.51, 1.2, 0.50, 1.0])

        centre = (0.5, 0.5)

        radius = estimate_spiral_centre_radius(
            timestamps,
            x,
            y,
            centre=centre,
            restart_gap_sec=0.5,
        )

        self.assertGreater(radius, 0.0)
        self.assertLess(radius, 0.1)

    def test_outlying_restart_does_not_expand_centre_radius(self):
        timestamps = np.asarray([0.0, 0.1, 1.0, 1.1, 2.0, 2.1, 3.0, 3.1, 4.0, 4.1])
        x = np.asarray([0.50, 1.0, 0.51, 1.1, 0.49, 1.2, 2.5, 2.8, 0.50, 1.0])
        y = np.asarray([0.50, 1.0, 0.49, 1.1, 0.51, 1.2, 2.5, 2.8, 0.50, 1.0])

        radius = estimate_spiral_centre_radius(
            timestamps,
            x,
            y,
            centre=(0.5, 0.5),
            restart_gap_sec=0.5,
        )

        self.assertLess(radius, 0.1)

    def test_only_selected_spirals_enter_hand_drawing_intervals(self):
        selected = pd.DataFrame(
            [
                {
                    "Attempt": 1,
                    "Start_Time": 0.1,
                    "End_Time": 0.9,
                    "Hand": "Dominant",
                },
                {
                    "Attempt": 3,
                    "Start_Time": 2.0,
                    "End_Time": 2.9,
                    "Hand": "NonDominant",
                },
            ]
        )

        movement_intervals = [
            (0.1, 0.8),
            (1.0, 1.5),
            (2.0, 2.8),
        ]

        dominant, nondominant = get_hand_drawing_intervals(
            selected,
            movement_intervals,
        )

        self.assertEqual(dominant, [(0.1, 0.8)])
        self.assertEqual(nondominant, [(2.0, 2.8)])


class TestSpiralOutput(unittest.TestCase):
    def test_switch_uses_active_drawing_boundaries(self):
        dominant = [(0.1, 0.8), (7.0, 7.8)]
        nondominant = [(9.0, 9.8), (10.0, 10.8)]

        switch_time = get_hand_switch_time(dominant, nondominant)

        self.assertAlmostEqual(switch_time, 8.4)

    def test_switch_is_none_when_one_hand_is_missing(self):
        self.assertIsNone(get_hand_switch_time([], [(9.0, 9.8)]))
        self.assertIsNone(get_hand_switch_time([(0.1, 0.8)], []))

    def test_clean_csv_removes_legacy_debug_columns(self):
        df = pd.DataFrame(
            [
                {
                    "Subject_ID": "PID123",
                    "XDF_File": "sub-PID123_eeg.xdf",
                    "Spiral_Selected_Count": 16,
                    "C3_dominant_alpha": 1.2,
                    "Processing_Status": "TrialIntervals=ok",
                    "Selection_Status": "AUTO_SELECTED_HIGH_CONFIDENCE",
                    "Pen_Samples": 12345,
                    "XDF_Path": "/tmp/test.xdf",
                    "Total_Streams": 8,
                }
            ]
        )

        result = clean_final_output(df)

        self.assertNotIn("Selection_Status", result.columns)
        self.assertNotIn("Pen_Samples", result.columns)
        self.assertNotIn("XDF_Path", result.columns)
        self.assertNotIn("Total_Streams", result.columns)
        self.assertIn("Spiral_Selected_Count", result.columns)
        self.assertIn("C3_dominant_alpha", result.columns)
        self.assertIn("Processing_Status", result.columns)


if __name__ == "__main__":
    unittest.main()
