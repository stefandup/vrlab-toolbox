import tempfile
import unittest
from pathlib import Path

from vrlab_toolbox.processing.spiral_pipeline import FindSpiralParticipantFilesStrategyStep


class TestFindSpiralParticipantFilesStrategyStep(unittest.TestCase):
    def test_crosschecked_subject_has_exactly_one_xdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_folder = Path(temp_dir)
            subject_folder = bids_folder / "sub-PID123" / "eeg"
            subject_folder.mkdir(parents=True)
            xdf_file = subject_folder / "sub-PID123_run-001_eeg.xdf"
            xdf_file.touch()

            config = FindSpiralParticipantFilesStrategyStep().run(
                "PID123",
                bids_folder,
                bids_folder / "output",
            )

            self.assertEqual(Path(config.physiology_fn), xdf_file)

    def test_multiple_xdfs_require_crosscheck(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            bids_folder = Path(temp_dir)
            subject_folder = bids_folder / "sub-PID123" / "eeg"
            subject_folder.mkdir(parents=True)
            (subject_folder / "sub-PID123_run-001_eeg.xdf").touch()
            (subject_folder / "sub-PID123_run-002_eeg.xdf").touch()

            with self.assertRaisesRegex(ValueError, "Run the Spiral BIDS crosscheck first"):
                FindSpiralParticipantFilesStrategyStep().run(
                    "PID123",
                    bids_folder,
                    bids_folder / "output",
                )


if __name__ == "__main__":
    unittest.main()
