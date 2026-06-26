import unittest
from mooi_toolbox.processing.biopac import BiopacRawData
from mooi_toolbox.processing.crane_pipeline import run_pipeline, validate_participant_output
from mooi_toolbox.processing.crane_pipeline import ProcessingStatus , PipelineStatus
from mooi_toolbox.processing.input_data import PipelineInput

example_crane_participant_correct = PipelineInput(
    subject_id = "00020",
    biopac_fn = r"crane_data\\2026481120_00020_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

crane_participant_no_FILE = PipelineInput(
    subject_id = "00020",
    biopac_fn = r"crane_data\\NOFILE.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

crane_participant_no_BEHAV = PipelineInput(
    subject_id = "00020",
    biopac_fn = r"crane_data\\2026481120_00020_CraneOut.mat",
    behav_folder = r"NO_BEHAV_FOLDER",
    verbose = False,
    show_plots= False
)

example_incorrect_interval_nr = PipelineInput(
    subject_id = "00007",
    biopac_fn = r"crane_data\\2026371237_00007_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

example_correct_interval_nr = PipelineInput(
    subject_id="TESTa",
    biopac_fn = r"crane_data\\20262121130_TESTa_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

example_long_delay = PipelineInput(
        subject_id="00011",
    biopac_fn = r"crane_data\\2026325120_00011_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

example_incorrect_very_short_trigger = PipelineInput(
    subject_id = "00006",
    biopac_fn = r"crane_data\\202637138_00006_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

example_incorrect_medium_short_trigger= PipelineInput(
    subject_id = "PID16407",
    biopac_fn = r"crane_data\\20265221116_PID16407_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

crane_participant_no_debrief = PipelineInput(
    subject_id = "PID15868",
    biopac_fn = r"crane_data\\20265121237_PID15868_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)


corrected_interval_str = PipelineStatus(data_in=ProcessingStatus.OK,
                            behaviour=ProcessingStatus.OK,
                            debrief=ProcessingStatus.OK,
                            intervals=ProcessingStatus.CORRECTED,
                            physiology=ProcessingStatus.OK
                            ).get_as_text()

all_ok_status_str = PipelineStatus(data_in=ProcessingStatus.OK,
                                   behaviour=ProcessingStatus.OK,
                                   debrief=ProcessingStatus.OK,
                                   intervals=ProcessingStatus.OK,
                                   physiology=ProcessingStatus.OK
                                   ).get_as_text()

class TestBasicDataHandling(unittest.TestCase):

    def test_good_raw_data_init_should_return_ok(self):
        raw_biodata_good : BiopacRawData = BiopacRawData.load_data(example_crane_participant_correct)
        self.assertIsInstance(raw_biodata_good,BiopacRawData)

        with self.assertRaises(FileNotFoundError):
            BiopacRawData.load_data(crane_participant_no_FILE)
                
class TestCranePipeline(unittest.TestCase):

    def test_crane_pipeline_has_expected_output(self):
        pipeline_out = run_pipeline(example_crane_participant_correct)
        data_frame_out = pipeline_out.subject_df_out
        validate_participant_output(data_frame_out)


    def test_crane_pipeline_labels_missing_file_correctly(self):
        input_processing_status = PipelineStatus(data_in=ProcessingStatus.ERROR).get_as_text()
        pipeline_out = run_pipeline(crane_participant_no_FILE)
        self.assertEqual(pipeline_out.status.data_in,ProcessingStatus.ERROR)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                input_processing_status
                )

    def test_crane_pipeline_labels_missing_behav_correctly(self):
        physiology_and_behav_error = PipelineStatus(
            data_in=ProcessingStatus.OK,
            physiology=ProcessingStatus.ERROR,
            behaviour=ProcessingStatus.ERROR,
            intervals=ProcessingStatus.OK,
            debrief=ProcessingStatus.ERROR
            ).get_as_text()
        
        pipeline_out = run_pipeline(crane_participant_no_BEHAV)
        self.assertEqual(pipeline_out.status.debrief,ProcessingStatus.ERROR)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                physiology_and_behav_error
                )

    def test_crane_missing_debrief_correct_label(self):

        missing_debrief = PipelineStatus(
            data_in=ProcessingStatus.OK,
            physiology=ProcessingStatus.OK,
            behaviour=ProcessingStatus.OK,
            intervals=ProcessingStatus.OK,
            debrief=ProcessingStatus.ERROR
            ).get_as_text()
        
        pipeline_out = run_pipeline(crane_participant_no_debrief)
        self.assertEqual(pipeline_out.status.debrief,ProcessingStatus.ERROR)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                missing_debrief
                )
        
    def test_crane_corrects_error_for_incorrect_interval_nr(self):

        pipeline_out = run_pipeline(example_incorrect_interval_nr)
        self.assertEqual(pipeline_out.status.intervals,ProcessingStatus.CORRECTED)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                corrected_interval_str
                )

    def test_crane_returns_ok_for_correct_interval_nr(self):
        pipeline_out = run_pipeline(example_correct_interval_nr)
        self.assertEqual(pipeline_out.status.intervals,ProcessingStatus.OK)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                'data_in=ok behaviour=ok debrief=error intervals=ok physiology=ok'
                )
        
    def test_crane_handles_long_delay_time(self):
        '''Currently no error with excessive delays'''
        pipeline_out = run_pipeline(example_long_delay)
        self.assertEqual(pipeline_out.status.intervals,ProcessingStatus.OK)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                all_ok_status_str
                )

    def test_crane_handles_very_short_triggers(self):
        pipeline_out = run_pipeline(example_incorrect_very_short_trigger)
        self.assertEqual(pipeline_out.status.intervals,ProcessingStatus.CORRECTED)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                corrected_interval_str
                )
        
    def test_crane_handles_medium_short_triggers(self):
        corrected_interval_str = PipelineStatus(data_in=ProcessingStatus.OK,
                            behaviour=ProcessingStatus.OK,
                            debrief=ProcessingStatus.ERROR,
                            intervals=ProcessingStatus.CORRECTED,
                            physiology=ProcessingStatus.OK
                            ).get_as_text()

        pipeline_out = run_pipeline(example_incorrect_medium_short_trigger)
        self.assertEqual(pipeline_out.status.intervals,ProcessingStatus.CORRECTED)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                corrected_interval_str
                )
