import unittest
from dataclasses import dataclass
from pandas import DataFrame

from mooi_toolbox.processing.crane_pipeline import run_pipeline, validate_participant_output

@dataclass
class ExampleCraneParticipant:
    subject_id : str = "00020"
    biopac_fn: str = r"crane_data\\2026481120_00020_CraneOut.mat"
    behav_folder : str = r"crane_data"
    verbose : bool = False
    show_plots : bool = False

class TestCranePipeline(unittest.TestCase):

    def test_crane_pipeline_has_expected_output(self):
        data_frame_out, fig = run_pipeline(
            ExampleCraneParticipant.subject_id,
            ExampleCraneParticipant.biopac_fn,
            ExampleCraneParticipant.behav_folder,
            ExampleCraneParticipant.verbose,
            ExampleCraneParticipant.show_plots
            )
        
        validate_participant_output(data_frame_out)

    def test_crane_pipeline_rejects_empty_output(self):
        bad_df = DataFrame()
        validate_participant_output(bad_df)
