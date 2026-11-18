"""LongwalkV3 raw -> BIDS conversion pieces (longwalk3_bids.py), on small hand-written inputs."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from vrlab_toolbox.processing.longwalk3_bids import (
    _convert_subject_debrief,
    _session_nr_from_raw_folder,
    csv_to_df_compress_header,
    debrief_session_nrs,
    parse_behaviour_hhmm,
    parse_physiology_filename,
    parse_raw_csv_filename,
    parse_unreal_datetimes,
)


def test_sub_prefix_in_raw_filenames_is_stripped():
    acq = parse_physiology_filename(Path("202609161730_sub-dummy01_longwalkv3out.acq"))
    csv = parse_raw_csv_filename(
        Path("202609161730_sub-dummy01_ses-01_task-city3_run-1_BP_NPC_C.csv")
    )
    assert acq is not None and acq.subject_id == "dummy01"
    assert csv is not None and csv.subject_id == "dummy01"
    # Older exports wrote the bare id.
    legacy = parse_physiology_filename(Path("202609161730_P001_LongWalkV3Out.acq"))
    assert legacy is not None and legacy.subject_id == "P001"


def test_unreal_datetimes_read_short_milliseconds_as_unpadded():
    parsed = parse_unreal_datetimes(
        pd.Series(["20260916173040521", "2026091617304052", "20260916173040", "junk", ""])
    )
    assert parsed[0] == pd.Timestamp("2026-09-16 17:30:40.521")
    assert parsed[1] == pd.Timestamp("2026-09-16 17:30:40.052")
    assert parsed[2] == pd.Timestamp("2026-09-16 17:30:40")
    assert pd.isna(parsed[3]) and pd.isna(parsed[4])


def test_behaviour_hhmm_takes_the_day_from_the_run_date():
    parsed = parse_behaviour_hhmm(pd.Series(["1731", "905", "x"]), datetime(2026, 9, 16, 17, 30))
    assert parsed[0] == pd.Timestamp("2026-09-16 17:31")
    assert parsed[1] == pd.Timestamp("2026-09-16 09:05")
    assert pd.isna(parsed[2])


def test_repeated_headers_and_ragged_rows(tmp_path):
    path = tmp_path / "log.csv"
    path.write_text(
        "datetime,actor,trigger,message\n"
        "datetime,actor,trigger,message\n"
        "20260916173040521,A_0,A_0,hello, world\n"  # unquoted comma -> one extra field
        "20260916173041521,A_0\n",  # short row
        encoding="utf-8",
    )
    df = csv_to_df_compress_header(path)
    assert list(df.columns) == ["datetime", "actor", "trigger", "message"]
    assert len(df) == 2
    assert df.loc[0, "message"] == "hello, world"
    assert df.loc[1, "trigger"] == ""


def test_header_only_file_gives_empty_frame(tmp_path):
    path = tmp_path / "behaviour.csv"
    path.write_text("TimeStampHHmm,Nausea\nTimeStampHHmm,Nausea\n", encoding="utf-8")
    df = csv_to_df_compress_header(path)
    assert df.empty and list(df.columns) == ["TimeStampHHmm", "Nausea"]


@pytest.mark.parametrize(
    ("relative", "expected"),
    [("sub-01/ses-02/x.acq", 2), ("sub-01/ses_01/run-001/x.acq", 1), ("x.acq", None)],
)
def test_session_from_raw_folder(tmp_path, relative, expected):
    assert _session_nr_from_raw_folder(tmp_path / relative, tmp_path) == expected


def _debrief_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "study_id": ["d01", "d01", "d01"],
            "redcap_event_name": [
                "followup_session_1_arm_1",
                "baseline_arm_1",
                "followup_session_2_arm_1",
            ],
            "first_name": ["Ann", "", ""],
            "icf_pt_date_sign": ["2026-01-01", "", ""],
            "ipq_q1": [3, 4, None],
            "ipq_complete": [2, 2, 0],
        }
    )


def test_redcap_events_map_to_sessions_in_study_order():
    assert debrief_session_nrs(_debrief_df()) == {
        "baseline_arm_1": 1,
        "followup_session_1_arm_1": 2,
        "followup_session_2_arm_1": 3,
    }


def test_debrief_written_per_session_without_identifying_columns(tmp_path):
    written = _convert_subject_debrief("d01", _debrief_df(), tmp_path)

    # The followup_session_2 row has no answers -> skipped.
    sessions = sorted(p.parent.parent.name for p in written)
    assert sessions == ["ses-01", "ses-02"]
    for path in written:
        df = pd.read_csv(path, sep="\t")
        assert "first_name" not in df.columns
        assert "icf_pt_date_sign" not in df.columns
        assert {"study_id", "redcap_event_name", "ipq_q1"} <= set(df.columns)
