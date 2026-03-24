from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mooi_toolbox.processing.check_plux_data import main as process_single_xdf


def find_xdf_files(base_dir: Path) -> list[Path]:
    """Recursively find all .xdf files in the base directory."""
    return sorted(base_dir.rglob("*.xdf"))


def extract_subject_id(xdf_path: Path) -> str:
    """Return subject/session ID in the form sub-XXX_ses-YYY."""
    sub = next((part for part in xdf_path.parts if part.startswith("sub-")), None)
    ses = next((part for part in xdf_path.parts if part.startswith("ses-")), None)
    if sub and ses:
        return f"{sub}_{ses}"

    # Fallback: parse from filename, e.g. sub-Test_ses-S001_task-...
    stem = xdf_path.stem
    sub_match = re.search(r"(sub-[^_\\\/]+)", stem)
    ses_match = re.search(r"(ses-[^_\\\/]+)", stem)
    if sub_match and ses_match:
        return f"{sub_match.group(1)}_{ses_match.group(1)}"

    return stem


def build_group_dataframe(base_dir: Path) -> pd.DataFrame:
    """Process all XDF files and vertically append participant outputs."""
    xdf_files = find_xdf_files(base_dir)
    if not xdf_files:
        return pd.DataFrame()

    participant_frames: list[pd.DataFrame] = []

    for xdf_path in xdf_files:
        try:
            participant_out_df = process_single_xdf([str(xdf_path)])
            participant_out_df = participant_out_df.copy()
            participant_out_df.insert(0, "subject_id", extract_subject_id(xdf_path))
            participant_out_df.insert(1, "xdf_path", str(xdf_path))
            participant_frames.append(participant_out_df)
        except Exception as exc:
            print(f"[WARN] Skipping {xdf_path}: {exc}")

    if not participant_frames:
        return pd.DataFrame()

    return pd.concat(participant_frames, axis=0, ignore_index=True, sort=False)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Loop over all .xdf files and aggregate participant_out_df rows."
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=PROJECT_ROOT / "local_lsl_data",
        help="Directory to recursively search for .xdf files.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=PROJECT_ROOT / "local_lsl_data_aggregated.csv",
        help="Output CSV path for the aggregated DataFrame.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    base_dir = args.base_dir.resolve()

    if not base_dir.exists():
        raise ValueError(f"Base directory does not exist: {base_dir}")

    group_df = build_group_dataframe(base_dir)

    if group_df.empty:
        print(f"No processable .xdf files found in: {base_dir}")
        return 0

    output_csv = args.output_csv.resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    group_df.to_csv(output_csv, index=False)

    print(f"Processed rows: {len(group_df)}")
    print(f"Saved aggregated output to: {output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
