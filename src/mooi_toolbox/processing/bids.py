import csv
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pandera.pandas as pa

SCANS_TSV_COLUMNS: tuple[str, ...] = ("filename", "acq_time")
# Marks a filename whose BIDS suffix collided with an existing one and got disambiguated
# (see resolve_collision) -- not part of real BIDS, callers strip it once a human has picked
# the canonical file among duplicates.
_SUFFIX_DUPLICATE_MARKER_PATTERN = re.compile(r"-dup\d+$")


def read_scans_tsv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as tsv_file:
        return list(csv.DictReader(tsv_file, delimiter="\t"))


def append_scan_row(scans_tsv_path: Path, filename: str, acq_time: str) -> None:
    """Record one scan file's acquisition date/time as a row in its `scans.tsv` sidecar --
    BIDS's own place for per-scan acquisition metadata.
    """
    rows = read_scans_tsv_rows(scans_tsv_path)
    rows.append({"filename": filename, "acq_time": acq_time})
    with scans_tsv_path.open("w", newline="", encoding="utf-8") as tsv_file:
        writer = csv.DictWriter(tsv_file, fieldnames=SCANS_TSV_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def build_bids_filename(
    subject_id: str,
    session: str,
    task: str,
    run: str,
    suffix: str,
    extension: str,
    acq: str | None = None,
) -> str:
    """A BIDS filename in real entity order: sub-/ses-/task-/[acq-/]run-/suffix.ext."""
    acq_entity = f"acq-{acq}_" if acq else ""
    return f"sub-{subject_id}_{session}_{task}_{acq_entity}{run}_{suffix}{extension}"


def resolve_collision(build_path: Callable[[str], Path], base_suffix: str) -> Path:
    """First available path for `base_suffix`, or a "-dupN" variant if `build_path(base_suffix)`
    already exists -- e.g. two different source files landing on the same destination name.
    Both are real candidate files a human should pick between, so this disambiguates rather
    than silently overwriting one.
    """
    destination = build_path(base_suffix)
    if not destination.exists():
        return destination
    counter = 2
    candidate = build_path(f"{base_suffix}-dup{counter}")
    while candidate.exists():
        counter += 1
        candidate = build_path(f"{base_suffix}-dup{counter}")
    return candidate


def strip_duplicate_marker(filename: str) -> str | None:
    """The BIDS-valid version of `filename` with `resolve_collision`'s "-dupN" marker removed
    from its suffix, or None if it doesn't carry one.
    """
    stem = Path(filename).stem
    if not _SUFFIX_DUPLICATE_MARKER_PATTERN.search(stem):
        return None
    corrected_stem = _SUFFIX_DUPLICATE_MARKER_PATTERN.sub("", stem, count=1)
    return f"{corrected_stem}{Path(filename).suffix}"


def copy_scan(source: Path, destination: Path, scans_tsv_path: Path, acq_time: str) -> None:
    """Byte-copy `source` into `destination` and record it in the session's `scans.tsv`."""
    shutil.copy2(source, destination)
    relative_name = destination.relative_to(scans_tsv_path.parent).as_posix()
    append_scan_row(scans_tsv_path, relative_name, acq_time)


def write_scan_as_tsv(source: Path, destination: Path, scans_tsv_path: Path, acq_time: str) -> None:
    """Reformat a comma-delimited `source` into a true tab-delimited `destination` (BIDS
    requires `.tsv`, e.g. for `_events`) and record it in the session's `scans.tsv`. A real
    reformat, not a rename -- round-tripping through pandas can trim trailing float precision
    on numeric columns.
    """
    pd.read_csv(source).to_csv(destination, sep="\t", index=False)
    relative_name = destination.relative_to(scans_tsv_path.parent).as_posix()
    append_scan_row(scans_tsv_path, relative_name, acq_time)


def load_json_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as json_file:
        return json.load(json_file)


def save_json_map(path: Path, data: dict[str, str]) -> None:
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def build_base_bids_events_schema(
    additional_columns: dict[str, pa.Column] | None = None,
) -> pa.DataFrameSchema:
    """Build a BIDS-compatible events schema.

    Use this as the base schema for any events.tsv-style output. The schema always
    requires valid BIDS timing columns: finite numeric `onset` values and finite,
    non-negative numeric `duration` values.

    Pass `additional_columns` to extend the schema for pipeline-specific outputs
    while preserving the required BIDS columns.

    Example:
        class CraneEventsOutput:
            validation_schema = build_bids_events_schema(
                {
                    "trial_type": pa.Column(pd.StringDtype(), nullable=False, coerce=True),
                    "response_time": pa.Column(pd.Float64Dtype(), nullable=True, coerce=True),
                }
            )
    """

    return pa.DataFrameSchema(
        {
            "onset": pa.Column(
                pd.Float64Dtype(),
                checks=pa.Check(
                    lambda s: np.isfinite(s).all(),
                    error="onsets must contain finite numeric values",
                ),
                nullable=False,
                coerce=True,
                required=True,
            ),
            "duration": pa.Column(
                pd.Float64Dtype(),
                checks=[
                    pa.Check.ge(0),
                    pa.Check(
                        lambda s: np.isfinite(s).all(), error="duration must contain finite numbers"
                    ),
                ],
                nullable=True,
                coerce=True,
                required=True,
            ),
            **(additional_columns or {}),
        },
        coerce=True,
        strict=False,
    )


@dataclass
class BidsEventsData:
    events_df: pd.DataFrame = field(init=False)
    additional_columns: dict[str, pa.Column] = field(default_factory=dict, init=False)
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_bids_events_schema)

    def __post_init__(self):
        self.events_df = pd.DataFrame(
            {"onset": pd.Series(dtype="Float64"), "duration": pd.Series(dtype="Float64")}
        )

        self.validation_schema = build_base_bids_events_schema(self.additional_columns)
        self.events_df = self.validation_schema.validate(self.events_df)

    def append_dataframe(
        self, df_in: pd.DataFrame, additional_columns: dict[str, pa.Column] | None = None
    ) -> None:
        additional_columns = additional_columns or {}
        self.validation_schema = build_base_bids_events_schema(
            {**self.additional_columns, **additional_columns}
        )
        df_in_reset = df_in.reset_index(drop=True)

        exisiting_df = self.events_df
        exisiting_df_reset = exisiting_df.reset_index(drop=True)
        data_list = [df_in_reset, exisiting_df_reset]
        data_list = [data for data in data_list if not data.empty]

        if not data_list:
            raise ValueError("Cannot concatenate empty dataset.")

        combined_df = pd.concat(data_list, axis=0, ignore_index=True)

        self.events_df = self.validation_schema.validate(combined_df)

    @classmethod
    def from_csv(cls, csv_fn: Path, delimiter: str = "\t"):
        new_df = pd.read_csv(csv_fn, delimiter=delimiter)
        result = cls()
        result.append_dataframe(new_df)

        return result
