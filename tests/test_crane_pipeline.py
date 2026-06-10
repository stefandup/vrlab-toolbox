import unittest
from pandas import DataFrame

from mooi_toolbox.processing.crane_pipeline import run_pipeline, validate_participant_output
from mooi_toolbox.processing.crane_pipeline import CranePipelineInput as ExampleCraneParticipant

class TestCranePipeline(unittest.TestCase):

    def test_crane_pipeline_has_expected_output(self):
        data_frame_out, fig = run_pipeline(ExampleCraneParticipant)
        
        validate_participant_output(data_frame_out)

    def test_crane_pipeline_rejects_empty_output(self):
        bad_df = DataFrame()
        validate_participant_output(bad_df)
