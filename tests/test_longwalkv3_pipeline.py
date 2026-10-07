import unittest
from pathlib import Path

import pandas as pd

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.longwalk3_behaviour import (
    ImportLongWalkV3BehaviourDataStrategyStep,
    ProcessLongWalkV3BehaviourDataStrategyStep,
    RawLongWalkV3BehaviourData,
)
from vrlab_toolbox.processing.longwalk3_bids import (
    build_longwalkv3_raw_session_events_behav_file_schema,
    combine_events_df_files,
    get_all_dfs,
)
from vrlab_toolbox.processing.longwalk3_debrief_behaviour import RawLongWalkV3DebriefBehaviourData
from vrlab_toolbox.processing.longwalk3_pipeline import (
    FindLongWalkV3ParticipantFilesStrategyStep,
)
from vrlab_toolbox.processing.longwalk3_trial_intervals import (
    LongWalkV3GetTrialIntervalStrategyStep,
)
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import TrialIntervals

BIDS_FOLDER = Path(r"longwalkv3_examples\\bids")
EXAMPLES_FOLDER = Path(r"longwalkv3_examples")
CLEAN_ID = "dummy01"

ALL_OK_STATUS_STR = PipelineStatus(
    status={
        RawLongWalkV3BehaviourData: ProcessingStatus.OK,
        RawLongWalkV3DebriefBehaviourData: ProcessingStatus.OK,
        RawBioData: ProcessingStatus.OK,
        TrialIntervals: ProcessingStatus.OK,
    }
).get_as_text()


class TestBidsConversion(unittest.TestCase):
    def test_combining_csv_files(self):
        dummy_data_folder = EXAMPLES_FOLDER
        subject_id_correct = CLEAN_ID
        df_list = get_all_dfs(subject_id_correct, dummy_data_folder)
        combined_df_list_out = combine_events_df_files(subject_id_correct, df_list)

        for df in combined_df_list_out.values():
            self.assertIsInstance(
                build_longwalkv3_raw_session_events_behav_file_schema().validate(df), pd.DataFrame
            )


class TestBasicDataHandling(unittest.TestCase):
    def setUp(self):
        self.good_config = FindLongWalkV3ParticipantFilesStrategyStep().run(CLEAN_ID, BIDS_FOLDER)

    def test_find_long_walk_v3_participant_strategy(self):
        good_config = FindLongWalkV3ParticipantFilesStrategyStep().run(CLEAN_ID, BIDS_FOLDER)
        self.assertIsInstance(good_config, ParticipantConfig)

    def test_good_raw_data_init_should_return_ok(self):
        raw_biodata = BiopacPhysiologyDataImportStartegy().run(self.good_config)
        self.assertIsInstance(raw_biodata, RawBioData)


class TestLongWalkV3BehaviourStrategy(unittest.TestCase):
    def setUp(self):
        self.config_list = [
            FindLongWalkV3ParticipantFilesStrategyStep(session_nr=session_nr).run(
                CLEAN_ID, BIDS_FOLDER
            )
            for session_nr in range(1, 3)
        ]

    def test_bids_behav_import(self):
        for config in self.config_list:
            raw_behaviour = ImportLongWalkV3BehaviourDataStrategyStep().run(config)
            build_longwalkv3_raw_session_events_behav_file_schema().validate(
                raw_behaviour.raw_behav_df
            )

    def test_long_walk_v3_process_behaviour(self):
        for config in self.config_list:
            raw_behaviour = ImportLongWalkV3BehaviourDataStrategyStep().run(config_in=config)
            processed = ProcessLongWalkV3BehaviourDataStrategyStep().run(config, raw_behaviour)
            self.assertEqual(processed.subject_df_out["Subject_ID"].iloc[0], CLEAN_ID)


class TestLongWalkV3(unittest.TestCase):
    def setUp(self):
        self.config_list = [
            FindLongWalkV3ParticipantFilesStrategyStep(session_nr=session_nr).run(
                CLEAN_ID, BIDS_FOLDER
            )
            for session_nr in range(1, 3)
        ]

        self.raw_behaviour_list = []
        self.raw_biodata_list = []

        for config in self.config_list:
            self.raw_biodata_list.append(BiopacPhysiologyDataImportStartegy().run(config))
            self.raw_behaviour_list.append(ImportLongWalkV3BehaviourDataStrategyStep().run(config))

    def test_longwalkv3_process_intervals_correctly(self):
        trial_interval_list = []
        for session in range(0, 2):
            trial_interval, _, _ = LongWalkV3GetTrialIntervalStrategyStep().run(
                self.raw_biodata_list[session], self.raw_behaviour_list[session]
            )
            trial_interval_list.append(trial_interval)
