import unittest
from mooi_toolbox.processing.crane_pipeline import run_pipeline, validate_participant_output
from mooi_toolbox.processing.crane_pipeline import CranePipelineInput, ProcessingStatus 

example_crane_participant_correct = CranePipelineInput(
    subject_id = "00020",
    biopac_fn = r"crane_data\\2026481120_00020_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

crane_participant_no_FILE = CranePipelineInput(
    subject_id = "00020",
    biopac_fn = r"crane_data\\NOFILE.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

crane_participant_no_BEHAV = CranePipelineInput(
    subject_id = "00020",
    biopac_fn = r"crane_data\\2026481120_00020_CraneOut.mat",
    behav_folder = r"NO_BEHAV_FOLDER",
    verbose = False,
    show_plots= False
)

example_incorrect_interval_nr = CranePipelineInput(
    subject_id = "00007",
    biopac_fn = r"crane_data\\2026371237_00007_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

example_correct_interval_nr = CranePipelineInput(
    subject_id="TESTa",
    biopac_fn = r"crane_data\\20262121130_TESTa_CraneOut.mat",
    behav_folder = r"crane_data",
    verbose = False,
    show_plots= False
)

class TestCranePipeline(unittest.TestCase):

    def test_crane_pipeline_has_expected_output(self):
        pipeline_out = run_pipeline(example_crane_participant_correct)
        data_frame_out = pipeline_out.subject_df_out
        validate_participant_output(data_frame_out)


    def test_crane_pipeline_labels_missing_file_correctly(self):

        pipeline_out = run_pipeline(crane_participant_no_FILE)
        self.assertEqual(pipeline_out.status,ProcessingStatus.ERROR)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                ProcessingStatus.ERROR.value
                )

    def test_crane_pipeline_labels_missing_behav_correctly(self):

        pipeline_out = run_pipeline(crane_participant_no_BEHAV)
        self.assertEqual(pipeline_out.status,ProcessingStatus.PARTIAL)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                ProcessingStatus.PARTIAL.value
                )

    def test_crane_returns_error_for_incorrect_interval_nr(self):
        pipeline_out = run_pipeline(example_incorrect_interval_nr)
        self.assertEqual(pipeline_out.status,ProcessingStatus.ERROR)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                ProcessingStatus.ERROR.value
                )

    def test_crane_returns_ok_for_correct_interval_nr(self):
        pipeline_out = run_pipeline(example_correct_interval_nr)
        self.assertEqual(pipeline_out.status,ProcessingStatus.OK)
        self.assertEqual(
                pipeline_out.subject_df_out["Processing_Status"].iloc[0],
                ProcessingStatus.OK.value
                )