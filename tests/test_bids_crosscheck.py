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
    crosschecked_scan_types,
    ensure_bidsignore,
    existing_subject_ids,
    load_decisions,
    load_excluded_subjects,
    load_pending_selections,
    record_date_correction,
    record_id_correction,
    record_selected_run,
    record_subject_excluded,
    record_task_tag,
    remove_task_tag,
    restore_all_from_bids,
    revert_all_decisions,
    save_pending_selections,
    scan_bids_folder,
    set_crosschecked,
)

TEST_CONFIG = DatasetConfig(
    dataset_name="test",
    scan_types=(
        ScanTypeConfig(name="physiology", glob_patterns=("*_physiology.*",)),
        ScanTypeConfig(name="debrief", glob_patterns=("*_redcap*.csv",)),
    ),
    task_tag_scan_type="physiology",
    task_tag_task="foh",
    task_tag_suffix="beh",
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

    def test_non_selected_files_are_removed_from_bids(self):
        # Deleted outright, not moved anywhere -- see record_selected_run's docstring. The raw
        # folder (never touched by any importer/converter) is the only recoverable copy now.
        record_selected_run(
            self.bids_folder, "001", "physiology", self.file_a, (self.file_a, self.file_b)
        )

        self.assertTrue(self.file_a.exists())
        self.assertFalse(self.file_b.exists())

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

    def test_raises_if_destination_already_exists(self):
        # Path.rename() silently overwrites an existing target on macOS/Linux (only Windows
        # raises on its own) -- this must be caught explicitly so the failure is the same
        # everywhere, not just where the OS happens to catch it.
        _touch(self.bids_folder / "sub-001" / "20240110_sub-001_redcap_v1.csv")

        with self.assertRaises(BidsCrosscheckError):
            record_date_correction(self.bids_folder, "001", "debrief", self.file, "20240110")

        self.assertTrue(self.file.exists())  # untouched -- the guard runs before any rename


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

    def test_renamed_files_use_forward_slashes_regardless_of_os(self):
        # Recorded from the *original* paths, before the rename happens -- same
        # decision-before-action ordering every other record_* function uses.
        record_id_correction(self.bids_folder, "001", "014")

        decision = load_decisions(self.bids_folder)["001"]
        self.assertIn(
            "sub-001/20240101_sub-001_physiology.acq", decision["renamed_files"]
        )
        for renamed in decision["renamed_files"]:
            self.assertNotIn("\\", renamed)

    def test_raises_for_unknown_subject(self):
        with self.assertRaises(BidsCrosscheckError):
            record_id_correction(self.bids_folder, "999", "014")

    def test_raises_if_corrected_folder_already_exists(self):
        _touch(self.bids_folder / "sub-014" / "unrelated.txt")

        with self.assertRaises(BidsCrosscheckError):
            record_id_correction(self.bids_folder, "001", "014")

        self.assertTrue((self.bids_folder / "sub-001").exists())  # untouched

    def test_raises_if_a_renamed_file_would_collide(self):
        # A file already sitting at what would become the corrected name for a *different*
        # file in this subject's folder -- must be caught before any renaming starts, not
        # leave the folder half-renamed.
        _touch(self.bids_folder / "sub-001" / "20240101_sub-014_physiology.acq")

        with self.assertRaises(BidsCrosscheckError):
            record_id_correction(self.bids_folder, "001", "014")

        self.assertTrue((self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq").exists())

    def test_allows_a_pure_case_change_in_the_id(self):
        # Windows/macOS are case-insensitive filesystems -- correcting "abc" to "ABC" would
        # otherwise look like the corrected folder "already exists" (it's the same folder,
        # case-insensitively) and be wrongly blocked. See _is_real_collision.
        _touch(self.bids_folder / "sub-abc" / "20240101_sub-abc_physiology.acq")

        corrected_folder = record_id_correction(self.bids_folder, "abc", "ABC")

        self.assertEqual(corrected_folder, self.bids_folder / "sub-ABC")
        self.assertTrue((corrected_folder / "20240101_sub-ABC_physiology.acq").exists())


class TestRecordSubjectExcluded(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_redcap_v1.csv")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_deletes_the_whole_subject_folder(self):
        destination = record_subject_excluded(self.bids_folder, "001")

        self.assertEqual(destination, self.bids_folder / "sub-001")
        self.assertFalse((self.bids_folder / "sub-001").exists())

    def test_records_reason(self):
        record_subject_excluded(self.bids_folder, "001", reason="non_participant")

        excluded = load_excluded_subjects(self.bids_folder)
        self.assertEqual(excluded["001"], "non_participant")

    def test_reason_defaults_to_none(self):
        record_subject_excluded(self.bids_folder, "001")

        excluded = load_excluded_subjects(self.bids_folder)
        self.assertIsNone(excluded["001"])

    def test_raises_for_unknown_subject(self):
        with self.assertRaises(BidsCrosscheckError):
            record_subject_excluded(self.bids_folder, "999")


class TestExistingSubjectIds(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_includes_a_subject_present_on_disk(self):
        _touch(self.bids_folder / "sub-001" / "a.acq")

        self.assertEqual(existing_subject_ids(self.bids_folder), {"001"})

    def test_still_includes_an_excluded_subject(self):
        # Critical: an excluded subject's folder is deleted, not moved -- if it dropped out of
        # this set, the next raw-to-BIDS refresh would treat it as brand new and silently
        # re-copy it back in.
        _touch(self.bids_folder / "sub-001" / "a.acq")
        record_subject_excluded(self.bids_folder, "001")

        self.assertEqual(existing_subject_ids(self.bids_folder), {"001"})

    def test_empty_for_a_folder_that_does_not_exist_yet(self):
        missing = self.bids_folder / "does-not-exist"

        self.assertEqual(existing_subject_ids(missing), set())


class TestRestoreAllFromBids(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_restores_an_excluded_subject(self):
        _touch(self.bids_folder / "sub-001" / "a_physiology.acq")
        record_subject_excluded(self.bids_folder, "001")
        self.assertIn("001", existing_subject_ids(self.bids_folder))

        restored, errors = restore_all_from_bids(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertEqual(restored, ["001"])
        self.assertNotIn("001", existing_subject_ids(self.bids_folder))
        self.assertEqual(load_excluded_subjects(self.bids_folder), {})

    def test_restores_a_subject_with_a_committed_duplicate_pick(self):
        file_a = _touch(self.bids_folder / "sub-001" / "a_physiology.acq")
        file_b = _touch(self.bids_folder / "sub-001" / "b_physiology.acq")
        record_selected_run(self.bids_folder, "001", "physiology", file_a, (file_a, file_b))
        self.assertTrue((self.bids_folder / "sub-001").is_dir())

        restored, errors = restore_all_from_bids(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertEqual(restored, ["001"])
        # The WHOLE subject is re-derived on the next refresh, not just the removed file --
        # see restore_all_from_bids's docstring for why.
        self.assertFalse((self.bids_folder / "sub-001").exists())
        self.assertNotIn("selected_run", {e.get("type") for e in load_decisions(self.bids_folder).values()})

    def test_no_op_on_a_folder_with_nothing_removed(self):
        restored, errors = restore_all_from_bids(self.bids_folder)

        self.assertEqual((restored, errors), ([], []))


class TestRevertAllDecisions(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_reverts_a_date_correction(self):
        file = _touch(self.bids_folder / "sub-001" / "20240108_sub-001_redcap_v1.csv")
        record_date_correction(self.bids_folder, "001", "debrief", file, "20240110")
        self.assertFalse(file.exists())

        reverted, errors = revert_all_decisions(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertTrue(file.exists())

    def test_reverts_a_task_tag(self):
        file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")
        record_task_tag(self.bids_folder, "001", "physiology", file, task="foh", suffix="beh")
        self.assertFalse(file.exists())

        reverted, errors = revert_all_decisions(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertTrue(file.exists())

    def test_reverts_an_id_correction(self):
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        record_id_correction(self.bids_folder, "001", "014")
        self.assertFalse((self.bids_folder / "sub-001").exists())

        reverted, errors = revert_all_decisions(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertTrue((self.bids_folder / "sub-001").exists())
        self.assertFalse((self.bids_folder / "sub-014").exists())

    def test_clears_decisions_and_pending_selections(self):
        file = _touch(self.bids_folder / "sub-001" / "20240108_sub-001_redcap_v1.csv")
        record_date_correction(self.bids_folder, "001", "debrief", file, "20240110")
        save_pending_selections(self.bids_folder, {"001": {"physiology": "a.acq"}})

        revert_all_decisions(self.bids_folder)

        self.assertEqual(load_decisions(self.bids_folder), {})
        self.assertEqual(load_pending_selections(self.bids_folder), {})

    def test_only_reverts_the_latest_decision_for_a_given_key(self):
        # date_correction and task_tag share the same _decision_key(subject_id, scan_type) --
        # the second overwrites the first's record, so only the second is revertible. This is
        # the documented limitation, not a bug.
        file = _touch(self.bids_folder / "sub-001" / "20240108_sub-001_run-2_physiology.acq")
        corrected = record_date_correction(self.bids_folder, "001", "physiology", file, "20240110")
        record_task_tag(self.bids_folder, "001", "physiology", corrected, task="foh", suffix="beh")

        reverted, errors = revert_all_decisions(self.bids_folder)

        # The task_tag reverts (strips the tag) leaving the *date-corrected* name, not the
        # true original -- the date_correction record was already overwritten.
        self.assertTrue(
            (self.bids_folder / "sub-001" / "20240110_sub-001_run-2_physiology.acq").exists()
        )

    def test_does_not_error_on_an_already_reverted_file(self):
        file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")
        record_task_tag(self.bids_folder, "001", "physiology", file, task="foh", suffix="beh")
        # Simulate the file having already been restored/renamed some other way.
        (self.bids_folder / "sub-001" / "sub-001_task-foh_run-2_beh.xdf").rename(file)

        reverted, errors = revert_all_decisions(self.bids_folder)

        self.assertEqual(errors, [])

    def test_reverts_a_task_tag_that_also_renamed_the_parent_folder(self):
        file = _touch(self.bids_folder / "sub-001" / "eeg" / "sub-001_run-2_eeg_philani.xdf")
        record_task_tag(
            self.bids_folder,
            "001",
            "physiology",
            file,
            task="foh",
            suffix="beh",
            datatype_folder_name="beh",
        )

        reverted, errors = revert_all_decisions(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertTrue(file.exists())
        self.assertFalse((self.bids_folder / "sub-001" / "beh").exists())


class TestEnsureBidsignore(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_creates_bidsignore_with_required_entries(self):
        ensure_bidsignore(self.bids_folder)

        content = (self.bids_folder / ".bidsignore").read_text(encoding="utf-8")
        self.assertIn("crosscheck.json", content)
        self.assertIn("crosscheck_pending.json", content)
        self.assertIn("excluded_subjects.json", content)

    def test_includes_extra_patterns(self):
        ensure_bidsignore(self.bids_folder, ("crosscheck_info_cache.json",))

        content = (self.bids_folder / ".bidsignore").read_text(encoding="utf-8")
        self.assertIn("crosscheck_info_cache.json", content)

    def test_appends_to_an_existing_bidsignore_without_touching_its_content(self):
        bidsignore = self.bids_folder / ".bidsignore"
        bidsignore.write_text("derivatives/\n", encoding="utf-8")

        ensure_bidsignore(self.bids_folder)

        content = bidsignore.read_text(encoding="utf-8")
        self.assertIn("derivatives/", content)
        self.assertIn("crosscheck.json", content)

    def test_is_idempotent(self):
        ensure_bidsignore(self.bids_folder)
        first = (self.bids_folder / ".bidsignore").read_text(encoding="utf-8")

        ensure_bidsignore(self.bids_folder)
        second = (self.bids_folder / ".bidsignore").read_text(encoding="utf-8")

        self.assertEqual(first, second)


class TestRecordTaskTag(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_inserts_task_entity_and_renames_the_suffix(self):
        destination = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
        )

        self.assertEqual(destination.name, "sub-001_task-foh_run-2_beh.xdf")

    def test_inserts_acq_entity_when_given(self):
        destination = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh", acq="lsl"
        )

        self.assertEqual(destination.name, "sub-001_task-foh_acq-lsl_run-2_beh.xdf")

    def test_rejects_a_filename_with_no_run_token(self):
        file = _touch(self.bids_folder / "sub-002" / "sub-002_physiology.xdf")

        with self.assertRaises(BidsCrosscheckError):
            record_task_tag(self.bids_folder, "002", "physiology", file, task="foh", suffix="beh")

    def test_rejects_file_already_labelled(self):
        labelled = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
        )

        with self.assertRaises(BidsCrosscheckError):
            record_task_tag(
                self.bids_folder, "001", "physiology", labelled, task="foh", suffix="beh"
            )

    def test_rejects_a_file_already_labelled_under_different_casing(self):
        # A file that already carries the task- marker under a different casing must still
        # count as tagged -- see _is_real_collision's docstring for why a case-insensitive
        # filesystem makes re-tagging it actively dangerous too.
        legacy = _touch(self.bids_folder / "sub-003" / "sub-003_TASK-FOH_run-1_eeg.xdf")

        with self.assertRaises(BidsCrosscheckError):
            record_task_tag(
                self.bids_folder, "003", "physiology", legacy, task="foh", suffix="beh"
            )

        self.assertTrue(legacy.exists())  # untouched

    def test_raises_if_destination_already_exists(self):
        _touch(self.bids_folder / "sub-001" / "sub-001_task-foh_run-2_beh.xdf")

        with self.assertRaises(BidsCrosscheckError):
            record_task_tag(
                self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
            )

        self.assertTrue(self.file.exists())  # untouched -- the guard runs before any rename

    def test_renames_the_parent_folder_when_a_datatype_folder_name_is_given(self):
        file = _touch(self.bids_folder / "sub-002" / "eeg" / "sub-002_run-1_eeg_philani.xdf")

        destination = record_task_tag(
            self.bids_folder,
            "002",
            "physiology",
            file,
            task="foh",
            suffix="beh",
            datatype_folder_name="beh",
        )

        expected = self.bids_folder / "sub-002" / "beh" / "sub-002_task-foh_run-1_beh.xdf"
        self.assertEqual(destination, expected)
        self.assertTrue(destination.exists())
        self.assertFalse((self.bids_folder / "sub-002" / "eeg").exists())

    def test_parent_folder_rename_keeps_sibling_files(self):
        file = _touch(self.bids_folder / "sub-002" / "eeg" / "sub-002_run-1_eeg_philani.xdf")
        sibling = _touch(self.bids_folder / "sub-002" / "eeg" / "sub-002_run-1_eeg_other.xdf")

        record_task_tag(
            self.bids_folder,
            "002",
            "physiology",
            file,
            task="foh",
            suffix="beh",
            datatype_folder_name="beh",
        )

        self.assertTrue((self.bids_folder / "sub-002" / "beh" / sibling.name).exists())

    def test_does_not_rename_the_parent_folder_when_it_already_matches(self):
        file = _touch(self.bids_folder / "sub-002" / "beh" / "sub-002_run-1_eeg_philani.xdf")

        destination = record_task_tag(
            self.bids_folder,
            "002",
            "physiology",
            file,
            task="foh",
            suffix="beh",
            datatype_folder_name="beh",
        )

        self.assertEqual(destination.parent, self.bids_folder / "sub-002" / "beh")

    def test_raises_if_target_parent_folder_already_exists(self):
        file = _touch(self.bids_folder / "sub-002" / "eeg" / "sub-002_run-1_eeg_philani.xdf")
        _touch(self.bids_folder / "sub-002" / "beh" / "unrelated.txt")

        with self.assertRaises(BidsCrosscheckError):
            record_task_tag(
                self.bids_folder,
                "002",
                "physiology",
                file,
                task="foh",
                suffix="beh",
                datatype_folder_name="beh",
            )

        self.assertTrue(file.exists())  # untouched -- the guard runs before any rename


class TestRemoveTaskTag(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_reverses_a_tag_insertion(self):
        labelled = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
        )

        restored = remove_task_tag(
            self.bids_folder, "001", "physiology", labelled, task="foh", suffix="beh"
        )

        self.assertEqual(restored.name, "sub-001_run-2_eeg.xdf")
        self.assertTrue(restored.exists())

    def test_reverses_a_tag_insertion_with_acq(self):
        labelled = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh", acq="lsl"
        )

        restored = remove_task_tag(
            self.bids_folder, "001", "physiology", labelled, task="foh", suffix="beh", acq="lsl"
        )

        self.assertEqual(restored.name, "sub-001_run-2_eeg.xdf")

    def test_rejects_file_without_the_label(self):
        with self.assertRaises(BidsCrosscheckError):
            remove_task_tag(
                self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
            )

    def test_accepts_a_tag_under_different_casing(self):
        # Not backed by a recorded decision -- exercises the best-effort structural fallback
        # under a different casing of the task- marker.
        legacy = _touch(self.bids_folder / "sub-003" / "sub-003_TASK-FOH_run-1_eeg.xdf")

        restored = remove_task_tag(
            self.bids_folder, "003", "physiology", legacy, task="foh", suffix="beh"
        )

        self.assertEqual(restored.name, "sub-003_run-1.xdf")

    def test_falls_back_to_stripping_the_tag_when_no_matching_decision_is_recorded(self):
        # Simulate a file tagged outside this tool -- no task_tag decision exists for it, so
        # the original free text (e.g. "_eeg") can't be recovered, only the tag stripped.
        tagged = _touch(self.bids_folder / "sub-002" / "sub-002_task-foh_run-1_beh.xdf")

        restored = remove_task_tag(
            self.bids_folder, "002", "physiology", tagged, task="foh", suffix="beh"
        )

        self.assertEqual(restored.name, "sub-002_run-1.xdf")

    def test_raises_if_destination_already_exists(self):
        labelled = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
        )
        # Recreate a file at the name removal would restore to.
        _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

        with self.assertRaises(BidsCrosscheckError):
            remove_task_tag(
                self.bids_folder, "001", "physiology", labelled, task="foh", suffix="beh"
            )

        self.assertTrue(labelled.exists())  # untouched -- the guard runs before any rename

    def test_decision_records_the_removal(self):
        labelled = record_task_tag(
            self.bids_folder, "001", "physiology", self.file, task="foh", suffix="beh"
        )

        remove_task_tag(self.bids_folder, "001", "physiology", labelled, task="foh", suffix="beh")

        decisions = load_decisions(self.bids_folder)
        entry = decisions["001_physiology"]
        self.assertEqual(entry["type"], "task_tag_removed")
        self.assertEqual(entry["corrected_filename"], "sub-001_run-2_eeg.xdf")

    def test_reverses_a_parent_folder_rename(self):
        file = _touch(self.bids_folder / "sub-002" / "eeg" / "sub-002_run-1_eeg_philani.xdf")
        labelled = record_task_tag(
            self.bids_folder,
            "002",
            "physiology",
            file,
            task="foh",
            suffix="beh",
            datatype_folder_name="beh",
        )

        restored = remove_task_tag(
            self.bids_folder, "002", "physiology", labelled, task="foh", suffix="beh"
        )

        expected = self.bids_folder / "sub-002" / "eeg" / "sub-002_run-1_eeg_philani.xdf"
        self.assertEqual(restored, expected)
        self.assertTrue(restored.exists())
        self.assertFalse((self.bids_folder / "sub-002" / "beh").exists())

    def test_does_not_move_the_folder_back_when_no_matching_decision_is_recorded(self):
        # Same "tagged outside this tool" scenario as the filename fallback above -- there's no
        # original_parent_folder to restore to, so the folder is left exactly where it is.
        tagged = _touch(self.bids_folder / "sub-002" / "beh" / "sub-002_task-foh_run-1_beh.xdf")

        restored = remove_task_tag(
            self.bids_folder, "002", "physiology", tagged, task="foh", suffix="beh"
        )

        self.assertEqual(restored.parent, self.bids_folder / "sub-002" / "beh")


class TestCrosschecked(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_starts_unmarked(self):
        self.assertEqual(crosschecked_scan_types(self.bids_folder), set())

    def test_marking_adds_to_the_set(self):
        set_crosschecked(self.bids_folder, "001", "physiology", True)

        self.assertEqual(crosschecked_scan_types(self.bids_folder), {("001", "physiology")})

    def test_unmarking_removes_it_again(self):
        set_crosschecked(self.bids_folder, "001", "physiology", True)
        set_crosschecked(self.bids_folder, "001", "physiology", False)

        self.assertEqual(crosschecked_scan_types(self.bids_folder), set())

    def test_does_not_clobber_an_existing_selected_run_decision(self):
        record_selected_run(self.bids_folder, "001", "physiology", self.file, (self.file,))
        set_crosschecked(self.bids_folder, "001", "physiology", True)

        decision = load_decisions(self.bids_folder)["001_physiology"]
        self.assertEqual(decision["type"], "selected_run")
        self.assertEqual(crosschecked_scan_types(self.bids_folder), {("001", "physiology")})


class TestPendingSelections(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_starts_empty(self):
        self.assertEqual(load_pending_selections(self.bids_folder), {})

    def test_round_trips(self):
        save_pending_selections(
            self.bids_folder, {"001": {"physiology": "20240101_sub-001_physiology.acq"}}
        )

        self.assertEqual(
            load_pending_selections(self.bids_folder),
            {"001": {"physiology": "20240101_sub-001_physiology.acq"}},
        )

    def test_overwrites_previous_contents_rather_than_merging(self):
        save_pending_selections(self.bids_folder, {"001": {"physiology": "a.acq"}})
        save_pending_selections(self.bids_folder, {"002": {"physiology": "b.acq"}})

        self.assertEqual(
            load_pending_selections(self.bids_folder), {"002": {"physiology": "b.acq"}}
        )

    def test_is_a_separate_file_from_decisions(self):
        save_pending_selections(self.bids_folder, {"001": {"physiology": "a.acq"}})

        self.assertEqual(load_decisions(self.bids_folder), {})
        self.assertTrue((self.bids_folder / "crosscheck_pending.json").exists())
        self.assertFalse((self.bids_folder / "crosscheck.json").exists())


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
