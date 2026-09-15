import shutil
import tempfile
import unittest
from pathlib import Path

import matplotlib
import numpy as np
import pyxdf

matplotlib.use("Agg")

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.foh_behaviour import ImportFohBehaviourDataStrategyStep
from mooi_toolbox.processing.foh_dummy_data import (
    DUMMY_DATA_LOG_FILENAME,
    ERROR_TYPES,
    generate_dummy_foh_dataset,
    generate_dummy_foh_participant,
)
from mooi_toolbox.processing.foh_pipeline import run_pipeline
from mooi_toolbox.processing.foh_target_behaviour import ImportFohTargetBehaviourDataStrategyStep
from mooi_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from mooi_toolbox.processing.lsl import FohLslPhysiologyDataImportStrategy
from mooi_toolbox.processing.processing_status import ProcessingStatus

# Same relative-difference threshold the FOH crosscheck GUI uses (see
# gui/foh_bids_crosscheck_gui.py's SRATE_MISMATCH_THRESHOLD) -- kept as a literal here rather
# than imported, since importing that module drags in PySide6 just to read one constant.
SRATE_MISMATCH_THRESHOLD = 0.1


class TestGenerateDummyFohParticipant(unittest.TestCase):
    """Round-trips the private XDF writer through pyxdf.load_xdf -- the same reader the real
    pipeline and the crosscheck GUI use -- for a clean participant and every ERROR_TYPES
    scenario, checking each produces the specific, documented effect it's meant to.
    """

    def setUp(self):
        self.output_folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.output_folder, ignore_errors=True)
        self.rng = np.random.default_rng(42)

    def _config_for(self, subject_id: str) -> ParticipantConfig:
        return ParticipantConfig.from_lsl_data(
            subject_id, self.output_folder, PhysiologyFileFormat.LSL
        )

    def test_clean_participant_has_all_four_streams(self):
        result = generate_dummy_foh_participant(self.output_folder, "CLEAN", self.rng, None)
        streams, _ = pyxdf.load_xdf(str(result.xdf_path))
        names = {stream["info"]["name"][0] for stream in streams}
        self.assertEqual(names, {"OpenSignals", "VR_markers", "VR_trial_events", "FOH_target"})

    def test_clean_participant_produces_expected_filename_and_layout(self):
        result = generate_dummy_foh_participant(self.output_folder, "CLEAN", self.rng, None)
        expected = (
            self.output_folder
            / "sub-CLEAN"
            / "ses-S001"
            / "beh"
            / "sub-CLEAN_ses-S001_task-foh_run-001_beh.xdf"
        )
        self.assertEqual(result.xdf_path, expected)
        self.assertTrue(expected.is_file())

    def test_clean_participant_runs_the_full_pipeline_ok(self):
        generate_dummy_foh_participant(self.output_folder, "CLEAN", self.rng, None)
        pipeline_out = run_pipeline("CLEAN", self.output_folder)
        self.assertTrue(
            all(status == ProcessingStatus.OK for status in pipeline_out.status.status.values())
        )
        self.assertIn("eda_qc", pipeline_out.figure_data_out)
        self.assertIn("Interval_qc", pipeline_out.figure_data_out)

    def test_unknown_error_type_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_dummy_foh_participant(
                self.output_folder, "BAD", self.rng, "not_a_real_scenario"
            )

    def test_missing_physiology_drops_opensignals_stream(self):
        generate_dummy_foh_participant(self.output_folder, "MP", self.rng, "missing_physiology")
        config = self._config_for("MP")
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(config)
        self.assertEqual(raw_bio_data, RawBioData())

    def test_missing_behaviour_raises_on_import(self):
        generate_dummy_foh_participant(self.output_folder, "MB", self.rng, "missing_behaviour")
        config = self._config_for("MB")
        with self.assertRaises(ValueError):
            ImportFohBehaviourDataStrategyStep().run(config)

    def test_missing_behaviour_still_completes_the_pipeline_with_errors_flagged(self):
        """Unlike missing_physiology/missing_target (see below), a missing VR_trial_events
        stream is caught by pipeline.py's per-step error containment -- run_pipeline() itself
        doesn't raise, it just flags every step downstream of behaviour import as ERROR.
        """
        generate_dummy_foh_participant(self.output_folder, "MB", self.rng, "missing_behaviour")
        pipeline_out = run_pipeline("MB", self.output_folder)
        status = pipeline_out.status.status
        self.assertEqual(status[RawBioData], ProcessingStatus.OK)
        for error_type in status:
            if error_type is RawBioData:
                continue
            self.assertEqual(status[error_type], ProcessingStatus.ERROR)

    def test_missing_target_raises_on_import(self):
        generate_dummy_foh_participant(self.output_folder, "MT", self.rng, "missing_target")
        config = self._config_for("MT")
        with self.assertRaises(KeyError):
            ImportFohTargetBehaviourDataStrategyStep().run(config)

    def test_missing_baseline_start_marker_still_resolves_via_fallback(self):
        """Drops VR_markers' event-10 sample but keeps the stream itself -- exercises
        BASELINE_START_FALLBACK_SPEC rather than the "no VR_markers stream at all" path
        (that path can't reach the fallback -- see foh_dummy_data.py's scenario docstring).
        """
        generate_dummy_foh_participant(
            self.output_folder, "MBSM", self.rng, "missing_baseline_start_marker"
        )
        pipeline_out = run_pipeline("MBSM", self.output_folder)
        self.assertTrue(
            all(status == ProcessingStatus.OK for status in pipeline_out.status.status.values())
        )

    def test_srate_mismatch_exceeds_crosscheck_threshold(self):
        result = generate_dummy_foh_participant(
            self.output_folder, "SR", self.rng, "srate_mismatch"
        )
        streams, _ = pyxdf.load_xdf(str(result.xdf_path))
        opensignals = next(s for s in streams if s["info"]["name"][0] == "OpenSignals")
        nominal = float(opensignals["info"]["nominal_srate"][0])
        effective = float(opensignals["info"]["effective_srate"])
        self.assertGreater(abs(nominal - effective) / nominal, SRATE_MISMATCH_THRESHOLD)

    def test_incomplete_target_trials_still_completes_the_pipeline(self):
        generate_dummy_foh_participant(
            self.output_folder, "ITT", self.rng, "incomplete_target_trials"
        )
        pipeline_out = run_pipeline("ITT", self.output_folder)
        self.assertTrue(
            all(status == ProcessingStatus.OK for status in pipeline_out.status.status.values())
        )
        self.assertFalse(pipeline_out.subject_df_out.empty)


class TestGenerateDummyFohDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_folder = Path(tempfile.mkdtemp())
        cls.results = generate_dummy_foh_dataset(
            cls.output_folder, n_clean=2, with_errors=True, seed=42
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.output_folder, ignore_errors=True)

    def test_generates_one_participant_per_clean_slot_and_error_type(self):
        scenarios = [result.scenario for result in self.results]
        self.assertEqual(scenarios.count("clean"), 2)
        for error_type in ERROR_TYPES:
            self.assertIn(error_type, scenarios)

    def test_writes_a_dummy_data_log(self):
        log_path = self.output_folder / DUMMY_DATA_LOG_FILENAME
        self.assertTrue(log_path.is_file())
        log_text = log_path.read_text(encoding="utf-8")
        for result in self.results:
            self.assertIn(result.subject_id, log_text)

    def test_is_reproducible_given_the_same_seed(self):
        other_folder = Path(tempfile.mkdtemp())
        try:
            other_results = generate_dummy_foh_dataset(
                other_folder, n_clean=2, with_errors=True, seed=42
            )
            first_xdf = next(r for r in self.results if r.subject_id == "DUMMY000").xdf_path
            second_xdf = next(r for r in other_results if r.subject_id == "DUMMY000").xdf_path
            self.assertEqual(first_xdf.read_bytes(), second_xdf.read_bytes())
        finally:
            shutil.rmtree(other_folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
