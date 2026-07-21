import pandas as pd


def check_changes_in_velocity_over_time():
    pass


def check_accuracy_over_conditions():
    pass


def check_emotion_distribution():
    """Use violin plots to examine data across conditions and emotions reported"""
    pass


def check_if_nausea_was_a_problem():
    """Check if there was a relative increase in nausea over conditions. We hope not."""
    pass


def compare_target_score_vs_score():
    """If task was successfully fixed, then the score should never have reached the target score."""
    pass


def compare_forced_vs_slips():
    pass


def check_more_drops_during_slip_and_stress():
    pass


def check_all_slips_have_a_reason():
    pass


def import_csv(csv_fn: str) -> pd.DataFrame:
    return pd.read_csv(csv_fn)


def qc_pipeline(csv_output_file: str):
    """
    Performs the QC to check basic assumptions of the crane game which would have been too
    laborious in SPSS and elsewhere.

    """

    pass
