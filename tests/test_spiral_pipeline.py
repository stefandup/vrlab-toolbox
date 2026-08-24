import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from mooi_toolbox.cli.mobi_spiral_process_batch import clean_final_output
from mooi_toolbox.processing.graphomotor_xdf import (
    add_qc_flags,
    choose_best_xdfs,
    get_pen_drawing_window,
    get_pen_movement_intervals,
    is_current_eeg_xdf,
    is_pen_stream,
)


def make_stream(
    name,
    stream_type="",
    timestamps=None,
    data=None,
    channel_names=None,
):
    """Create a small fake XDF stream for testing."""

    if timestamps is None:
        timestamps = np.arange(10, dtype=float)

    timestamps = np.asarray(timestamps, dtype=float)

    if data is None:
        data = np.zeros((len(timestamps), 1))

    data = np.asarray(data)

    if data.ndim == 1:
        data = data[:, None]

    if channel_names is None:
        channel_names = [
            f"channel_{i}"
            for i in range(data.shape[1])
        ]

    channels = [
        {
            "label": [channel_name],
        }
        for channel_name in channel_names
    ]

    return {
        "info": {
            "name": [name],
            "type": [stream_type],
            "nominal_srate": ["100"],
            "desc": [
                {
                    "channels": [
                        {
                            "channel": channels,
                        }
                    ]
                }
            ],
        },
        "time_stamps": timestamps,
        "time_series": data,
    }


class TestSpiralPipeline(unittest.TestCase):

    def test_opensignals_is_not_pen(self):
        """Regression test for the OpenSignals/pen substring bug."""

        timestamps = np.arange(
            0,
            10,
            0.01,
        )

        data = np.column_stack(
            [
                np.sin(timestamps),
                np.cos(timestamps),
            ]
        )

        stream = make_stream(
            name="OpenSignals",
            timestamps=timestamps,
            data=data,
            channel_names=[
                "EDA",
                "ECG",
            ],
        )

        self.assertFalse(
            is_pen_stream(stream)
        )

    def test_stationary_pen_is_not_drawing(self):
        """Repeated non-zero x/y coordinates must not count as drawing."""

        timestamps = np.arange(
            0,
            20,
            0.1,
        )

        x = np.full(
            len(timestamps),
            0.5,
        )

        y = np.full(
            len(timestamps),
            0.7,
        )

        stream = make_stream(
            name="MindLogger",
            stream_type="live_event",
            timestamps=timestamps,
            data=np.column_stack([x, y]),
            channel_names=[
                "x",
                "y",
            ],
        )

        (
            drawing_detected,
            _,
            _,
            active_duration,
        ) = get_pen_drawing_window(
            stream
        )

        self.assertFalse(
            drawing_detected
        )

        self.assertEqual(
            active_duration,
            0.0,
        )

    def test_long_pause_splits_drawing(self):
        """A long timestamp gap should create two drawing intervals."""

        timestamps = np.concatenate(
            [
                np.arange(
                    0,
                    5,
                    0.1,
                ),
                np.arange(
                    10,
                    15,
                    0.1,
                ),
            ]
        )

        x = np.arange(
            len(timestamps),
            dtype=float,
        )

        y = np.arange(
            len(timestamps),
            dtype=float,
        )

        stream = make_stream(
            name="MindLogger",
            stream_type="live_event",
            timestamps=timestamps,
            data=np.column_stack([x, y]),
            channel_names=[
                "x",
                "y",
            ],
        )

        intervals, _, _, _ = (
            get_pen_movement_intervals(
                stream
            )
        )

        self.assertEqual(
            len(intervals),
            2,
        )

    def test_best_xdf_selected_by_coverage(self):
        """Better multimodal coverage should beat the *_eeg.xdf filename."""

        candidates = pd.DataFrame(
            [
                {
                    "Subject_ID": "sub-PID123",
                    "XDF_File": "sub-PID123_eeg.xdf",
                    "XDF_Path": "/tmp/sub-PID123_eeg.xdf",
                    "Drawing_Detected": True,
                    "EDA_Coverage_pct": 40,
                    "ECG_Coverage_pct": 40,
                    "Neon_Gaze_Coverage_pct": 40,
                    "EEG_Coverage_pct": 100,
                    "Filename_Is_Current_EEG_XDF": True,
                    "Pen_Samples": 100,
                    "Total_Samples_All_Streams": 1000,
                    "EEG_Present": True,
                },
                {
                    "Subject_ID": "sub-PID123",
                    "XDF_File": "sub-PID123_old1.xdf",
                    "XDF_Path": "/tmp/sub-PID123_old1.xdf",
                    "Drawing_Detected": True,
                    "EDA_Coverage_pct": 100,
                    "ECG_Coverage_pct": 100,
                    "Neon_Gaze_Coverage_pct": 100,
                    "EEG_Coverage_pct": 95,
                    "Filename_Is_Current_EEG_XDF": False,
                    "Pen_Samples": 100,
                    "Total_Samples_All_Streams": 1000,
                    "EEG_Present": True,
                },
            ]
        )

        selected = choose_best_xdfs(
            candidates
        )

        self.assertEqual(
            selected.iloc[0]["XDF_File"],
            "sub-PID123_old1.xdf",
        )

    def test_missing_ecg_is_flagged(self):
        """Missing ECG should produce an AUTO_SELECTED_CHECK flag."""

        selected = pd.DataFrame(
            [
                {
                    "Selected_XDF": True,
                    "Subject_ID": "sub-PID123",
                    "XDF_File": "sub-PID123_eeg.xdf",
                    "XDF_Path": "/tmp/sub-PID123_eeg.xdf",

                    "Drawing_Detected": True,

                    "EDA_Present": True,
                    "EDA_Coverage_pct": 100,

                    "ECG_Present": False,
                    "ECG_Coverage_pct": 0,

                    "Neon_Gaze_Present": True,
                    "Neon_Gaze_Coverage_pct": 100,

                    "EEG_Present": True,
                    "EEG_Coverage_pct": 100,

                    "Selection_Ambiguous": False,
                    "Filename_Is_Current_EEG_XDF": True,
                    "Subject_Has_Any_EEG_XDF": True,
                    "Selected_XDF_Has_EEG": True,
                }
            ]
        )

        result = add_qc_flags(
            selected
        )

        self.assertEqual(
            result.iloc[0]["Selection_Status"],
            "AUTO_SELECTED_CHECK",
        )

        self.assertIn(
            "ECG_MISSING",
            result.iloc[0]["Selection_Reason"],
        )

    def test_clean_csv_removes_debug_columns(self):
        """Debugging fields should not appear in the final CSV."""

        df = pd.DataFrame(
            [
                {
                    "Subject_ID": "sub-PID123",
                    "XDF_File": "sub-PID123_eeg.xdf",

                    "Selection_Status":
                        "AUTO_SELECTED_HIGH_CONFIDENCE",

                    "Selection_Reason":
                        "Valid drawing with strong multimodal coverage",

                    "Drawing_Detected": True,

                    "EDA_Present": True,
                    "EDA_Coverage_pct": 100,

                    "ECG_Present": True,
                    "ECG_Coverage_pct": 100,

                    "Neon_Gaze_Present": True,
                    "Neon_Gaze_Coverage_pct": 100,

                    "EEG_Present": True,
                    "EEG_Coverage_pct": 100,

                    "Pen_Samples": 12345,
                    "EEG_Samples": 54321,
                    "XDF_Path": "/tmp/test.xdf",
                    "Total_Streams": 8,

                    "FullRecording_SCR_Peaks_N": 12,
                }
            ]
        )

        result = clean_final_output(
            df
        )

        self.assertNotIn(
            "Pen_Samples",
            result.columns,
        )

        self.assertNotIn(
            "EEG_Samples",
            result.columns,
        )

        self.assertNotIn(
            "XDF_Path",
            result.columns,
        )

        self.assertNotIn(
            "Total_Streams",
            result.columns,
        )

        self.assertIn(
            "FullRecording_SCR_Peaks_N",
            result.columns,
        )

    def test_current_eeg_filename_detection(self):
        current = Path(
            "sub-PID123_ses-S001_task-Default_run-001_eeg.xdf"
        )

        old = Path(
            "sub-PID123_ses-S001_task-Default_run-001_eeg_old1.xdf"
        )

        self.assertTrue(
            is_current_eeg_xdf(current)
        )

        self.assertFalse(
            is_current_eeg_xdf(old)
        )


if __name__ == "__main__":
    unittest.main()