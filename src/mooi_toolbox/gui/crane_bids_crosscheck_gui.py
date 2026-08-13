"""Standalone PySide6 tool: human-in-the-loop crosscheck for the crane BIDS folder.

See docs/bids_crosscheck_plan.md. Glob patterns below are provisional — placeholders
grounded in the plan's mockup and the existing REDCAP naming convention
(`crane_debrief_behaviour.REDCAP_FN`), since crane has no BIDS output yet to check
real filenames against. Confirm/adjust once real BIDS output exists.
"""

from mooi_toolbox.gui.bids_crosscheck_common import CandidateExtras, run_bids_crosscheck_app
from mooi_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig

CRANE_DATASET_CONFIG = DatasetConfig(
    dataset_name="crane",
    scan_types=(
        ScanTypeConfig(name="physiology", glob_patterns=("*physiology*",)),
        ScanTypeConfig(name="behaviour", glob_patterns=("*behaviour*",)),
        ScanTypeConfig(name="debrief", glob_patterns=("*redcap*",)),
    ),
)


def main() -> None:
    run_bids_crosscheck_app(
        CRANE_DATASET_CONFIG,
        "Crane BIDS Crosscheck",
        CandidateExtras(),
        settings_app_name="CraneBidsCrosscheck",
    )


if __name__ == "__main__":
    main()
