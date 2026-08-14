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
    junk_folder,
    load_decisions,
    load_pending_selections,
    record_date_correction,
    record_id_correction,
    record_selected_run,
    record_subject_junked,
    record_task_correction,
    remove_task_correction,
    restore_all_from_junk,
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


class TestRecordSubjectJunked(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_physiology.acq")
        _touch(self.bids_folder / "sub-001" / "20240101_sub-001_redcap_v1.csv")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_moves_the_whole_subject_folder(self):
        destination = record_subject_junked(self.bids_folder, "001")

        self.assertEqual(destination, junk_folder(self.bids_folder) / "sub-001")
        self.assertFalse((self.bids_folder / "sub-001").exists())
        self.assertTrue((destination / "20240101_sub-001_physiology.acq").exists())
        self.assertTrue((destination / "20240101_sub-001_redcap_v1.csv").exists())

    def test_decision_records_reason(self):
        record_subject_junked(self.bids_folder, "001", reason="non_participant")

        decision = load_decisions(self.bids_folder)["001_junked"]
        self.assertEqual(decision["type"], "subject_junked")
        self.assertEqual(decision["junked_reason"], "non_participant")

    def test_reason_defaults_to_none(self):
        record_subject_junked(self.bids_folder, "001")

        decision = load_decisions(self.bids_folder)["001_junked"]
        self.assertIsNone(decision["junked_reason"])

    def test_does_not_collide_with_a_stale_id_correction_entry(self):
        # record_id_correction keys its decision by the *original* id (bare _decision_key),
        # so a subject renamed away from "001" leaves a bare "001" entry behind. If a
        # different, later subject also ends up with id "001" and gets junked, that must not
        # overwrite the older id_correction record still sitting under the same bare key.
        record_id_correction(self.bids_folder, "001", "099")
        _touch(self.bids_folder / "sub-001" / "20240201_sub-001_physiology.acq")

        record_subject_junked(self.bids_folder, "001")

        decisions = load_decisions(self.bids_folder)
        self.assertEqual(decisions["001"]["type"], "id_correction")
        self.assertEqual(decisions["001"]["corrected_id"], "099")
        self.assertEqual(decisions["001_junked"]["type"], "subject_junked")

    def test_raises_for_unknown_subject(self):
        with self.assertRaises(BidsCrosscheckError):
            record_subject_junked(self.bids_folder, "999")

    def test_raises_if_destination_already_exists(self):
        _touch(junk_folder(self.bids_folder) / "sub-001" / "stray.txt")

        with self.assertRaises(BidsCrosscheckError):
            record_subject_junked(self.bids_folder, "001")


class TestRestoreAllFromJunk(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_restores_a_whole_junked_subject(self):
        _touch(self.bids_folder / "sub-001" / "a_physiology.acq")
        record_subject_junked(self.bids_folder, "001")
        self.assertFalse((self.bids_folder / "sub-001").exists())

        restored, errors = restore_all_from_junk(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertTrue((self.bids_folder / "sub-001" / "a_physiology.acq").exists())
        self.assertEqual(list(junk_folder(self.bids_folder).iterdir()), [])

    def test_merges_individually_junked_files_back_into_an_existing_subject_folder(self):
        # record_selected_run only junks the *non-selected* duplicate(s) -- the subject
        # folder itself, and the winning file, stay right where they are.
        file_a = _touch(self.bids_folder / "sub-001" / "a_physiology.acq")
        file_b = _touch(self.bids_folder / "sub-001" / "b_physiology.acq")
        record_selected_run(self.bids_folder, "001", "physiology", file_a, (file_a, file_b))
        self.assertTrue((self.bids_folder / "sub-001").is_dir())  # still exists, unlike above
        self.assertFalse(file_b.exists())

        restored, errors = restore_all_from_junk(self.bids_folder)

        self.assertEqual(errors, [])
        self.assertTrue(file_a.exists())
        self.assertTrue(file_b.exists())

    def test_reports_a_conflict_instead_of_overwriting(self):
        _touch(self.bids_folder / "sub-001" / "a.acq")
        record_subject_junked(self.bids_folder, "001")
        # Recreate a subject with the same id/file after it was junked -- restoring must not
        # silently clobber it.
        _touch(self.bids_folder / "sub-001" / "a.acq")

        restored, errors = restore_all_from_junk(self.bids_folder)

        self.assertEqual(restored, [])
        self.assertEqual(len(errors), 1)

    def test_no_op_on_a_folder_with_no_junk(self):
        restored, errors = restore_all_from_junk(self.bids_folder)

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

    def test_reverts_a_task_correction(self):
        file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")
        record_task_correction(self.bids_folder, "001", "physiology", file)
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
        # date_correction and task_correction share the same _decision_key(subject_id,
        # scan_type) -- the second overwrites the first's record, so only the second is
        # revertible. This is the documented limitation, not a bug.
        file = _touch(self.bids_folder / "sub-001" / "20240108_sub-001_run-2_physiology.acq")
        corrected = record_date_correction(self.bids_folder, "001", "physiology", file, "20240110")
        record_task_correction(self.bids_folder, "001", "physiology", corrected)

        reverted, errors = revert_all_decisions(self.bids_folder)

        # The task_correction reverts (strips the FOH tag) leaving the *date-corrected* name,
        # not the true original -- the date_correction record was already overwritten.
        self.assertTrue(
            (self.bids_folder / "sub-001" / "20240110_sub-001_run-2_physiology.acq").exists()
        )

    def test_does_not_error_on_an_already_reverted_file(self):
        file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")
        record_task_correction(self.bids_folder, "001", "physiology", file)
        # Simulate the file having already been restored/renamed some other way.
        (self.bids_folder / "sub-001" / "sub-001_run-2_FOH.xdf").rename(file)

        reverted, errors = revert_all_decisions(self.bids_folder)

        self.assertEqual(errors, [])


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
        self.assertIn("crosscheck_junk/", content)

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


class TestRecordTaskCorrection(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_replaces_everything_after_the_run_token(self):
        destination = record_task_correction(self.bids_folder, "001", "physiology", self.file)

        self.assertEqual(destination.name, "sub-001_run-2_FOH.xdf")

    def test_rejects_a_filename_with_no_run_token(self):
        file = _touch(self.bids_folder / "sub-002" / "sub-002_physiology.xdf")

        with self.assertRaises(BidsCrosscheckError):
            record_task_correction(self.bids_folder, "002", "physiology", file)

    def test_rejects_file_already_labelled(self):
        labelled = record_task_correction(self.bids_folder, "001", "physiology", self.file)

        with self.assertRaises(BidsCrosscheckError):
            record_task_correction(self.bids_folder, "001", "physiology", labelled)

    def test_raises_if_destination_already_exists(self):
        _touch(self.bids_folder / "sub-001" / "sub-001_run-2_FOH.xdf")

        with self.assertRaises(BidsCrosscheckError):
            record_task_correction(self.bids_folder, "001", "physiology", self.file)

        self.assertTrue(self.file.exists())  # untouched -- the guard runs before any rename


class TestRemoveTaskCorrection(unittest.TestCase):
    def setUp(self):
        self.bids_folder = Path(tempfile.mkdtemp())
        self.file = _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

    def tearDown(self):
        shutil.rmtree(self.bids_folder, ignore_errors=True)

    def test_reverses_a_label_insertion(self):
        labelled = record_task_correction(self.bids_folder, "001", "physiology", self.file)

        restored = remove_task_correction(self.bids_folder, "001", "physiology", labelled)

        self.assertEqual(restored.name, "sub-001_run-2_eeg.xdf")
        self.assertTrue(restored.exists())

    def test_rejects_file_without_the_label(self):
        with self.assertRaises(BidsCrosscheckError):
            remove_task_correction(self.bids_folder, "001", "physiology", self.file)

    def test_falls_back_to_stripping_the_tag_when_no_matching_decision_is_recorded(self):
        # Simulate a file tagged outside this tool -- no task_correction decision exists for
        # it, so the original suffix (e.g. "_eeg") can't be recovered, only the tag stripped.
        tagged = _touch(self.bids_folder / "sub-002" / "sub-002_run-1_FOH.xdf")

        restored = remove_task_correction(self.bids_folder, "002", "physiology", tagged)

        self.assertEqual(restored.name, "sub-002_run-1.xdf")

    def test_raises_if_destination_already_exists(self):
        labelled = record_task_correction(self.bids_folder, "001", "physiology", self.file)
        # Recreate a file at the name removal would restore to.
        _touch(self.bids_folder / "sub-001" / "sub-001_run-2_eeg.xdf")

        with self.assertRaises(BidsCrosscheckError):
            remove_task_correction(self.bids_folder, "001", "physiology", labelled)

        self.assertTrue(labelled.exists())  # untouched -- the guard runs before any rename

    def test_decision_records_the_removal(self):
        labelled = record_task_correction(self.bids_folder, "001", "physiology", self.file)

        remove_task_correction(self.bids_folder, "001", "physiology", labelled)

        decisions = load_decisions(self.bids_folder)
        entry = decisions["001_physiology"]
        self.assertEqual(entry["type"], "task_correction_removed")
        self.assertEqual(entry["corrected_filename"], "sub-001_run-2_eeg.xdf")


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
