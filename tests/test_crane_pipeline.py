import unittest
from pathlib import Path

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.biopac import BiopacDataImportStartegy
from mooi_toolbox.processing.crane_behaviour import (
    ImportCraneBehaviourDataStrategyStep,
    ProcessCraneBehaviourDataStrategyStep,
    RawCraneBehaviourData,
    build_crane_raw_behav_file_schema,
)
from mooi_toolbox.processing.crane_pipeline import (
    FindCraneParticipantFilesStrategyStep,
    run_pipeline,
)
from mooi_toolbox.processing.crane_trial_intervals import CraneGetTrialIntervalStrategyStep
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals

data_folder = Path(r"crane_data\\")

EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID = "00020"
CRANE_PARTICIPANT_NO_FILE_ID = "NOFILES"
CRANE_PARTICIPANT_NO_BEHAV_BAD_DATE_ID = "PID11136"
EXAMPLE_INCORRECT_INTERVAL_NR_ID = "00007"
EXAMPLE_LONG_DELAY_ID = "00011"
EXAMPLE_INCORRECT_VERY_SHORT_TRIGGER_ID = "00006"
EXAMPLE_INCORRECT_MEDIUM_SHORT_TRIGGER_ID = "PID16407"
CRANE_PARTICIPANT_NO_DEBRIEF_ID = "PID8495"
CRANE_PARTICIPANT_INCORRECT_DATE_ID = "PID15868"

corrected_interval_str = PipelineStatus(
    data_in=ProcessingStatus.OK,
    behaviour=ProcessingStatus.OK,
    intervals=ProcessingStatus.ERROR,
    physiology=ProcessingStatus.OK,
).get_as_text()

all_ok_status_str = PipelineStatus(
    data_in=ProcessingStatus.OK,
    behaviour=ProcessingStatus.OK,
    intervals=ProcessingStatus.OK,
    physiology=ProcessingStatus.OK,
).get_as_text()

missing_debrief = PipelineStatus(
    data_in=ProcessingStatus.ERROR,
    physiology=ProcessingStatus.OK,
    behaviour=ProcessingStatus.ERROR,
    intervals=ProcessingStatus.OK,
).get_as_text()

dates_no_match = PipelineStatus(
    data_in=ProcessingStatus.ERROR,
    physiology=ProcessingStatus.ERROR,
    behaviour=ProcessingStatus.ERROR,
    intervals=ProcessingStatus.ERROR,
).get_as_text()


class TestCraneIntervalQC(unittest.TestCase):
    def test_graph_output(self):
        # plot_biopac_interval_qc(example_crane_participant_correct)
        pass


class TestCraneGetIntervalStrategy(unittest.TestCase):
    def setUp(self):
        self.example_crane_participant_correct = FindCraneParticipantFilesStrategyStep().run(
            EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID, data_folder
        )

    def _run_interval_strategy_for(self, subject_id: str) -> TrialIntervals:
        participant_config = FindCraneParticipantFilesStrategyStep().run(subject_id, data_folder)
        raw_bio_data = BiopacDataImportStartegy().run(participant_config)
        raw_behav_data = ImportCraneBehaviourDataStrategyStep().run(participant_config)
        trial_intervals, interval_figure_out, interval_pipeline_status = (
            CraneGetTrialIntervalStrategyStep().run(raw_bio_data, raw_behav_data)
        )
        print(subject_id, interval_pipeline_status)
        return trial_intervals

    def test_interval_correction_with_correct_intervals(self):
        self.assertTrue(
            self._run_interval_strategy_for(EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID).intervals
        )

    def test_interval_correction_with_missing_initial_trigger_tp(self):
        MISSING_INITIAL_TRIGGER = "PID16186"
        self.assertTrue(self._run_interval_strategy_for(MISSING_INITIAL_TRIGGER).intervals)

    def test_interval_correction_with_initial_double_trigger(self):
        INITIAL_DOUBLE_TRIGGER = "PID16407"
        self.assertTrue(self._run_interval_strategy_for(INITIAL_DOUBLE_TRIGGER).intervals)

    def test_interval_correction_with_double_trigger_and_missing_init_tp_nr1(self):
        MISSING_TRIGGER_AND_INIT_TP_1 = "PID5753"

        self.assertTrue(self._run_interval_strategy_for(MISSING_TRIGGER_AND_INIT_TP_1).intervals)

    def test_shifting_algorithm_for_missing_first_last_tp(self):
        MISSING_INIT_AND_LAST_TP = "PID1267"
        self.assertTrue(self._run_interval_strategy_for(MISSING_INIT_AND_LAST_TP).intervals)

    def test_interval_correction_with_double_trigger_and_missing_init_tp_nr2(self):

        MISSING_TRIGGER_AND_INIT_TP_2 = "PID4572"

        self.assertTrue(self._run_interval_strategy_for(MISSING_TRIGGER_AND_INIT_TP_2).intervals)

    def test_interval_correction_with_missing_last_and_initial_triggers(self):
        MISSING_LAST_AND_INITIAL_TRIGGERS = "PID16230"
        self.assertTrue(
            self._run_interval_strategy_for(MISSING_LAST_AND_INITIAL_TRIGGERS).intervals
        )

    def test_interval_correction_with_multiple_double_triggers_1(self):
        MULTIPLE_DOUBLE_TRIGGERS_1 = "PID9188"
        self.assertTrue(self._run_interval_strategy_for(MULTIPLE_DOUBLE_TRIGGERS_1).intervals)

    def test_interval_correction_with_multiple_double_triggers_2(self):
        MULTIPLE_DOUBLE_TRIGGERS_2 = "PID7177"  # worse!
        self.assertTrue(self._run_interval_strategy_for(MULTIPLE_DOUBLE_TRIGGERS_2).intervals)


class TestBehaviourClassWithBiopacData(unittest.TestCase):
    def setUp(self):
        self.example_crane_participant_correct = FindCraneParticipantFilesStrategyStep().run(
            EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID, data_folder
        )

    def test_biopac_behav_import(self):
        correct_behaviour = RawCraneBehaviourData.load_from_config(
            self.example_crane_participant_correct
        )
        build_crane_raw_behav_file_schema().validate(correct_behaviour.raw_behav_df)

    def test_behaviour_processing_strategy(self):
        pass


class TestParticipantConfigFileHandling(unittest.TestCase):
    def test_detection_of_missing_behav_file(self):
        pass

    def test_finds_and_populates_config_file_correctly(self):
        pass


class TestBasicDataHandling(unittest.TestCase):
    def setUp(self):
        self.example_crane_participant_correct = FindCraneParticipantFilesStrategyStep().run(
            EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID, data_folder
        )
        self.crane_participant_no_FILE = FindCraneParticipantFilesStrategyStep().run(
            CRANE_PARTICIPANT_NO_FILE_ID, data_folder
        )

    def test_good_raw_data_init_should_return_ok(self):
        raw_biodata_good: RawBioData = BiopacDataImportStartegy().run(
            self.example_crane_participant_correct
        )
        self.assertIsInstance(raw_biodata_good, RawBioData)

    def test_no_data_should_return_error(self):
        with self.assertRaises(FileNotFoundError):
            BiopacDataImportStartegy().run(self.crane_participant_no_FILE)


class TestCraneBehaviourStrategy(unittest.TestCase):
    def setUp(self):
        self.example_crane_participant_correct = FindCraneParticipantFilesStrategyStep().run(
            EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID, data_folder
        )

    def test_crane_process_behaviour(self):
        import_strategy = ImportCraneBehaviourDataStrategyStep()
        process_strategy = ProcessCraneBehaviourDataStrategyStep()
        raw_behaviour_data = import_strategy.run(config_in=self.example_crane_participant_correct)
        crane_behav_output_data = process_strategy.run(
            self.example_crane_participant_correct, raw_behaviour_data
        )
        self.assertEqual(crane_behav_output_data.subject_df_out["Subject_ID"].iloc[0], "00020")


class TestCranePipeline(unittest.TestCase):
    def test_crane_pipeline_has_expected_output(self):
        pipeline_out = run_pipeline(
            EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID,
            data_folder,
        )
        pipeline_out.validate_participant_output()
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], all_ok_status_str
        )

    def test_crane_pipeline_labels_missing_physiology_correctly(self):
        input_processing_status = PipelineStatus(
            data_in=ProcessingStatus.ERROR,
            behaviour=ProcessingStatus.OK,
            intervals=ProcessingStatus.ERROR,
            physiology=ProcessingStatus.ERROR,
        ).get_as_text()
        pipeline_out = run_pipeline(CRANE_PARTICIPANT_NO_FILE_ID, data_folder)
        self.assertEqual(pipeline_out.status.data_in, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], input_processing_status
        )

    def test_crane_pipeline_labels_missing_behav_correctly(self):
        physiology_and_behav_error = PipelineStatus(
            data_in=ProcessingStatus.ERROR,
            physiology=ProcessingStatus.ERROR,
            behaviour=ProcessingStatus.ERROR,
            intervals=ProcessingStatus.ERROR,
        ).get_as_text()

        pipeline_out = run_pipeline(CRANE_PARTICIPANT_NO_BEHAV_BAD_DATE_ID, data_folder)
        self.assertEqual(pipeline_out.status.behaviour, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], physiology_and_behav_error
        )

    def test_crane_missing_debrief_correct_label(self):

        pipeline_out = run_pipeline(CRANE_PARTICIPANT_NO_DEBRIEF_ID, data_folder)
        self.assertEqual(pipeline_out.status.behaviour, ProcessingStatus.ERROR)
        self.assertEqual(pipeline_out.subject_df_out["Processing_Status"].iloc[0], missing_debrief)

    def test_crane_corrects_error_for_incorrect_interval_nr(self):

        pipeline_out = run_pipeline(EXAMPLE_INCORRECT_INTERVAL_NR_ID, data_folder)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], corrected_interval_str
        )

    def test_crane_spots_errors_when_behav_physiology_no_match(self):
        pipeline_out = run_pipeline(CRANE_PARTICIPANT_INCORRECT_DATE_ID, data_folder)
        self.assertEqual(pipeline_out.subject_df_out["Processing_Status"].iloc[0], dates_no_match)

    def test_crane_returns_ok_for_correct_interval_nr(self):
        pipeline_out = run_pipeline(EXAMPLE_CRANE_PARTICIPANT_CORRECT_ID, data_folder)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.OK)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], all_ok_status_str
        )

    def test_crane_handles_long_delay_time(self):
        """Currently no error with excessive delays"""
        pipeline_out = run_pipeline(EXAMPLE_LONG_DELAY_ID, data_folder)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.OK)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], all_ok_status_str
        )

    def test_crane_handles_very_short_triggers(self):
        pipeline_out = run_pipeline(EXAMPLE_INCORRECT_VERY_SHORT_TRIGGER_ID, data_folder)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], corrected_interval_str
        )

    def test_crane_handles_medium_short_triggers(self):
        corrected_interval_str = PipelineStatus(
            data_in=ProcessingStatus.ERROR,  # Also has missing debrief...
            behaviour=ProcessingStatus.ERROR,
            intervals=ProcessingStatus.ERROR,
            physiology=ProcessingStatus.OK,
        ).get_as_text()

        pipeline_out = run_pipeline(EXAMPLE_INCORRECT_MEDIUM_SHORT_TRIGGER_ID, data_folder)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], corrected_interval_str
        )
