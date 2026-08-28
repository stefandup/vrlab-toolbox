import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from mooi_toolbox.cli.mobi_FOH_process_batch import main as run_batch
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.foh_behaviour import (
    ImportFohBehaviourDataStrategyStep,
    RawFohBehaviourData,
)
from mooi_toolbox.processing.foh_pipeline import run_pipeline
from mooi_toolbox.processing.foh_target_behaviour import (
    FohRawTargetBehaviourData,
    ImportFohTargetBehaviourDataStrategyStep,
    ProcessFohTargetDataWithIntervalsStrategyStep,
)
from mooi_toolbox.processing.foh_trial_intervals import FohGetTrialIntervalStrategyStep
from mooi_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from mooi_toolbox.processing.lsl import FohLslPhysiologyDataImportStrategy
from mooi_toolbox.processing.output_data import PipelineOutputData
from mooi_toolbox.processing.processing_status import ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals

CORRECT_PARTICIPANT = "P00020"

# Real, gitignored data -- every test in this file needs this folder present locally and is
# expected to fail without it (no dummy/synthetic FOH dataset exists yet, unlike Crane).
DATA_FOLDER = Path(r"C:\Users\stefan\Participant Data Copy")


class TestFOHPipeline(unittest.TestCase):
    def setUp(self):
        self.participant_config = ParticipantConfig.from_lsl_data(
            CORRECT_PARTICIPANT, DATA_FOLDER, PhysiologyFileFormat.LSL
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
        pipeline_out = run_pipeline(self.participant_config.subject_id, DATA_FOLDER)
        self.assertTrue(pipeline_out)
        self.assertTrue(pipeline_out.figure_data_out["eda_qc"])
        self.assertTrue(pipeline_out.figure_data_out["Interval_qc"])
        self.assertEqual(pipeline_out.status.status[RawBioData], ProcessingStatus.OK)
        self.assertEqual(pipeline_out.status.status[RawFohBehaviourData], ProcessingStatus.OK)
        self.assertEqual(
            pipeline_out.status.status[FohRawTargetBehaviourData], ProcessingStatus.OK
        )
        self.assertEqual(pipeline_out.status.status[TrialIntervals], ProcessingStatus.OK)

    def test_batch_processing(self):
        with tempfile.TemporaryDirectory() as output_folder:
            result = CliRunner().invoke(run_batch, [str(DATA_FOLDER), output_folder])
        self.assertEqual(result.exit_code, 0, msg=result.output)


if __name__ == "__main__":
    unittest.main()
