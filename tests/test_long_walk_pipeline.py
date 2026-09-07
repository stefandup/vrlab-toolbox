import unittest
from pathlib import Path

from mooi_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from mooi_toolbox.processing.longwalk_behaviour import LongWalkRawBehaviourData

# mooi_toolbox.processing.long_walk_pipeline has no test coverage yet -- unlike crane/foh/spiral,
# this pipeline has no tests at all. Placeholder so the gap shows up in test runs instead of
# silently vanishing as an empty file.


@unittest.skip("No tests written yet for long_walk_pipeline.")
class TestLongWalkPipeline(unittest.TestCase):
    def test_import_strategy(self):
        EXAMPLE_PARTICIPANT_MAT = r"long_walk_data\\PID864_20267281136.mat"
        DATA_FOLDER = Path(r"long_walk_data")
        EXAMPLE_PARTICIPANT_ID = "PID864"

        ParticipantConfig.from_bids_data(
            EXAMPLE_PARTICIPANT_ID,
            PhysiologyFileFormat.BIOPAC,
            DATA_FOLDER,
            [type(LongWalkRawBehaviourData)],
        )

    def test_placeholder(self):
        pass


if __name__ == "__main__":
    unittest.main()
