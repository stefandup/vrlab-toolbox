import unittest
from pandas import DataFrame

from mooi_toolbox.processing.crane_pipeline import run_pipeline, validate_participant_output
from mooi_toolbox.processing.crane_pipeline import CranePipelineInput as ExampleCraneParticipant

class TestCranePipeline(unittest.TestCase):

    def test_crane_pipeline_has_expected_output(self):
        pipeline_out = run_pipeline(ExampleCraneParticipant)
        data_frame_out = pipeline_out.subject_df_out
        validate_participant_output(data_frame_out)

    def test_crane_validation_rejects_empty_output(self):
        bad_df = DataFrame()
        validate_participant_output(bad_df)

    def test_crane_pipeline_labels_missing_data_correctly(self):
        with self.assertRaises(FileNotFoundError):
            run_pipeline(ExampleCraneParticipant(subject_id="NO_ID"))
            run_pipeline(ExampleCraneParticipant(biopac_fn="NO_FILE"))
