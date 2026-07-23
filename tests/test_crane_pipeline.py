import unittest

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.biopac import BiopacDataImportStartegy
from mooi_toolbox.processing.crane_behaviour import (
    ImportCraneBehaviourDataStrategyStep,
    ProcessCraneBehaviourDataStrategyStep,
    RawCraneBehaviourData,
    build_crane_raw_behav_file_schema,
)
from mooi_toolbox.processing.crane_pipeline import run_pipeline
from mooi_toolbox.processing.crane_trial_intervals import CraneGetTrialIntervalStrategyStep
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus

example_crane_participant_correct = ParticipantConfig(
    subject_id="00020",
    physiology_fn=r"crane_data\\2026481120_00020_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

crane_participant_no_FILE = ParticipantConfig(
    subject_id="00020",
    physiology_fn=r"crane_data\\NOFILE.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

crane_participant_no_BEHAV = ParticipantConfig(
    subject_id="00020",
    physiology_fn=r"crane_data\\2026481120_00020_CraneOut.mat",
    behav_folder=r"NO_BEHAV_FOLDER",
    verbose=False,
    show_plots=False,
)

example_incorrect_interval_nr = ParticipantConfig(
    subject_id="00007",
    physiology_fn=r"crane_data\\2026371237_00007_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

example_correct_interval_nr = ParticipantConfig(
    subject_id="TESTa",
    physiology_fn=r"crane_data\\20262121130_TESTa_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

example_long_delay = ParticipantConfig(
    subject_id="00011",
    physiology_fn=r"crane_data\\2026325120_00011_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

example_incorrect_very_short_trigger = ParticipantConfig(
    subject_id="00006",
    physiology_fn=r"crane_data\\202637138_00006_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

example_incorrect_medium_short_trigger = ParticipantConfig(
    subject_id="PID16407",
    physiology_fn=r"crane_data\\20265221116_PID16407_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

crane_participant_no_debrief = ParticipantConfig(
    subject_id="PID8495",
    physiology_fn=r"crane_data\\2026651331_PID8495_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

crane_participant_incorrect_date = ParticipantConfig(
    subject_id="PID15868",
    physiology_fn=r"crane_data\\20265121237_PID15868_CraneOut.mat",
    behav_folder=r"crane_data",
    verbose=False,
    show_plots=False,
)

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
    def test_interval_correction_with_correct_intervals(self):
        raw_bio_data = BiopacDataImportStartegy().run(example_crane_participant_correct)
        raw_behav_data = ImportCraneBehaviourDataStrategyStep().run(
            example_crane_participant_correct
        )
        trial_intervals, interval_figure_out, interval_pipeline_status = (
            CraneGetTrialIntervalStrategyStep().run(raw_bio_data, raw_behav_data)
        )
        print("Done!")

    def test_interval_correction_with_missing_initial_trigger_tp(self):
        # PID16186
        pass

    def test_interval_correction_with_initial_double_trigger(self):
        # PID16407
        pass

    def test_interval_correction_with_double_trigger_and_missing_init_tp(self):
        # PID5753 and PID4572
        pass

    def test_interval_correction_with_missing_last_and_initial_triggers(self):
        # PID16230
        pass

    def test_interval_correction_with_multiple_double_triggers(self):
        # PID9188 and PID7177(worse!)
        pass


class TestBehaviourClassWithBiopacData(unittest.TestCase):
    def test_biopac_behav_import(self):
        correct_behaviour = RawCraneBehaviourData.load_from_config(
            example_crane_participant_correct
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
    def test_good_raw_data_init_should_return_ok(self):
        raw_biodata_good: RawBioData = BiopacDataImportStartegy().run(
            example_crane_participant_correct
        )
        self.assertIsInstance(raw_biodata_good, RawBioData)

    def test_no_data_should_return_error(self):
        with self.assertRaises(FileNotFoundError):
            BiopacDataImportStartegy().run(crane_participant_no_FILE)


class TestCraneBehaviourStrategy(unittest.TestCase):
    def test_crane_process_behaviour(self):
        import_strategy = ImportCraneBehaviourDataStrategyStep()
        process_strategy = ProcessCraneBehaviourDataStrategyStep()
        raw_behaviour_data = import_strategy.run(config_in=example_crane_participant_correct)
        crane_behav_output_data = process_strategy.run(
            example_crane_participant_correct, raw_behaviour_data
        )
        self.assertEqual(crane_behav_output_data.subject_df_out["Subject_ID"].iloc[0], "00020")


class TestCranePipeline(unittest.TestCase):
    def test_crane_pipeline_has_expected_output(self):
        pipeline_out = run_pipeline(example_crane_participant_correct)
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
        pipeline_out = run_pipeline(crane_participant_no_FILE)
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

        pipeline_out = run_pipeline(crane_participant_no_BEHAV)
        self.assertEqual(pipeline_out.status.behaviour, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], physiology_and_behav_error
        )

    def test_crane_missing_debrief_correct_label(self):

        pipeline_out = run_pipeline(crane_participant_no_debrief)
        self.assertEqual(pipeline_out.status.behaviour, ProcessingStatus.ERROR)
        self.assertEqual(pipeline_out.subject_df_out["Processing_Status"].iloc[0], missing_debrief)

    def test_crane_corrects_error_for_incorrect_interval_nr(self):

        pipeline_out = run_pipeline(example_incorrect_interval_nr)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], corrected_interval_str
        )

    def test_crane_spots_errors_when_behav_physiology_no_match(self):
        pipeline_out = run_pipeline(crane_participant_incorrect_date)
        self.assertEqual(pipeline_out.subject_df_out["Processing_Status"].iloc[0], dates_no_match)

    def test_crane_returns_ok_for_correct_interval_nr(self):
        pipeline_out = run_pipeline(example_crane_participant_correct)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.OK)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], all_ok_status_str
        )

    def test_crane_handles_long_delay_time(self):
        """Currently no error with excessive delays"""
        pipeline_out = run_pipeline(example_long_delay)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.OK)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], all_ok_status_str
        )

    def test_crane_handles_very_short_triggers(self):
        pipeline_out = run_pipeline(example_incorrect_very_short_trigger)
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

        pipeline_out = run_pipeline(example_incorrect_medium_short_trigger)
        self.assertEqual(pipeline_out.status.intervals, ProcessingStatus.ERROR)
        self.assertEqual(
            pipeline_out.subject_df_out["Processing_Status"].iloc[0], corrected_interval_str
        )
