from pathlib import Path

import pandas as pd

from vrlab_toolbox.processing import redcap


def test_redcap_output_path_uses_stable_study_and_crosscheck_name(tmp_path: Path) -> None:
    path = redcap.redcap_output_path(
        raw_folder=tmp_path,
        study_id="test study 01",
        crosscheck_id="crane",
    )

    assert path == tmp_path / "redcap_test_study_01_crane.csv"


def test_save_and_load_config_roundtrip(tmp_path: Path) -> None:
    config_file = tmp_path / "redcap_config.json"

    redcap.save_config(
        config_file=config_file,
        redcap_url="https://example.org/api/",
        report_id=12345,
    )

    config = redcap.load_config(config_file)

    assert config == {
        "redcap_url": "https://example.org/api/",
        "report_id": 12345,
    }


def test_pull_report_to_raw_writes_standard_filename(tmp_path: Path, monkeypatch) -> None:
    expected = pd.DataFrame(
        {
            "record_id": ["1001", "1002"],
            "stressed": [1, 2],
        }
    )

    monkeypatch.setattr(
        redcap,
        "get_token",
        lambda study_id, crosscheck_id: "fake-token",
    )

    monkeypatch.setattr(
        redcap,
        "pull_report",
        lambda token, report_id, redcap_url: expected,
    )

    output_file = redcap.pull_report_to_raw(
        raw_folder=tmp_path,
        study_id="philani",
        crosscheck_id="crane",
        report_id=14932,
        redcap_url="https://example.org/api/",
    )

    assert output_file == tmp_path / "redcap_philani_crane.csv"
    assert output_file.exists()

    saved = pd.read_csv(output_file, dtype={"record_id": str})
    pd.testing.assert_frame_equal(saved, expected)


def test_token_key_is_separate_per_study_and_crosscheck(monkeypatch) -> None:
    saved = {}

    def fake_set_password(service, username, password):
        saved[(service, username)] = password

    def fake_get_password(service, username):
        return saved.get((service, username))

    monkeypatch.setattr(redcap.keyring, "set_password", fake_set_password)
    monkeypatch.setattr(redcap.keyring, "get_password", fake_get_password)

    redcap.save_token("study_a", "crane", "token-a")
    redcap.save_token("study_b", "crane", "token-b")
    redcap.save_token("study_a", "foh", "token-c")

    assert redcap.get_token("study_a", "crane") == "token-a"
    assert redcap.get_token("study_b", "crane") == "token-b"
    assert redcap.get_token("study_a", "foh") == "token-c"
