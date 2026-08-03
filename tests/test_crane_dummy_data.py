import shutil
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.crane_behaviour import RawCraneBehaviourData
from mooi_toolbox.processing.crane_debrief_behaviour import RawDebriefBehaviourData
from mooi_toolbox.processing.crane_dummy_data import generate_dummy_dataset
from mooi_toolbox.processing.crane_pipeline import run_pipeline
from mooi_toolbox.processing.processing_status import ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals

TEMPLATE_FOLDER = Path("sample_data/crane_templates")

ERROR_SCENARIO_STATUS_KEY = {
    "missing_physiology": RawBioData,
    "missing_behaviour": RawCraneBehaviourData,
    "missing_debrief": RawDebriefBehaviourData,
    "date_mismatch": RawCraneBehaviourData,
    "bad_trigger_count": TrialIntervals,
    "short_trigger": TrialIntervals,
}


class TestCraneDummyData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output_folder = Path(tempfile.mkdtemp())
        cls.results = generate_dummy_dataset(
            TEMPLATE_FOLDER, cls.output_folder, n_clean=2, with_errors=True, seed=42
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.output_folder, ignore_errors=True)

    def test_clean_participant_is_fully_ok(self):
        clean_result = next(r for r in self.results if r.scenario == "clean")
        pipeline_out = run_pipeline(clean_result.subject_id, self.output_folder)
        self.assertTrue(
            all(status == ProcessingStatus.OK for status in pipeline_out.status.status.values())
        )

    def test_each_error_scenario_flags_expected_status(self):
        for result in self.results:
            if result.scenario == "clean":
                continue
            with self.subTest(scenario=result.scenario):
                pipeline_out = run_pipeline(result.subject_id, self.output_folder)
                status_key = ERROR_SCENARIO_STATUS_KEY[result.scenario]
                self.assertEqual(pipeline_out.status.status[status_key], ProcessingStatus.ERROR)


if __name__ == "__main__":
    unittest.main()
