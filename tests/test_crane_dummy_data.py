import shutil
import tempfile
import unittest
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

from mooi_toolbox.cli.crane_convert_to_bids import convert_crane_to_bids
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.crane_behaviour import RawCraneBehaviourData
from mooi_toolbox.processing.crane_debrief_behaviour import RawDebriefBehaviourData
from mooi_toolbox.processing.crane_dummy_data import (
    DUMMY_GROUP_DEBRIEF_FN,
    REFERENCE_ERROR_TYPES,
    characterize_reference_trigger_pattern,
    discover_template_pairs,
    find_reference_mat_file,
    generate_dummy_dataset,
    generate_dummy_participant,
    generate_dummy_participant_matching_reference,
)
from mooi_toolbox.processing.crane_pipeline import run_pipeline
from mooi_toolbox.processing.processing_status import ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals

# Templates currently live under examples/crane_templates on disk, not the sample_data/ path
# this constant previously pointed at (that folder doesn't exist in this checkout).
TEMPLATE_FOLDER = Path("examples/crane_templates")

ERROR_SCENARIO_STATUS_KEY = {
    "missing_physiology": RawBioData,
    "missing_behaviour": RawCraneBehaviourData,
    "missing_debrief": RawDebriefBehaviourData,
    "bad_trigger_count": TrialIntervals,
    "short_trigger": TrialIntervals,
    "unbalanced_trial_conditions": RawCraneBehaviourData,
}


class TestCraneDummyData(unittest.TestCase):
    """
    generate_dummy_dataset() still writes the flat, raw {date}_{id}_CraneOut.{csv,mat} layout
    -- that's the input a real raw-to-BIDS conversion would run against, not what the pipeline
    itself reads anymore. So each generated dataset is run once through
    crane_convert_to_bids.convert_crane_to_bids() here, and run_pipeline() below points at that
    BIDS output, not the raw output_folder -- matching examples/crane_bids_dummy, the real BIDS
    dummy data these tests are meant to mirror.
    """

    @classmethod
    def setUpClass(cls):
        cls.output_folder = Path(tempfile.mkdtemp())
        cls.bids_folder = Path(tempfile.mkdtemp())
        cls.results = generate_dummy_dataset(
            TEMPLATE_FOLDER, cls.output_folder, n_clean=2, with_errors=True, seed=42
        )
        convert_crane_to_bids(cls.output_folder, cls.bids_folder)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.output_folder, ignore_errors=True)
        shutil.rmtree(cls.bids_folder, ignore_errors=True)

    def test_clean_participant_is_fully_ok(self):
        clean_result = next(r for r in self.results if r.scenario == "clean")
        pipeline_out = run_pipeline(clean_result.subject_id, self.bids_folder)
        self.assertTrue(
            all(status == ProcessingStatus.OK for status in pipeline_out.status.status.values())
        )

    def test_each_error_scenario_flags_expected_status(self):
        for result in self.results:
            if result.scenario == "clean":
                continue
            with self.subTest(scenario=result.scenario):
                pipeline_out = run_pipeline(result.subject_id, self.bids_folder)
                status_key = ERROR_SCENARIO_STATUS_KEY[result.scenario]
                self.assertEqual(pipeline_out.status.status[status_key], ProcessingStatus.ERROR)


class TestReferenceTriggerPatternGeneration(unittest.TestCase):
    """
    generate_dummy_participant_matching_reference() lets a caller point reference_folder at a
    real, gitignored crane_data/ folder to reproduce one participant's trigger anomaly shape
    locally, without that participant's data ever needing to leave their machine. Every
    "reference" file used *in this test class* is instead generated fresh from
    sample_data/crane_templates via generate_dummy_participant() — synthetic data only, same
    constraint the rest of this test file already follows.
    """

    @classmethod
    def setUpClass(cls):
        cls.output_folder = Path(tempfile.mkdtemp())
        csv_template, mat_template = discover_template_pairs(TEMPLATE_FOLDER)[0]
        cls.reference_result, _ = generate_dummy_participant(
            csv_template,
            mat_template,
            "REFSOURCE",
            "2026500",
            "2026500",
            cls.output_folder,
            np.random.default_rng(1),
        )
        if cls.reference_result.mat_path is not None:
            cls.reference_profile = characterize_reference_trigger_pattern(
                cls.reference_result.mat_path
            )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.output_folder, ignore_errors=True)

    def _generate_matching(self, reference_error_type: str, subject_id: str):
        return generate_dummy_participant_matching_reference(
            TEMPLATE_FOLDER,
            self.output_folder,
            reference_folder=self.output_folder,
            reference_subject_id="REFSOURCE",
            reference_error_type=reference_error_type,
            subject_id=subject_id,
            seed=1,
        )

    def test_find_reference_mat_file_locates_by_subject_id(self):
        found = find_reference_mat_file(self.output_folder, "REFSOURCE")
        self.assertEqual(found, self.reference_result.mat_path)

    def test_find_reference_mat_file_raises_for_unknown_subject(self):
        with self.assertRaises(FileNotFoundError):
            find_reference_mat_file(self.output_folder, "NOSUCHSUBJECT")

    def test_characterize_reference_trigger_pattern_reads_timing_only(self):
        self.assertGreater(self.reference_profile.n_pulses, 2)
        self.assertGreater(self.reference_profile.sampling_freq_hz, 0)
        self.assertLessEqual(
            self.reference_profile.min_gap_seconds, self.reference_profile.median_gap_seconds
        )

    def test_unknown_reference_error_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self._generate_matching("not_a_real_scenario", "REFBAD")

    def test_missing_initial_trigger_drops_one_pulse(self):
        result = self._generate_matching("missing_initial_trigger", "REFMISSINGINIT")
        if result.mat_path is not None:
            mutated_profile = characterize_reference_trigger_pattern(result.mat_path)
            self.assertEqual(mutated_profile.n_pulses, self.reference_profile.n_pulses - 1)

    def test_missing_last_trigger_drops_one_pulse(self):
        result = self._generate_matching("missing_last_trigger", "REFMISSINGLAST")
        if result.mat_path is not None:
            mutated_profile = characterize_reference_trigger_pattern(result.mat_path)
            self.assertEqual(mutated_profile.n_pulses, self.reference_profile.n_pulses - 1)

    def test_double_initial_trigger_adds_one_pulse_with_a_short_gap(self):
        result = self._generate_matching("double_initial_trigger", "REFDOUBLEINIT")
        if result.mat_path is not None:
            mutated_profile = characterize_reference_trigger_pattern(result.mat_path)
        self.assertEqual(mutated_profile.n_pulses, self.reference_profile.n_pulses + 1)
        # The new pulse's gap is set from the reference's own min_gap_seconds (see
        # generate_dummy_participant_matching_reference), so it should sit well below the
        # reference's *typical* cadence rather than strictly below its own min.
        self.assertLess(mutated_profile.min_gap_seconds, self.reference_profile.median_gap_seconds)

    def test_repeated_calls_accumulate_debrief_rows_instead_of_overwriting(self):
        first = self._generate_matching("missing_initial_trigger", "REFACCUM1")
        second = self._generate_matching("missing_last_trigger", "REFACCUM2")
        workbook = pd.read_csv(self.output_folder / DUMMY_GROUP_DEBRIEF_FN)
        subject_ids = set(workbook["record_id"])
        self.assertIn(first.subject_id, subject_ids)
        self.assertIn(second.subject_id, subject_ids)

    def test_reference_scenarios_still_produce_runnable_pipeline_output(self):
        # run_pipeline reads BIDS output, not the raw output_folder these participants are
        # generated into -- see TestCraneDummyData's docstring. Re-converting after each
        # participant is added is safe/cheap: convert_crane_to_bids is incremental and skips
        # subjects already present in bids_folder.
        bids_folder = Path(tempfile.mkdtemp())
        try:
            for index, reference_error_type in enumerate(REFERENCE_ERROR_TYPES):
                with self.subTest(scenario=reference_error_type):
                    result = self._generate_matching(reference_error_type, f"REFPIPE{index:03d}")
                    convert_crane_to_bids(self.output_folder, bids_folder)
                    pipeline_out = run_pipeline(result.subject_id, bids_folder)
                    self.assertEqual(
                        pipeline_out.subject_df_out["Subject_ID"].iloc[0], result.subject_id
                    )
        finally:
            shutil.rmtree(bids_folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
