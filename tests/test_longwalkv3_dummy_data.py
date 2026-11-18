"""REDCap shape profiling + dummy generation for longwalkV3 (longwalk3_dummy_data.py).

Every input here is a made-up REDCap export written by the test itself -- no real data. Its
answer cells hold marker values, so the tests can check none of them leak into a manifest.
"""

import csv
import json
import random
from pathlib import Path

import pandas as pd

from vrlab_toolbox.processing.longwalk3_dummy_data import (
    LIKERT_RANGE,
    REDCAP_EVENT_COLUMN,
    check_datetime_cells,
    generate_dummy_redcap_from_shape,
    is_redcap_export_filename,
    profile_longwalkv3_shape,
    profile_redcap_export,
)

HEADER = [
    "study_id",
    REDCAP_EVENT_COLUMN,
    "debrief_date",
    "stress_q1",
    "free_text_comment",
    "symptoms___1",
    "debrief_complete",
]
# Long format: subject A did 3 sessions, subject B did 2.
ROWS = [
    ["A", "session_1_arm_1", "2025-03-04", "4", "SECRETANSWER", "1", "2"],
    ["A", "session_2_arm_1", "2025-03-11", "3", "", "0", "2"],
    ["A", "session_3_arm_1", "2025-03-18", "5", "OTHERSECRET", "1", "2"],
    ["B", "session_1_arm_1", "2025-04-01", "2", "", "0", "2"],
    ["B", "session_2_arm_1", "2025-04-08", "1", "THIRDSECRET", "1", "1"],
]
ANSWER_MARKERS = ("SECRETANSWER", "OTHERSECRET", "THIRDSECRET", "2025-03-04", '"A"', '"B"')


def _write_export(folder: Path, name: str = "LongWalkV3_DATA_2026-11-18_1200.csv") -> Path:
    path = folder / name
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)
        writer.writerows(ROWS)
    return path


def test_redcap_export_filenames_are_recognised():
    assert is_redcap_export_filename("LongWalkV3_DATA_2026-11-18_1200.csv")
    assert is_redcap_export_filename("redcap_123_longwalkv3.csv")
    assert not is_redcap_export_filename("20260916_sub-01_task-city1_run-1_behaviour.csv")


def test_profile_holds_structure_but_no_answers(tmp_path):
    profile = profile_redcap_export(_write_export(tmp_path))

    assert profile["header"] == HEADER
    assert profile["id_column"] == "study_id"
    assert profile["n_records"] == 2
    assert profile["project_name"] == "LongWalkV3"
    assert sorted(len(p["row_types"]) for p in profile["record_row_patterns"]) == [2, 3]
    events = {rt["structural_values"][REDCAP_EVENT_COLUMN] for rt in profile["row_types"]}
    assert events == {"session_1_arm_1", "session_2_arm_1", "session_3_arm_1"}

    dumped = json.dumps(profile)
    for marker in ANSWER_MARKERS:
        assert marker not in dumped, f"{marker!r} leaked into the profile"


def test_shape_manifest_profiles_top_level_redcap_export_separately(tmp_path):
    (tmp_path / "sub-01" / "ses-01").mkdir(parents=True)
    _write_export(tmp_path)

    manifest = profile_longwalkv3_shape(tmp_path)

    assert len(manifest["redcap_exports"]) == 1
    generic_patterns = [
        f["pattern"] for s in manifest["subjects"] for ses in s["sessions"] for f in ses["files"]
    ]
    assert not any("DATA" in p for p in generic_patterns)


def test_generated_export_is_long_format_with_same_columns(tmp_path):
    profile = profile_redcap_export(_write_export(tmp_path))
    out = tmp_path / "out"
    out.mkdir()

    path = generate_dummy_redcap_from_shape(
        profile, out, ["dummy01", "dummy02", "dummy03"], random.Random(1)
    )
    df = pd.read_csv(path, dtype=str, keep_default_na=False)

    assert list(df.columns) == HEADER
    assert set(df["study_id"]) == {"dummy01", "dummy02", "dummy03"}
    assert df.groupby("study_id").size().isin([2, 3]).all()
    assert set(df[REDCAP_EVENT_COLUMN]) <= {"session_1_arm_1", "session_2_arm_1", "session_3_arm_1"}
    likert = df["stress_q1"].astype(int)
    assert likert.between(*LIKERT_RANGE).all()
    assert set(df["symptoms___1"]) <= {"0", "1"}
    assert (df["debrief_complete"] == "2").all()
    for marker in ("SECRETANSWER", "OTHERSECRET", "THIRDSECRET"):
        assert marker not in path.read_text(encoding="utf-8")


def test_datetime_check_tells_the_two_d6_readings_apart():
    # 17-digit neighbours 17:30:40.040 and 17:30:40.100; the short cell "...4052" fits
    # between them only as unpadded ms (52 ms), not as trailing-zeros-dropped (520 ms).
    cells = ["20260916173040040", "2026091617304052", "20260916173040100", ""]
    check = check_datetime_cells(cells)
    assert check["digit_lengths"] == {"16": 1, "17": 2, "empty": 1}
    assert check["full_length_in_order"] == [1, 1]
    assert check["decisive"] == {"unpadded_ms": 1}
    assert "2026" not in json.dumps(check)  # counts only, no values
