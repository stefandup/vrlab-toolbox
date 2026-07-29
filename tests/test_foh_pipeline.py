import unittest
from pathlib import Path

from mooi_toolbox.processing.input_data import PhysiologyFileFormat
from mooi_toolbox.processing.lsl import LslParticipantConfig


# @unittest.skip("Busy")
class TestFOHPipeline(unittest.TestCase):
    def test_basic_pipeline(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = LslParticipantConfig.from_lsl_data(
            "P00015",
            data_folder,
            ["FOH_target", "VR_trial_events", "VR_markers"],
            PhysiologyFileFormat.LSL,
        )

        # df_out, fig = run_lsl_pipeline(data_folder=data_folder, verbose=False, show_plots=False)
