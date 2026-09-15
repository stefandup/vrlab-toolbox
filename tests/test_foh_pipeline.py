import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from vrlab_toolbox.cli.mobi_FOH_process_batch import run_batch as run_batch_fn
from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.foh_behaviour import (
    ImportFohBehaviourDataStrategyStep,
    RawFohBehaviourData,
)
from vrlab_toolbox.processing.foh_dummy_data import generate_dummy_foh_participant
from vrlab_toolbox.processing.foh_pipeline import run_pipeline
from vrlab_toolbox.processing.foh_target_behaviour import (
    FohRawTargetBehaviourData,
    ImportFohTargetBehaviourDataStrategyStep,
    ProcessFohTargetDataWithIntervalsStrategyStep,
)
from vrlab_toolbox.processing.foh_trial_intervals import FohGetTrialIntervalStrategyStep
from vrlab_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from vrlab_toolbox.processing.lsl import FohLslPhysiologyDataImportStrategy
from vrlab_toolbox.processing.output_data import PipelineOutputData
from vrlab_toolbox.processing.processing_status import ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import TrialIntervals

DUMMY_PARTICIPANT = "DUMMY"


class TestFOHPipelineDummyData(unittest.TestCase):
    """Self-contained: builds its own synthetic FOH recording via foh_dummy_data.py rather
    than reading real, gitignored data -- see TestFOHPipelineRealData below for the
    real-data-dependent counterpart these tests were split out of. Runs anywhere, no local
    data folder required. See tests/test_foh_dummy_data.py for generator-focused tests
    (error scenarios, XDF round-tripping) -- this class only covers the clean/happy path,
    exercised here at the strategy-step granularity that predates the dummy data generator.
    """

    @classmethod
    def setUpClass(cls):
        cls.data_folder = Path(tempfile.mkdtemp())
        generate_dummy_foh_participant(
            cls.data_folder, DUMMY_PARTICIPANT, np.random.default_rng(42)
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.data_folder, ignore_errors=True)

    def test_load_lsl_config_data(self):
        participant_config = ParticipantConfig.from_lsl_data(
            DUMMY_PARTICIPANT, self.data_folder, PhysiologyFileFormat.LSL
        )
        self.assertIsInstance(participant_config, ParticipantConfig)

    def setUp(self):
        self.participant_config = ParticipantConfig.from_lsl_data(
            DUMMY_PARTICIPANT, self.data_folder, PhysiologyFileFormat.LSL
        )

    def test_physiology_data_import_strategy(self):
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(self.participant_config)
        self.assertIsInstance(raw_bio_data, RawBioData)

    def test_foh_target_behav_import_strategy(self):
        raw_target_behav_data = ImportFohTargetBehaviourDataStrategyStep().run(
            self.participant_config
        )
        self.assertIsInstance(raw_target_behav_data, FohRawTargetBehaviourData)

    def test_foh_target_behav_processing_strategy(self):
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(self.participant_config)
        raw_behav_data = ImportFohBehaviourDataStrategyStep().run(self.participant_config)
        trial_intervals, _, _ = FohGetTrialIntervalStrategyStep().run(raw_bio_data, raw_behav_data)

        raw_target_behav_data = ImportFohTargetBehaviourDataStrategyStep().run(
            self.participant_config
        )
        target_output = ProcessFohTargetDataWithIntervalsStrategyStep().run(
            self.participant_config, raw_target_behav_data, trial_intervals
        )
        self.assertIsInstance(target_output, PipelineOutputData)

    def test_interval_get_strategy(self):
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(self.participant_config)
        raw_behav_data = ImportFohBehaviourDataStrategyStep().run(self.participant_config)
        trial_intervals, _, status = FohGetTrialIntervalStrategyStep().run(
            raw_bio_data, raw_behav_data
        )
        self.assertEqual(status.status[type(trial_intervals)], ProcessingStatus.OK)
        self.assertTrue(trial_intervals)

    def test_basic_foh_pipeline(self):
        pipeline_out = run_pipeline(self.participant_config.subject_id, self.data_folder)
        self.assertTrue(pipeline_out)
        self.assertTrue(pipeline_out.figure_data_out["eda_qc"])
        self.assertTrue(pipeline_out.figure_data_out["Interval_qc"])
        self.assertEqual(pipeline_out.status.status[RawBioData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[RawFohBehaviourData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[FohRawTargetBehaviourData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[TrialIntervals], ProcessingStatus.OK)

    def test_foh_batch_processing(self):
        # Calls run_batch() directly rather than through CliRunner: run_batch() calls
        # mobi_logging.init() itself (unlike crane's batch CLI, which only does that under
        # `if __name__ == "__main__"`), and that combination with rich's Progress and
        # pytest's own log-capturing trips a known click.testing/pytest stdout-capture
        # interaction ("I/O operation on closed file") that has nothing to do with what
        # this test is actually checking (that a mixed clean/broken dataset doesn't crash
        # the whole batch).
        output_folder = Path(tempfile.mkdtemp())
        try:
            csv_path = run_batch_fn(self.data_folder, output_folder)
        finally:
            # mobi_logging.init() (called by run_batch()) leaves output_folder/logs/*.log open
            # for the rest of the process, which blocks a plain rmtree on Windows.
            shutil.rmtree(output_folder, ignore_errors=True)
        self.assertIsNotNone(csv_path)


CORRECT_PARTICIPANT = "P00020"

# Real, gitignored data -- every test in this class needs this folder present locally and is
# expected to fail without it. See TestFOHPipelineDummyData above for the self-contained
# equivalent that runs anywhere, via foh_dummy_data.py.
BIDS_FOLDER = Path(r"foh_data_copy\foh_bids_test")


class TestFOHPipelineRealData(unittest.TestCase):
    def test_load_lsl_config_data(self):
        participant_config = ParticipantConfig.from_lsl_data(
            CORRECT_PARTICIPANT, BIDS_FOLDER, PhysiologyFileFormat.LSL
        )
        self.assertIsInstance(participant_config, ParticipantConfig)

    def setUp(self):
        self.participant_config = ParticipantConfig.from_lsl_data(
            CORRECT_PARTICIPANT, BIDS_FOLDER, PhysiologyFileFormat.LSL
        )

    def test_physiology_data_import_strategy(self):
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(self.participant_config)
        self.assertIsInstance(raw_bio_data, RawBioData)

    def test_foh_target_behav_import_strategy(self):
        raw_target_behav_data = ImportFohTargetBehaviourDataStrategyStep().run(
            self.participant_config
        )
        self.assertIsInstance(raw_target_behav_data, FohRawTargetBehaviourData)

    def test_foh_target_behav_processing_strategy(self):
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(self.participant_config)
        raw_behav_data = ImportFohBehaviourDataStrategyStep().run(self.participant_config)
        trial_intervals, _, _ = FohGetTrialIntervalStrategyStep().run(raw_bio_data, raw_behav_data)

        raw_target_behav_data = ImportFohTargetBehaviourDataStrategyStep().run(
            self.participant_config
        )
        target_output = ProcessFohTargetDataWithIntervalsStrategyStep().run(
            self.participant_config, raw_target_behav_data, trial_intervals
        )
        self.assertIsInstance(target_output, PipelineOutputData)

    def test_interval_get_strategy(self):
        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(self.participant_config)
        raw_behav_data = ImportFohBehaviourDataStrategyStep().run(self.participant_config)
        trial_intervals, _, status = FohGetTrialIntervalStrategyStep().run(
            raw_bio_data, raw_behav_data
        )
        self.assertEqual(status.status[type(trial_intervals)], ProcessingStatus.OK)
        self.assertTrue(trial_intervals)

    def test_basic_foh_pipeline(self):
        pipeline_out = run_pipeline(self.participant_config.subject_id, BIDS_FOLDER)
        self.assertTrue(pipeline_out)
        self.assertTrue(pipeline_out.figure_data_out["eda_qc"])
        self.assertTrue(pipeline_out.figure_data_out["Interval_qc"])
        self.assertEqual(pipeline_out.status.status[RawBioData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[RawFohBehaviourData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[FohRawTargetBehaviourData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[TrialIntervals], ProcessingStatus.OK)

    def test_foh_batch_processing(self):
        # See TestFOHPipelineDummyData.test_foh_batch_processing: run_batch() is called
        # directly rather than through CliRunner, to avoid a click.testing/pytest stdout
        # capture interaction ("I/O operation on closed file") triggered by run_batch()
        # calling mobi_logging.init() itself, unrelated to what this test actually checks.
        output_folder = Path(tempfile.mkdtemp())
        try:
            csv_path = run_batch_fn(BIDS_FOLDER, output_folder)
        finally:
            shutil.rmtree(output_folder, ignore_errors=True)
        self.assertIsNotNone(csv_path)


if __name__ == "__main__":
    unittest.main()
