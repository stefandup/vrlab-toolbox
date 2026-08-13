import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mooi_toolbox.processing.bids_crosscheck import (
    BidsCrosscheckError,
    DatasetConfig,
    ScanTypeConfig,
    completeness_summary,
    junk_folder,
    load_decisions,
    record_date_correction,
    record_id_correction,
    record_selected_run,
    record_task_correction,
    scan_bids_folder,
)

TEST_CONFIG = DatasetConfig(
    dataset_name="test",
    scan_types=(
        ScanTypeConfig(name="physiology", glob_patterns=("*_physiology.*",)),
        ScanTypeConfig(name="debrief", glob_patterns=("*_redcap*.csv",)),
    ),
    task_correction_scan_type="physiology",
    task_correction_label="FOH",
)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    return path


class TestScanBidsFolder(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_finds_single_matching_file_as_ok(self):
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")

        scan = scan_bids_folder(self.bids_folder, TEST_CONFIG)

        self.assertEqual(scan.scans["001"]["physiology"].status, "ok")

    def test_flags_zero_matches_as_missing(self):
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")

        scan = scan_bids_folder(self.bids_folder, TEST_CONFIG)

        self.assertEqual(scan.scans["001"]["debrief"].status, "missing")
        self.assertTrue(scan.has_issues("001"))

    def test_flags_multiple_matches_as_duplicate(self):
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        _touch(self.bids_folder / "sub-001" / "20240102_sub-001_physiology.acq")

        scan = scan_bids_folder(self.bids_folder, TEST_CONFIG)

        self.assertEqual(scan.scans["001"]["physiology"].status, "duplicate")
        self.assertEqual(len(scan.scans["001"]["physiology"].files), 2)

    def test_junk_folder_is_excluded_from_scanning(self):
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        _touch(junk_folder(self.bids_folder) / "sub-001" / "old_physiology.acq")

        scan = scan_bids_folder(self.bids_folder, TEST_CONFIG)

        self.assertNotIn("crosscheck_junk", scan.subject_ids())

    def test_completeness_summary_counts_ok_subjects_per_scan_type(self):
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        _touch(self.bids_folder / "sub-002" / "20240101_sub-002_physiology.acq")
        _touch(self.bids_folder / "sub-002" / "20240102_sub-002_physiology.acq")

        scan = scan_bids_folder(self.bids_folder, TEST_CONFIG)
        summary = completeness_summary(scan, TEST_CONFIG)

        self.assertEqual(summary["physiology"], (1, 2))
        self.assertEqual(summary["debrief"], (0, 2))


class TestRecordSelectedRun(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file_a = _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        self.file_b = _touch(self.bids_folder / "sub-001" / "20240102_sub-001_physiology.acq")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_non_selected_files_move_to_junk(self):
        record_selected_run(
            self.bids_folder, "001", "physiology", self.file_a, (self.file_a, self.file_b)
        )

        self.assertTrue(self.file_a.exists())
        self.assertFalse(self.file_b.exists())
        self.assertTrue((junk_folder(self.bids_folder) / "sub-001" / self.file_b.name).exists())

    def test_decision_is_recorded(self):
        record_selected_run(
            self.bids_folder, "001", "physiology", self.file_a, (self.file_a, self.file_b)
        )

        decision = load_decisions(self.bids_folder)["001_physiology"]
        self.assertEqual(decision["type"], "selected_run")
        self.assertEqual(decision["selected_file"], self.file_a.name)
        self.assertEqual(decision["non_selected_files"], [self.file_b.name])

    def test_rejects_selection_outside_candidates(self):
        stray_file = _touch(self.bids_folder / "sub-002" / "unrelated.acq")

        with self.assertRaises(BidsCrosscheckError):
            record_selected_run(
                self.bids_folder, "001", "physiology", stray_file, (self.file_a, self.file_b)
            )


class TestRecordDateCorrection(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "20240108_sub-001_redcap_v1.csv")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_renames_with_corrected_date_prefix(self):
        destination = record_date_correction(
            self.bids_folder, "001", "debrief", self.file, "20240110"
        )

        self.assertEqual(destination.name, "20240110_sub-001_redcap_v1.csv")
        self.assertTrue(destination.exists())
        self.assertFalse(self.file.exists())

    def test_decision_records_original_filename_and_date(self):
        record_date_correction(self.bids_folder, "001", "debrief", self.file, "20240110")

        decision = load_decisions(self.bids_folder)["001_debrief"]
        self.assertEqual(decision["original_filename"], "20240108_sub-001_redcap_v1.csv")
        self.assertEqual(decision["original_date"], "20240108")
        self.assertEqual(decision["corrected_date"], "20240110")


class TestRecordIdCorrection(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_redcap_v1.csv")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_renames_subject_folder_and_every_file_within_it(self):
        corrected_folder = record_id_correction(self.bids_folder, "001", "014")

        self.assertEqual(corrected_folder, self.bids_folder / "sub-014")
        self.assertFalse((self.bids_folder / "sub-001").exists())
        self.assertTrue((corrected_folder / "20240101_sub-014_physiology.acq").exists())
        self.assertTrue((corrected_folder / "20240101_sub-014_redcap_v1.csv").exists())

    def test_decision_lists_every_renamed_file(self):
        record_id_correction(self.bids_folder, "001", "014")

        decision = load_decisions(self.bids_folder)["001"]
        self.assertEqual(decision["type"], "id_correction")
        self.assertEqual(decision["corrected_id"], "014")
        self.assertEqual(len(decision["renamed_files"]), 2)

    def test_raises_for_unknown_subject(self):
        with self.assertRaises(BidsCrosscheckError):
            record_id_correction(self.bids_folder, "999", "014")


class TestRecordTaskCorrection(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_inserts_label_before_suffix(self):
        destination = record_task_correction(self.bids_folder, "001", "physiology", self.file)

        self.assertEqual(destination.name, "sub-001_run-2_eeg_FOH.xdf")

    def test_rejects_file_already_labelled(self):
        labelled = record_task_correction(self.bids_folder, "001", "physiology", self.file)

        with self.assertRaises(BidsCrosscheckError):
            record_task_correction(self.bids_folder, "001", "physiology", labelled)


class TestDecisionsJsonIsValidJson(unittest.TestCase):
    def test_write_produces_parseable_file(self):
        bids_folder = Path(tempfile.mkdtemp())
        try:
            file_a = _touch(bids_folder / "sub-001" / "a_physiology.acq")
            record_selected_run(bids_folder, "001", "physiology", file_a, (file_a,))

            with (bids_folder / "crosscheck.json").open() as decisions_file:
                json.load(decisions_file)
        finally:
            shutil.rmtree(bids_folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
