import unittest
from pathlib import Path

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.longwalk3_behaviour import (
    ImportLongWalkV3BehaviourDataStrategyStep,
    ProcessLongWalkV3BehaviourDataStrategyStep,
    RawLongWalkV3BehaviourData,
    build_long_walk_v3_raw_behav_file_schema,
)
from vrlab_toolbox.processing.longwalk3_debrief_behaviour import RawLongWalkV3DebriefBehaviourData
from vrlab_toolbox.processing.longwalk3_pipeline import (
    FindLongWalkV3ParticipantFilesStrategyStep,
    run_pipeline,
)
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import TrialIntervals

BIDS_FOLDER = Path(r"longwalkv3_examples\\longwalkv3_bids")
EXAMPLES_FOLDER = Path(r"longwalkv3_examples")
CLEAN_ID = "testEDA01"

ALL_OK_STATUS_STR = PipelineStatus(
    status={
        RawLongWalkV3BehaviourData: ProcessingStatus.OK,
        RawLongWalkV3DebriefBehaviourData: ProcessingStatus.OK,
        RawBioData: ProcessingStatus.OK,
        TrialIntervals: ProcessingStatus.OK,
    }
).get_as_text()


class TestBasicDataHandling(unittest.TestCase):
    def test_find_long_walk_v3_participant_strategy(self):
        good_config = FindLongWalkV3ParticipantFilesStrategyStep().run(CLEAN_ID, EXAMPLES_FOLDER)
        self.assertIsInstance(good_config, ParticipantConfig)

    def setUp(self):
        self.good_config = FindLongWalkV3ParticipantFilesStrategyStep().run(
            CLEAN_ID, EXAMPLES_FOLDER
        )

    def test_good_raw_data_init_should_return_ok(self):
        raw_biodata = BiopacPhysiologyDataImportStartegy().run(self.good_config)
        self.assertIsInstance(raw_biodata, RawBioData)


class TestLongWalkV3BehaviourStrategy(unittest.TestCase):
    def setUp(self):
        self.config = FindLongWalkV3ParticipantFilesStrategyStep().run(CLEAN_ID, EXAMPLES_FOLDER)

    def test_bids_behav_import(self):
        raw_behaviour = ImportLongWalkV3BehaviourDataStrategyStep().run(self.config)
        build_long_walk_v3_raw_behav_file_schema().validate(raw_behaviour.raw_behav_df)

    def test_long_walk_v3_process_behaviour(self):
        raw_behaviour = ImportLongWalkV3BehaviourDataStrategyStep().run(config_in=self.config)
        processed = ProcessLongWalkV3BehaviourDataStrategyStep().run(self.config, raw_behaviour)
        self.assertEqual(processed.subject_df_out["Subject_ID"].iloc[0], CLEAN_ID)


class TestLongWalkV3(unittest.TestCase):
    def test_crane_returns_ok_for_correct_interval_nr(self):
        pipeline_out = run_pipeline(CLEAN_ID, EXAMPLES_FOLDER)
        self.assertEqual(pipeline_out.status.status[TrialIntervals], ProcessingStatus.OK)
        status_str = pipeline_out.subject_df_out["Processing_Status"].iloc[0]
        self.assertEqual(sorted(status_str.split(" ")), sorted(ALL_OK_STATUS_STR.split(" ")))


class TestCranePipelineDummyData(unittest.TestCase):
    def test_crane_pipeline_has_expected_output(self):
        pipeline_out = run_pipeline(CLEAN_ID, EXAMPLES_FOLDER)
        pipeline_out.validate_participant_output()
        status_str = pipeline_out.subject_df_out["Processing_Status"].iloc[0]
        self.assertEqual(sorted(status_str.split(" ")), sorted(ALL_OK_STATUS_STR.split(" ")))
