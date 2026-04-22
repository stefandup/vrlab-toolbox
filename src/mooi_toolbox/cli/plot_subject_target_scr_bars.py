from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_CSV = PROJECT_ROOT / "local_lsl_data" / "_out" / "FOH_process_batch_out.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "local_lsl_data" / "_out" / "plots"
REQUIRED_TARGET_COLUMNS = [
    "Baseline_0_Short_Target",
    "Baseline_1_Short_Target",
    "Stress_0_Short_Target",
    "Stress_1_Short_Target",
    "recovery_Short_Target",
    "Baseline_0_Medium_Target",
    "Baseline_1_Medium_Target",
    "Stress_0_Medium_Target",
    "Stress_1_Medium_Target",
    "recovery_Medium_Target",
    "Baseline_0_Long_Target",
    "Baseline_1_Long_Target",
    "Stress_0_Long_Target",
    "Stress_1_Long_Target",
    "recovery_Long_Target",
]
REQUIRED_SCR_COLUMNS = [
    "baseline_SCR_per_min",
    "stress_SCR_per_min",
    "recovery_SCR_per_min",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create per-subject paired bar plots for target type values "
            "(Short/Medium/Long) vs SCR-per-min across Baseline, Stress, Recovery."
        )
    )
    parser.add_argument(
        "--input-csv",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help=f"Input CSV path (default: {DEFAULT_INPUT_CSV}).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for PNG files (default: {DEFAULT_OUTPUT_DIR}).",
    )
    return parser.parse_args(argv)


def _mean_if_all_present(values: list[float]) -> float:
    arr = np.asarray(values, dtype=float)
    if np.isnan(arr).any():
        return float(np.nan)
    return float(np.mean(arr))


def _target_by_condition(row: pd.Series, duration: str) -> list[float]:
    training = float(row.get(f"Baseline_0_{duration}_Target", np.nan))
    baseline = float(row.get(f"Baseline_1_{duration}_Target", np.nan))
    stress = _mean_if_all_present(
        [
            row.get(f"Stress_0_{duration}_Target", np.nan),
            row.get(f"Stress_1_{duration}_Target", np.nan),
        ]
    )
    recovery = float(row.get(f"recovery_{duration}_Target", np.nan))
    return [training, baseline, stress, recovery]


def _scr_by_condition(row: pd.Series) -> list[float]:
    return [
        float(row.get("baseline_SCR_per_min", np.nan)),
        float(row.get("stress_SCR_per_min", np.nan)),
        float(row.get("recovery_SCR_per_min", np.nan)),
    ]


def _normalise_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Import-Csv showed an unnamed index-like first column in the batch output.
    unnamed_columns = [col for col in df.columns if str(col).startswith("Unnamed:")]
    if unnamed_columns:
        df = df.drop(columns=unnamed_columns)

    rename_map = {}
    for col in df.columns:
        stripped = str(col).strip()
        lowered = stripped.lower()
        if lowered == "subject_id":
            rename_map[col] = "Subject_ID"
        elif lowered == "recovery_short_target":
            rename_map[col] = "recovery_Short_Target"
        elif lowered == "recovery_medium_target":
            rename_map[col] = "recovery_Medium_Target"
        elif lowered == "recovery_long_target":
            rename_map[col] = "recovery_Long_Target"
        elif lowered == "baseline_scr_per_min":
            rename_map[col] = "baseline_SCR_per_min"
        elif lowered == "stress_scr_per_min":
            rename_map[col] = "stress_SCR_per_min"
        elif lowered == "recovery_scr_per_min":
            rename_map[col] = "recovery_SCR_per_min"

    if rename_map:
        df = df.rename(columns=rename_map)
    return df


def _validate_columns(df: pd.DataFrame) -> None:
    required_columns = [
        "Subject_ID",
        *REQUIRED_TARGET_COLUMNS,
    ]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"Missing expected columns: {missing}")


def create_subject_plot(row: pd.Series, output_dir: Path) -> Path:
    subject_id = str(row["Subject_ID"])
    target_conditions = ["Training", "Baseline", "Stress", "Recovery"]
    scr_conditions = ["Baseline", "Stress", "Recovery"]
    scr_values = _scr_by_condition(row)
    durations = ["Short", "Medium", "Long"]

    fig = plt.figure(figsize=(16, 7))
    gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 0.9])
    x_target = np.arange(len(target_conditions))
    x_scr = np.arange(len(scr_conditions))
    width = 0.6

    for col_idx, duration in enumerate(durations):
        target_values = _target_by_condition(row, duration)
        target_ax = fig.add_subplot(gs[0, col_idx])

        target_ax.bar(x_target, target_values, width=width, color="#4C78A8")
        target_ax.set_title(f"{duration} Targets")
        target_ax.set_xticks(x_target)
        target_ax.set_xticklabels(target_conditions)
        target_ax.set_ylabel("Hit latency (s)")
        target_ax.grid(axis="y", alpha=0.25)

    scr_ax = fig.add_subplot(gs[1, :])
    if np.isnan(np.asarray(scr_values, dtype=float)).all():
        scr_ax.set_title("SCR / min (not available)")
        scr_ax.text(
            0.5,
            0.5,
            "No SCR columns/data in source CSV",
            ha="center",
            va="center",
            transform=scr_ax.transAxes,
            fontsize=11,
            alpha=0.8,
        )
        scr_ax.set_xticks([])
        scr_ax.set_yticks([])
    else:
        scr_ax.bar(x_scr, scr_values, width=width, color="#F58518")
        scr_ax.set_title("SCR / min")
        scr_ax.set_xticks(x_scr)
        scr_ax.set_xticklabels(scr_conditions)
        scr_ax.set_ylabel("SCR / min")
        scr_ax.grid(axis="y", alpha=0.25)

    fig.suptitle(f"{subject_id}: Targets and SCR by condition", y=0.98)
    fig.tight_layout(rect=(0, 0, 1, 0.95))

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{subject_id}_target_scr_paired_bars.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_csv = args.input_csv.resolve()
    output_dir = args.output_dir.resolve()

    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    df = _normalise_dataframe(pd.read_csv(input_csv))
    _validate_columns(df)

    numeric_cols = [
        col
        for col in df.columns
        if col not in {"Subject_ID", "xdf_path"}
    ]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")

    saved_paths: list[Path] = []
    skipped_subjects: list[str] = []
    for idx, row in df.iterrows():
        subject_id = str(row.get("Subject_ID", f"row_{idx}"))
        if pd.isna(row.get("Subject_ID", np.nan)) or not subject_id.strip():
            print(f"Skipping row_{idx}: missing subject identifier")
            skipped_subjects.append(f"row_{idx}")
            continue
        try:
            saved_paths.append(create_subject_plot(row, output_dir))
        except Exception as exc:
            print(f"Skipping {subject_id}: failed to generate plot ({exc})")
            skipped_subjects.append(subject_id)

    print(f"Generated {len(saved_paths)} plot(s). Skipped {len(skipped_subjects)}.")
    for path in saved_paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
