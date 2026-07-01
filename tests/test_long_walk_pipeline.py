import unittest

from mooi_toolbox.processing.biopac import BiopacRawData
from mooi_toolbox.processing.processing_status import ProcessingStatus,PipelineStatus
from mooi_toolbox.processing.input_data import ParticipantConfig

from mooi_toolbox.processing.long_walk_pipeline import run_pipeline

example_long_walk_participant_correct = ParticipantConfig(
    subject_id="PID1311",
    biopac_fn=r"long_walk_data\\PID1311_20266241306.mat",
    behav_folder=r"long_walk_data",
    verbose=False,
    show_plots=False
)

class TestReadingBasicBiopacData(unittest.TestCase):
    
    def test_good_raw_data_should_return_ok(self):
        raw_biodata_good : BiopacRawData = BiopacRawData.load_data(example_long_walk_participant_correct)
        self.assertIsInstance(raw_biodata_good,BiopacRawData)

class TestLongWalkPipeline(unittest.TestCase):

    def test_long_walk_pipeline_has_expected_output(self):
       pipeline_out = run_pipeline(example_long_walk_participant_correct)
       pipeline_out.validate_participant_output() 