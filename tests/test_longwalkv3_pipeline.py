import unittest
from pathlib import Path

import pandas as pd

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from vrlab_toolbox.processing.input_data import ParticipantConfig
from vrlab_toolbox.processing.longwalk3_behaviour import (
    ImportLongWalkV3BehaviourDataStrategyStep,
    ProcessLongWalkV3BehaviourDataStrategyStep,
    RawLongWalkV3BehaviourData,
)
from vrlab_toolbox.processing.longwalk3_bids import (
    build_longwalkv3_raw_session_events_behav_file_schema,
    combine_events_df_files,
    get_all_dfs,
)
from vrlab_toolbox.processing.longwalk3_debrief_behaviour import RawLongWalkV3DebriefBehaviourData
from vrlab_toolbox.processing.longwalk3_pipeline import (
    FindLongWalkV3ParticipantFilesStrategyStep,
    build_longwalkv3_participant_output_schema,
    run_pipeline_all_sessions,
)
from vrlab_toolbox.processing.longwalk3_trial_intervals import (
    LongWalkV3GetTrialIntervalStrategyStep,
)
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.trial_intervals import TrialIntervals

BIDS_FOLDER = Path(r"longwalkv3_examples\\bids")
EXAMPLES_FOLDER = Path(r"longwalkv3_examples")
CLEAN_ID = "dummy01"

ALL_OK_STATUS_STR = PipelineStatus(
    status={
        RawLongWalkV3BehaviourData: ProcessingStatus.OK,
        RawLongWalkV3DebriefBehaviourData: ProcessingStatus.OK,
        RawBioData: ProcessingStatus.OK,
        TrialIntervals: ProcessingStatus.OK,
    }
).get_as_text()


class TestBidsConversion(unittest.TestCase):
    def test_combining_csv_files(self):
        dummy_data_folder = EXAMPLES_FOLDER
        subject_id_correct = CLEAN_ID
        df_list = get_all_dfs(subject_id_correct, dummy_data_folder)
        combined_df_list_out = combine_events_df_files(subject_id_correct, df_list)

        for df in combined_df_list_out.values():
            self.assertIsInstance(
                build_longwalkv3_raw_session_events_behav_file_schema().validate(df), pd.DataFrame
            )


class TestBasicDataHandling(unittest.TestCase):
    def setUp(self):
        self.good_config = FindLongWalkV3ParticipantFilesStrategyStep().run(CLEAN_ID, BIDS_FOLDER)

    def test_find_long_walk_v3_participant_strategy(self):
        good_config = FindLongWalkV3ParticipantFilesStrategyStep().run(CLEAN_ID, BIDS_FOLDER)
        self.assertIsInstance(good_config, ParticipantConfig)

    def test_good_raw_data_init_should_return_ok(self):
        raw_biodata = BiopacPhysiologyDataImportStartegy().run(self.good_config)
        self.assertIsInstance(raw_biodata, RawBioData)


class TestLongWalkV3BehaviourStrategy(unittest.TestCase):
    def setUp(self):
        self.config_list = [
            FindLongWalkV3ParticipantFilesStrategyStep(session_nr=session_nr).run(
                CLEAN_ID, BIDS_FOLDER
            )
            for session_nr in range(1, 3)
        ]

    def test_bids_behav_import(self):
        for config in self.config_list:
            raw_behaviour = ImportLongWalkV3BehaviourDataStrategyStep().run(config)
            build_longwalkv3_raw_session_events_behav_file_schema().validate(
                raw_behaviour.raw_behav_df
            )

    def test_long_walk_v3_process_behaviour(self):
        for config in self.config_list:
            raw_behaviour = ImportLongWalkV3BehaviourDataStrategyStep().run(config_in=config)
            processed = ProcessLongWalkV3BehaviourDataStrategyStep().run(config, raw_behaviour)
            self.assertEqual(processed.subject_df_out["Subject_ID"].iloc[0], CLEAN_ID)


class TestLongWalkV3(unittest.TestCase):
    def setUp(self):
        self.config_list = [
            FindLongWalkV3ParticipantFilesStrategyStep(session_nr=session_nr).run(
                CLEAN_ID, BIDS_FOLDER
            )
            for session_nr in range(1, 3)
        ]

        self.raw_behaviour_list = []
        self.raw_biodata_list = []

        for config in self.config_list:
            self.raw_biodata_list.append(BiopacPhysiologyDataImportStartegy().run(config))
            self.raw_behaviour_list.append(ImportLongWalkV3BehaviourDataStrategyStep().run(config))

    def test_longwalkv3_process_intervals_correctly(self):
        trial_interval_list = []
        for session in range(0, 2):
            trial_interval, _, _ = LongWalkV3GetTrialIntervalStrategyStep().run(
                self.raw_biodata_list[session], self.raw_behaviour_list[session]
            )
            trial_interval_list.append(trial_interval)


class TestLongWalkV3AllSessions(unittest.TestCase):
    """D3: one wide row per subject, every session's columns prefixed sesNN_."""

    def test_clean_subject_gives_one_wide_row_with_every_session_ok(self):
        output = run_pipeline_all_sessions(CLEAN_ID, BIDS_FOLDER)
        df = output.subject_df_out
        self.assertEqual(len(df), 1)
        self.assertEqual(df["Subject_ID"].iloc[0], CLEAN_ID)
        session_statuses = [c for c in df.columns if c.endswith("_Processing_Status")]
        self.assertEqual(session_statuses, [f"ses0{n}_Processing_Status" for n in (1, 2, 3)])
        for column in session_statuses:
            self.assertIn("TrialIntervals=ok", df[column].iloc[0])
        self.assertTrue(any(c.startswith("ses01_") and "SCR_per_min" in c for c in df.columns))
        build_longwalkv3_participant_output_schema().validate(df)


class TestLongWalkV3ProcessCli(unittest.TestCase):
    def test_run_batch_writes_one_wide_row_per_subject(self):
        import shutil
        import tempfile

        from vrlab_toolbox.cli.vrlab_longwalk3_process import find_subject_ids, run_batch

        with tempfile.TemporaryDirectory() as tmp:
            bids, out = Path(tmp) / "bids", Path(tmp) / "out"
            shutil.copytree(BIDS_FOLDER / f"sub-{CLEAN_ID}", bids / f"sub-{CLEAN_ID}")
            out.mkdir()
            self.assertEqual(find_subject_ids(bids), [CLEAN_ID])
            csv_path = run_batch(bids, out)
            df = pd.read_csv(csv_path, index_col=0, dtype={"Subject_ID": str})
            self.assertEqual(df["Subject_ID"].tolist(), [CLEAN_ID])
            self.assertTrue(csv_path.with_suffix(".sav").exists())
            self.assertTrue(any(out.glob("*Interval_qc.png")))


class TestLongWalkV3ResultsViewer(unittest.TestCase):
    """Phase C: the results viewer's dashboard reads the batch CSV's wide columns."""

    def test_dashboard_and_overhead_lines_from_a_wide_row(self):
        from matplotlib.figure import Figure

        from vrlab_toolbox.gui.longwalk3_process_results_gui import (
            actor_class_label,
            build_longwalk3_group_dashboard,
            longwalk3_dashboard_overhead_lines,
            subject_id_from_bids_path,
        )

        df = pd.DataFrame(
            {
                "Subject_ID": ["a", "b"],
                "Processing_Status": ["X=ok", "X=corrected"],
                "ses01_Processing_Status": ["X=ok", "TrialIntervals=corrected"],
                "ses02_Processing_Status": ["X=ok", None],
                "ses01_BP_NPC_C_SCR_per_min_1": [1.0, 2.0],
                "ses02_BP_Phone_C_SCR_per_min": [3.0, None],
            }
        )
        figure = Figure()
        build_longwalk3_group_dashboard(figure, df, ["a", "b"])
        self.assertEqual(len(figure.axes), 3)
        lines = longwalk3_dashboard_overhead_lines(df, ["a", "b", "c"])
        self.assertIn("no output yet", lines[0])
        self.assertIn("range 1-2", lines[1])
        self.assertIn("corrected): 1", lines[2])
        self.assertEqual(actor_class_label("BP_NPC_C", with_icon=False), "NPC")
        self.assertEqual(
            subject_id_from_bids_path(
                Path("bids/sub-007/ses-01/beh/sub-007_ses-01_task-longwalkv3_physio.acq")
            ),
            "007",
        )
