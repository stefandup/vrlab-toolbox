import unittest
from pathlib import Path

from mooi_toolbox.processing.foh_behaviour import ImportFohBehaviourDataStrategyStep
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


# @unittest.skip("Busy")
class TestFOHPipeline(unittest.TestCase):
    def test_biodata_import_strategy(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = ParticipantConfig.from_lsl_data(
            "FOH",
            data_folder,
            PhysiologyFileFormat.LSL,
        )
        raw_bio_data_out = FohLslPhysiologyDataImportStrategy().run(participant_config)

        self.assertTrue(raw_bio_data_out)

    def test_foh_target_behav_import_strategy(self):

        data_folder = Path(r"local_lsl_data\\Participant Data")
        participant_config = ParticipantConfig.from_lsl_data(
            "FOH",
            data_folder,
            PhysiologyFileFormat.LSL,
        )

        raw_target_behav_data = ImportFohTargetBehaviourDataStrategyStep().run(participant_config)
        self.assertIsInstance(raw_target_behav_data, FohRawTargetBehaviourData)

    def test_foh_target_behav_processing_strategy(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = ParticipantConfig.from_lsl_data(
            "FOH",
            data_folder,
            PhysiologyFileFormat.LSL,
        )

        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(participant_config)
        raw_behav_data = ImportFohBehaviourDataStrategyStep().run(participant_config)
        trial_intervals, _, _ = FohGetTrialIntervalStrategyStep().run(raw_bio_data, raw_behav_data)

        raw_target_behav_data = ImportFohTargetBehaviourDataStrategyStep().run(participant_config)
        self.assertIsInstance(raw_target_behav_data, FohRawTargetBehaviourData)

        target_output = ProcessFohTargetDataWithIntervalsStrategyStep().run(
            participant_config, raw_target_behav_data, trial_intervals
        )
        self.assertIsInstance(target_output, PipelineOutputData)

    def test_physiology_data_import_strategy(self):
        pass

    def test_interval_get_strategy(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = ParticipantConfig.from_lsl_data(
            "P00015",
            data_folder,
            PhysiologyFileFormat.LSL,
        )

        raw_bio_data = FohLslPhysiologyDataImportStrategy().run(participant_config)
        # FohGetTrialIntervalStrategyStep().run(
        #    raw_bio_data,
        # )

    def test_basic_pipeline(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = ParticipantConfig.from_lsl_data(
            "00024",
            data_folder,
            PhysiologyFileFormat.LSL,
        )

        pipeline_data_out = run_pipeline(participant_config.subject_id, data_folder)
        self.assertTrue(pipeline_data_out)
