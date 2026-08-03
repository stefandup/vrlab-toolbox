import unittest
from pathlib import Path

from mooi_toolbox.processing.foh_pipeline import run_lsl_pipeline
from mooi_toolbox.processing.input_data import PhysiologyFileFormat
from mooi_toolbox.processing.lsl import LslParticipantConfig, LslPhysiologyDataImportStrategy

# from mooi_toolbox.processing.foh_target_behaviour import run_processing
# from mooi_toolbox.processing.be


# @unittest.skip("Busy")
class TestFOHPipeline(unittest.TestCase):
    def test_data_import_strategy(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = LslParticipantConfig.from_lsl_data(
            "P00015",
            data_folder,
            ["OpenSignals", "FOH_target", "VR_trial_events", "VR_markers"],
            PhysiologyFileFormat.LSL,
        )
        raw_bio_data_out = LslPhysiologyDataImportStrategy().run(participant_config)

        self.assertTrue(raw_bio_data_out)

    @unittest.skip("Busy")
    def test_foh_target_behav_strategy(self):
        # run_processing()
        pass

    def test_basic_pipeline(self):
        data_folder = Path(r"local_lsl_data\\Participant Data")

        participant_config = LslParticipantConfig.from_lsl_data(
            "P00015",
            data_folder,
            ["OpenSignals", "FOH_target", "VR_trial_events", "VR_markers"],
            PhysiologyFileFormat.LSL,
        )

        raw_bio_data_out = LslPhysiologyDataImportStrategy().run(participant_config)
        df_out, fig_out = run_lsl_pipeline(
            participant_config.physiology_fn, verbose=False, show_plots=False
        )
