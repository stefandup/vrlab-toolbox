import unittest
from pathlib import Path

from mooi_toolbox.processing.bids import BidsEventsData
from mooi_toolbox.processing.crane_behaviour import RawCraneBehaviourData
from mooi_toolbox.processing.crane_pipeline import FindCraneParticipantFilesStrategyStep

data_folder = Path("crane_data")
example_correct_bids_events_file_fn = Path(r"references\\example_events.tsv")


def setUpModule():
    global example_crane_participant_correct
    example_crane_participant_correct = FindCraneParticipantFilesStrategyStep().run(
        "00020", data_folder
    )


class TestBidsEventsDataBasicImport(unittest.TestCase):
    def test_import_from_valid_csv(self):
        bids_events_data = BidsEventsData.from_csv(example_correct_bids_events_file_fn)
        self.assertEqual(len(bids_events_data.events_df), 3)
        self.assertListEqual(
            list(bids_events_data.events_df.columns),
            ["onset", "duration", "trial_type", "response_time"],
        )

    def test_import_from_crane_tsv_out(self):
        raw_crane_behav_data = RawCraneBehaviourData.load_from_behaviour_type(
            example_crane_participant_correct, RawCraneBehaviourData
        )
        raw_crane_bids_events_data = raw_crane_behav_data.to_bids_events()
        self.assertListEqual(
            list(raw_crane_bids_events_data.events_df.columns),
            [
                "onset",
                "duration",
                "trial_type",
                "training",
                "trial_nr",
                "current_score",
                "total_dropped",
                "target_score",
                "nr_frustration_barrels",
                "nr_error_slips",
                "nr_slips",
                "nr_other_slips",
                "nr_no_reason_slips",
                "nr_forced_slips",
                "avg_velocity",
                "nausea",
                "dizzy",
                "stressed",
                "emotion_feedback",
            ],
        )
