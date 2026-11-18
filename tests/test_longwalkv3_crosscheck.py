"""LongwalkV3 crosscheck MVP, end to end on synthetic data (docs/longwalk3_plan.md, phase A).

Done = clean dummy participants have no problems, and every injected error scenario is flagged.
Generates from the reviewed shape manifest in longwalkv3_examples/shape/ (gitignored -- the
test is skipped where it isn't present). Synthetic data only.
"""

from pathlib import Path

import pytest

from vrlab_toolbox.gui.longwalk3_bids_crosscheck_gui import (
    LONGWALKV3_DATASET_CONFIG,
    LongwalkV3CandidateExtras,
)
from vrlab_toolbox.processing.bids_crosscheck import scan_bids_folder
from vrlab_toolbox.processing.longwalk3_bids import convert_longwalkv3_to_bids
from vrlab_toolbox.processing.longwalk3_dummy_data import (
    SHAPE_ERROR_TYPES,
    generate_dummy_longwalkv3_dataset_from_shape,
)

MANIFEST = Path(__file__).parents[1] / "longwalkv3_examples/shape/longwalkv3_shape.json"
N_CLEAN = 2

# What each scenario should be flagged with, as a fragment of an issue/problem message.
EXPECTED_FLAG = {
    "aborted_run_restarted": "restarted",
    "session_folder_underscore": "should be named 'ses-",
    "multiple_cities_per_session": "more than one city",
    "malformed_subject_id_in_physiology_filename": "no physiology recording",
    "missing_subject_id_in_physiology_filename": "no physiology recording",
    "mislabeled_physiology_date": "mislabeled physiology date",
}

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="shape manifest not present")


@pytest.fixture(scope="module")
def crosschecked(tmp_path_factory):
    root = tmp_path_factory.mktemp("lw3")
    raw, bids_folder = root / "raw", root / "bids"
    dataset = generate_dummy_longwalkv3_dataset_from_shape(
        MANIFEST, raw, n_clean=N_CLEAN, with_errors=True, seed=1
    )
    summary = convert_longwalkv3_to_bids(raw, bids_folder)
    scan = scan_bids_folder(bids_folder, LONGWALKV3_DATASET_CONFIG)
    extras = LongwalkV3CandidateExtras()
    extras.on_bids_folder_changed(bids_folder)

    flags: dict[str, list[str]] = {}
    for subject_id in scan.subject_ids():
        subject_scans = scan.scans[subject_id]
        messages = list(extras.subject_issues(subject_id, subject_scans))
        for scan_type, subject_scan in subject_scans.items():
            for file in subject_scan.files:
                messages += extras.problems(scan_type, file)
        flags[subject_id] = messages
    return dataset, summary, flags


def test_clean_participants_have_no_problems(crosschecked):
    dataset, _, flags = crosschecked
    for result in dataset.participant_results[:N_CLEAN]:
        assert flags[result.subject_id] == [], result.subject_id


@pytest.mark.parametrize("scenario", SHAPE_ERROR_TYPES)
def test_each_error_scenario_is_flagged(crosschecked, scenario):
    dataset, _, flags = crosschecked
    result = next(r for r in dataset.participant_results if r.scenario == scenario)
    messages = flags.get(result.subject_id, [])
    assert any(EXPECTED_FLAG[scenario] in m for m in messages), (scenario, messages)


def test_unparseable_physiology_filename_is_reported(crosschecked):
    _, summary, _ = crosschecked
    assert summary.unparseable_files
