"""CLI: copy-only converter from crane's raw flat data folder into a BIDS-shaped output
folder that `gui/crane_bids_crosscheck_gui.py` can point at.

See docs/bids_converter_plan.md. Never touches `input_folder` -- only ever copies into
`output_folder`. Dumps every matching file it finds, duplicates included; picking a
canonical file among duplicates is the crosscheck tool's job, not this converter's ("the
converter should dump, not decide").

Incremental by subject: `output_folder` may already exist and already hold converted
subjects (e.g. from a previous run, possibly already crosschecked/corrected by hand) --
any subject whose `sub-XXX/` folder is already there is left completely alone and skipped,
so re-running against a source folder that's since gained new subjects only ever adds
those, never re-copies or overwrites an existing one.

Date prefixes are carried through unchanged from the raw filenames -- they're not reliably
parseable as real calendar dates (inconsistent length/format across sessions), so no attempt
is made to normalize them here. Use the crosscheck tool's "Correct date..." button to fix any
that are wrong, once they're visible listed per subject.

Output layout, and why it looks the way it does:
- Every file goes in `sub-XXX/beh/`, not directly in `sub-XXX/` -- mirroring FOH's
  `sub-XXX/eeg/` layout. This isn't cosmetic: `bids_crosscheck.record_task_correction`
  (the crosscheck tool's "Tag as..." action) renames a *file's parent folder* to the
  dataset's datatype folder when tagging -- if files sat directly in `sub-XXX/`, tagging
  would rename the whole subject folder itself, merging every tagged subject into one
  shared top-level folder. Placing them under `beh/` up front makes that rename a same-name
  no-op instead.
- Every filename includes a `run-001` token -- `record_task_correction` requires one
  (`RUN_TOKEN_PATTERN`) and raises otherwise. Crane doesn't have multi-run semantics today,
  so this is always "001", not a real run count.
- Scan type is identified by *extension* (`.mat`/`.csv`/`.tsv`), not by a keyword in the
  filename stem (`gui/crane_bids_crosscheck_gui.py`'s glob patterns) -- because
  `record_task_correction` replaces everything after the run-<NNN> token with just
  `_<label>`, so a keyword like "_physiology" wouldn't survive tagging. Debrief is written
  `.tsv` (not `.csv`, same as behaviour) specifically so all three scan types stay
  distinguishable by extension alone even after a tag rename.
"""

import logging
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

from mooi_toolbox import mobi_logging
from mooi_toolbox.processing.bids_crosscheck import SUBJECT_FOLDER_PREFIX
from mooi_toolbox.processing.crane_debrief_behaviour import REDCAP_FN

logger = logging.getLogger(__name__)

PHYSIOLOGY_GLOB = "*_CraneOut.mat"
BEHAVIOUR_GLOB = "*_CraneOut.csv"
# See module docstring's "Output layout" section for why these two exist.
DATATYPE_FOLDER_NAME = "beh"
RUN_TOKEN = "run-001"
# REDCAP exports a value for these subject-level columns only on a row's first appearance,
# blank on any continuation rows for the same subject -- same forward-fill
# `crane_debrief_behaviour.load_group_debrief_data` already does for the pipeline's own
# reading of this workbook, needed here too so a per-subject filter doesn't miss a
# continuation row with a blank Subject_ID.
DEBRIEF_SUBJECT_COLS = ("Subject_ID", "started_with_Crane_MobiLab", "High_at_start_end")
# Known REDCAP renames of the two DEBRIEF_SUBJECT_COLS fields above (beyond Subject_ID,
# handled separately via SUBJECT_ID_HEADER_ALIASES) -- confirmed by whoever maintains the
# export, added one at a time as they're actually seen, not guessed. An unmapped rename just
# means that field isn't forward-filled (a blank on a subject's later rows in the output
# .tsv) -- doesn't affect subject-id matching, so leaving one unmapped rather than guessing
# wrong is the safe default. "High_at_start_end" doesn't have a confirmed rename yet.
DEBRIEF_SUBJECT_COL_ALIASES: dict[str, str] = {
    "started": "started_with_Crane_MobiLab",
}
# Real filenames are `{date}_{subject_id}_CraneOut.{ext}`, but: the date prefix isn't always
# there; it's sometimes joined with "-" instead of "_" (e.g. "20267291154-PID5562_CraneOut");
# and a subject id can carry a Windows duplicate-copy marker (" (1)", " (2)", ...) from a file
# accidentally copied twice within the same folder. `biopac.get_subject_id_from_mat`'s naive
# `split("_")[1]` breaks on all three: a 2-token filename with no date puts "CraneOut" itself
# (the suffix) at index 1 instead of the id; a "-"-joined date never gets split off at all; and
# a "(1)"/"(2)" marker gets kept as part of the "id" -- turning one real subject into two
# different (wrong) ones. This regex handles all three, without touching biopac.py (still
# correct for the plain-date-prefixed filenames the real pipeline mostly sees).
_SUBJECT_ID_PATTERN = re.compile(
    r"^(?:(?P<date>\d+)[_-])?(?P<subject_id>.+?)(?:\s*\(\d+\))?_CraneOut$", re.IGNORECASE
)
# Confirmed (by whoever actually enters these IDs) the same real subject gets written
# inconsistently as "PID-1234" and "PID1234" -- consistent about the "PID" prefix and the
# digits, just not about the dash in between. Canonicalized to the no-dash form (arbitrary
# but consistent) wherever a subject id is derived, so e.g. a sub-XXX/ folder name doesn't
# end up depending on which spelling happened to appear in a given source file.
_PID_DASH_PATTERN = re.compile(r"^PID-(\d+)$", re.IGNORECASE)


def canonicalize_subject_id(subject_id: str) -> str:
    match = _PID_DASH_PATTERN.match(subject_id)
    if match:
        return f"PID{match.group(1)}"
    return subject_id


@dataclass
class ParsedCraneFilename:
    subject_id: str
    date_prefix: str | None


def parse_crane_filename(file: Path) -> ParsedCraneFilename | None:
    """Subject id + date prefix from a raw crane filename's stem, in one pass -- both need
    the same regex, so deriving date_prefix separately (e.g. a naive
    `file.name.split("_")[0]`) would silently disagree with it whenever the date is "-"-joined
    or absent. Returns None if the filename doesn't match the expected
    `[<date>[_-]]<id>[ (N)]_CraneOut` shape at all, rather than guessing -- callers must handle
    None (skip + log), not treat it as a real id.
    """
    match = _SUBJECT_ID_PATTERN.match(file.stem)
    if match is None:
        return None
    return ParsedCraneFilename(
        subject_id=canonicalize_subject_id(match.group("subject_id")),
        date_prefix=match.group("date"),
    )


def extract_subject_id(file: Path) -> str | None:
    """Subject id alone -- see `parse_crane_filename` for the date prefix too."""
    parsed = parse_crane_filename(file)
    return parsed.subject_id if parsed is not None else None

EXAMPLES_EPILOG = """
Examples:

\\b
  Convert a raw crane data folder into a BIDS-shaped folder the crosscheck tool can point at:
  crane_convert_to_bids C:\\raw\\MscFiles_crane_local C:\\bids\\MscFiles_crane_bids
"""


def _find_debrief_workbook(input_folder: Path, override: Path | None = None) -> Path | None:
    """Locate the shared REDCAP workbook. `override`, if given, is used as-is, no searching
    -- for when auto-detection guesses wrong or refuses (ambiguous, multiple .xlsx candidates)
    and a human just knows which file is the real one. Otherwise prefers an exact `REDCAP_FN`
    match (what the real pipeline's `load_group_debrief_data` requires today), but falls back
    to any single `.xlsx` file found -- confirmed against real data that the on-disk filename
    can differ from `REDCAP_FN` by punctuation alone (underscores vs. spaces), which would
    make the exact-match pipeline path silently find nothing too. Flag that constant/filename
    mismatch to a human rather than silently "fixing" it here. Searched recursively (like
    every other lookup here) since it may not sit directly at input_folder's top level.
    """
    if override is not None:
        return override

    exact_matches = sorted(input_folder.rglob(REDCAP_FN))
    if exact_matches:
        return exact_matches[0]

    xlsx_candidates = sorted(input_folder.rglob("*.xlsx"))
    if len(xlsx_candidates) == 1:
        logger.warning(
            "No file named %r, but found %s -- using it as the debrief workbook. This means "
            "processing/crane_debrief_behaviour.py's REDCAP_FN constant doesn't match the "
            "real filename either, which would also break the pipeline's own debrief "
            "loading -- worth fixing REDCAP_FN or renaming the file.",
            REDCAP_FN,
            xlsx_candidates[0].name,
        )
        return xlsx_candidates[0]

    if xlsx_candidates:
        logger.warning(
            "No file named %r, and %d other .xlsx files found -- ambiguous, skipping debrief "
            "entirely: %s",
            REDCAP_FN,
            len(xlsx_candidates),
            ", ".join(path.name for path in xlsx_candidates),
        )
    else:
        logger.warning(
            "No file named %r and no other .xlsx file found in %s -- skipping debrief "
            "entirely",
            REDCAP_FN,
            input_folder,
        )
    return None


def _normalize_subject_id_column(series: pd.Series) -> pd.Series:
    """Fallback string-ification for a Subject_ID column, for when the read-time dtype hint
    below (the real fix) couldn't be applied because no matching raw header was found. A
    zero-padded, numeric-looking ID cell (e.g. "00002") read WITHOUT a dtype hint gets
    pandas' auto-inferred numeric type (2.0) -- plain `.astype(str)` on that produces "2.0",
    not "2", let alone the original "00002". This strips a spurious ".0" for whole numbers;
    it can't recover already-lost leading zeros, since that information is gone by the time
    pandas has inferred a numeric dtype.
    """
    if pd.api.types.is_float_dtype(series):
        return series.apply(
            lambda v: str(int(v)) if pd.notna(v) and float(v).is_integer() else str(v)
        )
    return series.astype(str).str.strip()


# "record_id" is REDCAP's own default name for a project's first/primary field, present in
# every REDCAP project unless someone explicitly renames it -- recognized here as a synonym
# for "Subject_ID" since an export can come out under REDCAP's default name instead of a
# crane-specific rename. Just this one well-known REDCAP-standard alternative, not a general
# column-name-guessing system.
SUBJECT_ID_HEADER_ALIASES = ("subject_id", "record_id")


def _find_subject_id_header(columns) -> str | None:
    """Find whatever the raw (uncleaned) column header for Subject_ID actually is, so it can
    be used as a `pd.read_excel(..., dtype=...)` key -- that dict is matched against the
    literal on-disk header, before any of this module's own cleaning/renaming runs.
    """
    for column in columns:
        if str(column).strip().lower().replace(" ", "_") in SUBJECT_ID_HEADER_ALIASES:
            return column
    return None


def _load_cleaned_debrief_workbook(
    input_folder: Path, override: Path | None = None
) -> pd.DataFrame | None:
    """Read+clean the shared REDCAP workbook, without `load_group_debrief_data`'s further
    pivot/proportion transform -- that produces pipeline *output* metrics, not the raw
    per-subject row this converter wants to hand a human reviewer.

    TODO: this reads whatever REDCAP happened to export and hopes the columns/values look
    right (see the header/dtype gymnastics below and the case-insensitive/dash-insensitive
    matching in convert_crane_to_bids) -- there's no schema validating the shape up front.
    REDCAP exports are human-triggered and people taking liberties with the export options
    (wrong columns included, wrong format) is exactly the kind of thing a schema check (e.g.
    reusing or adapting crane_debrief_behaviour.crane_raw_debrief_file_schema) would catch
    with a clear error instead of a silent downstream mismatch. Not done here since a strict
    schema also risks being too rigid for a converter that's meant to dump, not decide --
    needs a real design pass on what "invalid enough to reject" means for this file, not a
    quick add.
    """
    workbook_path = _find_debrief_workbook(input_folder, override)
    if workbook_path is None:
        return None

    # Read Subject_ID as text from the very start, matching what makes the real pipeline's
    # own matching (crane_debrief_behaviour.load_group_debrief_data's
    # `pd.read_excel(data_fn, dtype={"Subject_ID": str})`) reliable. This is NOT the same as
    # reading with no dtype hint and str()-ing the result afterwards in
    # _normalize_subject_id_column: a numeric-looking Excel cell read without a dtype hint
    # gets pandas' auto-inferred numeric type first (e.g. becomes the float 1.0), and
    # str(1.0) == "1.0" -- the real "00001"-style representation is already gone by the time
    # there's a chance to reformat it. The header name is discovered from a cheap
    # header-only read first, since `dtype` needs the exact raw (uncleaned) column name.
    header_only = pd.read_excel(workbook_path, nrows=0)
    raw_subject_id_header = _find_subject_id_header(header_only.columns)
    dtype_hint = {raw_subject_id_header: str} if raw_subject_id_header is not None else None
    df = pd.read_excel(workbook_path, dtype=dtype_hint)
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.replace("/", "_")

    # Matched case-insensitively against either known alias (see SUBJECT_ID_HEADER_ALIASES)
    # rather than requiring the literal "Subject_ID" spelling -- same risk as the REDCAP_FN
    # filename mismatch above: the real workbook's header casing/naming isn't confirmed
    # against crane_raw_debrief_file_schema's expectation.
    subject_id_column = next(
        (col for col in df.columns if col.lower() in SUBJECT_ID_HEADER_ALIASES), None
    )
    if subject_id_column is None:
        logger.warning(
            "No 'Subject_ID'/'record_id' column found in %s after cleaning -- skipping "
            "debrief entirely. Columns found: %s",
            workbook_path,
            ", ".join(df.columns) or "(none)",
        )
        return None
    df = df.rename(columns={subject_id_column: "Subject_ID"})
    df["Subject_ID"] = _normalize_subject_id_column(df["Subject_ID"]).apply(canonicalize_subject_id)

    df = df.rename(
        columns={
            col: DEBRIEF_SUBJECT_COL_ALIASES[col.lower()]
            for col in df.columns
            if col.lower() in DEBRIEF_SUBJECT_COL_ALIASES
        }
    )
    present_subject_cols = [col for col in DEBRIEF_SUBJECT_COLS if col in df.columns]
    df[present_subject_cols] = df[present_subject_cols].ffill()
    df = df.dropna(how="all")
    return df.drop(columns="Subject_Names", errors="ignore")


def _existing_subject_ids(output_folder: Path) -> set[str]:
    if not output_folder.is_dir():
        return set()
    return {
        entry.name.removeprefix(SUBJECT_FOLDER_PREFIX)
        for entry in output_folder.iterdir()
        if entry.is_dir() and entry.name.startswith(SUBJECT_FOLDER_PREFIX)
    }


def _has_debrief_file(output_folder: Path, subject_id: str) -> bool:
    datatype_folder = output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}" / DATATYPE_FOLDER_NAME
    return datatype_folder.is_dir() and any(datatype_folder.glob("*_debrief_events.tsv"))


def _existing_date_prefix(output_folder: Path, subject_id: str) -> str | None:
    """Best-effort date prefix for a subject already converted in an earlier run, read off
    whatever file's already sitting in their beh/ folder -- used only for naming a backfilled
    debrief file consistently with its siblings, since that subject's date prefix was never
    derived this run (see subject_date_prefix, only populated for files copied in this call).
    """
    datatype_folder = output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}" / DATATYPE_FOLDER_NAME
    if not datatype_folder.is_dir():
        return None
    existing_files = sorted(f for f in datatype_folder.iterdir() if f.is_file())
    return existing_files[0].name.split("_")[0] if existing_files else None


def _datatype_folder(output_folder: Path, subject_id: str) -> Path:
    folder = output_folder / f"{SUBJECT_FOLDER_PREFIX}{subject_id}" / DATATYPE_FOLDER_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _bids_filename(date_prefix: str, subject_id: str, suffix: str, extension: str) -> str:
    return f"{date_prefix}_{SUBJECT_FOLDER_PREFIX}{subject_id}_{RUN_TOKEN}_{suffix}{extension}"


def _copy_into_subject_folder(
    source: Path, output_folder: Path, subject_id: str, date_prefix: str, suffix: str
) -> Path:
    destination = _datatype_folder(output_folder, subject_id) / _bids_filename(
        date_prefix, subject_id, suffix, source.suffix
    )
    if destination.exists():
        # Two different source files landed on the same destination name -- e.g. a Windows
        # duplicate-copy pair ("... (1)_CraneOut.mat" / "... (2)_CraneOut.mat") that share a
        # date prefix once the "(N)" marker is stripped from the subject id. Both are real
        # candidate files the crosscheck tool should let a human pick between, so disambiguate
        # rather than silently overwrite one with shutil.copy2's default behaviour.
        counter = 2
        candidate = destination
        while candidate.exists():
            candidate = _datatype_folder(output_folder, subject_id) / _bids_filename(
                date_prefix, subject_id, f"{suffix}-dup{counter}", source.suffix
            )
            counter += 1
        destination = candidate
    shutil.copy2(source, destination)
    return destination


@dataclass
class CraneConversionSummary:
    """Everything a caller (the CLI's `main()` below, or the crosscheck GUI's "Convert to
    BIDS..." button) needs to report what a `convert_crane_to_bids()` call actually did.
    Warnings/skips are also emitted via the module `logger` as they happen -- this is the
    end-of-run rollup, not a replacement for that.
    """

    new_subject_ids: list[str] = field(default_factory=list)
    subject_physiology: dict[str, list[Path]] = field(default_factory=dict)
    subject_behaviour: dict[str, list[Path]] = field(default_factory=dict)
    subject_debrief: dict[str, Path] = field(default_factory=dict)
    already_converted: set[str] = field(default_factory=set)
    skipped_files: int = 0
    unmatched_debrief: list[str] = field(default_factory=list)
    backfilled_debrief_ids: list[str] = field(default_factory=list)


def convert_crane_to_bids(
    input_folder: Path, output_folder: Path, debrief_workbook: Path | None = None
) -> CraneConversionSummary:
    """Core, UI-agnostic conversion logic -- see module docstring for the "why" behind the
    output layout. Progress/problems are reported via the standard `logger` (info for
    routine skips, warning for anything worth a human's attention), not print/rich, so both
    the CLI below and the crosscheck GUI's "Convert to BIDS..." button can drive this and
    display the result their own way -- attach a `logging.Handler` to this module's logger
    around the call to capture those messages for display elsewhere.

    `debrief_workbook`, if given, overrides auto-detection of the shared REDCAP workbook --
    for when the on-disk filename doesn't match `REDCAP_FN` *and* there's more than one
    `.xlsx` candidate in `input_folder` (auto-detection refuses rather than guessing between
    them), or when auto-detection would otherwise pick the wrong one.
    """
    output_folder.mkdir(parents=True, exist_ok=True)
    already_converted = _existing_subject_ids(output_folder)

    # Recursive (like every real pipeline lookup this mirrors -- input_data.py's
    # from_physiology_data, behaviour.py, vrlab_crane_process.py -- all use rglob), since raw
    # files aren't guaranteed to sit directly at input_folder's top level.
    physiology_files = sorted(input_folder.rglob(PHYSIOLOGY_GLOB))
    behaviour_files = sorted(input_folder.rglob(BEHAVIOUR_GLOB))
    debrief_df = _load_cleaned_debrief_workbook(input_folder, debrief_workbook)

    subject_physiology: dict[str, list[Path]] = defaultdict(list)
    subject_behaviour: dict[str, list[Path]] = defaultdict(list)
    subject_debrief: dict[str, Path] = {}
    subject_date_prefix: dict[str, str] = {}
    skipped_files = 0
    unparseable_files: list[Path] = []

    for mat_file in physiology_files:
        parsed = parse_crane_filename(mat_file)
        if parsed is None:
            unparseable_files.append(mat_file)
            continue
        if parsed.subject_id in already_converted:
            skipped_files += 1
            continue
        date_prefix = parsed.date_prefix or "nodate"
        subject_date_prefix.setdefault(parsed.subject_id, date_prefix)
        destination = _copy_into_subject_folder(
            mat_file, output_folder, parsed.subject_id, date_prefix, "physiology"
        )
        subject_physiology[parsed.subject_id].append(destination)

    for csv_file in behaviour_files:
        parsed = parse_crane_filename(csv_file)
        if parsed is None:
            unparseable_files.append(csv_file)
            continue
        if parsed.subject_id in already_converted:
            skipped_files += 1
            continue
        date_prefix = parsed.date_prefix or "nodate"
        subject_date_prefix.setdefault(parsed.subject_id, date_prefix)
        destination = _copy_into_subject_folder(
            csv_file, output_folder, parsed.subject_id, date_prefix, "behaviour"
        )
        subject_behaviour[parsed.subject_id].append(destination)

    if unparseable_files:
        logger.warning(
            "Could not extract a subject id from %d filename(s) -- skipped entirely, not "
            "copied: %s",
            len(unparseable_files),
            ", ".join(f.name for f in unparseable_files),
        )

    new_subject_ids = sorted(set(subject_physiology) | set(subject_behaviour))

    # Debrief backfill: an already-converted subject (physiology/behaviour skipped above,
    # untouched by design) still gets reconsidered for debrief specifically if they don't
    # have one yet -- e.g. a previous run's debrief workbook didn't match them, and this run
    # was given a corrected/different one via debrief_workbook. Subjects that already have a
    # debrief file are left alone either way -- never overwritten, same as everything else
    # this converter touches.
    backfill_candidate_ids = sorted(
        sid for sid in already_converted if not _has_debrief_file(output_folder, sid)
    )
    debrief_candidate_ids = sorted(set(new_subject_ids) | set(backfill_candidate_ids))
    backfilled_debrief_ids: list[str] = []

    if debrief_df is not None:
        # Case-insensitive, in case the workbook's Subject_ID values and filename-derived ids
        # differ only in casing (e.g. "pid10016" vs "PID10016").
        debrief_lookup_key = debrief_df["Subject_ID"].str.upper()
        for subject_id in debrief_candidate_ids:
            subject_rows = debrief_df[debrief_lookup_key == subject_id.upper()]
            if not subject_rows.empty:
                date_prefix = (
                    subject_date_prefix.get(subject_id)
                    or _existing_date_prefix(output_folder, subject_id)
                    or "nodate"
                )
                destination = _datatype_folder(output_folder, subject_id) / _bids_filename(
                    date_prefix, subject_id, "debrief_events", ".tsv"
                )
                subject_rows.to_csv(destination, index=False, sep="\t")
                subject_debrief[subject_id] = destination
                if subject_id in backfill_candidate_ids:
                    backfilled_debrief_ids.append(subject_id)

    if backfilled_debrief_ids:
        logger.info(
            "Backfilled debrief for %d already-converted subject(s) that didn't have one "
            "yet: %s",
            len(backfilled_debrief_ids),
            ", ".join(sorted(backfilled_debrief_ids)),
        )

    if already_converted and skipped_files:
        logger.info(
            "Skipped %d file(s) for %d subject(s) already converted: %s",
            skipped_files,
            len(already_converted),
            ", ".join(sorted(already_converted)),
        )

    unmatched_debrief = [sid for sid in debrief_candidate_ids if sid not in subject_debrief]
    if debrief_df is not None and unmatched_debrief:
        # Sampling naively from the front of a sorted list is misleading here: e.g. every
        # "0"-prefixed numeric id sorts before every letter-prefixed one, so "first 15" alone
        # could show only one shape and hide entirely that the other shape exists further
        # in. Showing both ends (plus the total count) avoids that blind spot.
        all_values = sorted(debrief_df["Subject_ID"].dropna().unique())
        if len(all_values) <= 20:
            sample_desc = ", ".join(all_values)
        else:
            sample_desc = f"{', '.join(all_values[:10])}, ..., {', '.join(all_values[-10:])}"
        logger.warning(
            "No debrief row found for %d subject(s) -- check whether their Subject_ID in %s "
            "actually matches the ID in their filenames: %s. %d total distinct Subject_ID "
            "value(s) found in the workbook (first/last 10 shown if more than 20): %s",
            len(unmatched_debrief),
            REDCAP_FN,
            ", ".join(unmatched_debrief),
            len(all_values),
            sample_desc,
        )

    logger.info(
        "Added %d new subject folder(s) to %s: %d physiology, %d behaviour, %d debrief "
        "file(s) (%d of those backfilled for already-converted subjects). Skipped %d "
        "already-converted subject(s).",
        len(new_subject_ids),
        output_folder,
        sum(len(paths) for paths in subject_physiology.values()),
        sum(len(paths) for paths in subject_behaviour.values()),
        len(subject_debrief),
        len(backfilled_debrief_ids),
        len(already_converted),
    )

    return CraneConversionSummary(
        new_subject_ids=new_subject_ids,
        subject_physiology=dict(subject_physiology),
        subject_behaviour=dict(subject_behaviour),
        subject_debrief=subject_debrief,
        already_converted=already_converted,
        skipped_files=skipped_files,
        backfilled_debrief_ids=backfilled_debrief_ids,
        unmatched_debrief=unmatched_debrief,
    )


def _cell(paths_by_subject: dict, subject_id: str) -> str:
    value = paths_by_subject.get(subject_id)
    if not value:
        return "(missing)"
    if isinstance(value, list):
        return ", ".join(path.name for path in value)
    return value.name


def print_conversion_summary(summary: CraneConversionSummary) -> None:
    """Rich console/table rendering of a `CraneConversionSummary` -- the CLI's own output
    format, factored out so `main()` stays a thin wrapper around `convert_crane_to_bids()`.
    """
    console = Console()
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        console.print("No new subjects found -- everything in the source folder is already converted.")
        return

    table = Table(title="Crane raw -> BIDS conversion")
    table.add_column("Subject ID")
    table.add_column("Physiology")
    table.add_column("Behaviour")
    table.add_column("Debrief")
    for subject_id in summary.new_subject_ids:
        table.add_row(
            subject_id,
            _cell(summary.subject_physiology, subject_id),
            _cell(summary.subject_behaviour, subject_id),
            _cell(summary.subject_debrief, subject_id),
        )
    for subject_id in summary.backfilled_debrief_ids:
        table.add_row(
            f"{subject_id} (backfill)",
            "(already converted)",
            "(already converted)",
            _cell(summary.subject_debrief, subject_id),
        )
    console.print(table)


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="mooi-toolbox")
@click.argument(
    "input_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--debrief-workbook",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Override the shared REDCAP workbook auto-detection -- use when the on-disk "
    "filename doesn't match REDCAP_FN and there's more than one .xlsx candidate.",
)
@click.option("--verbose", is_flag=True, help="Give verbose output")
def main(
    input_folder: Path, output_folder: Path, debrief_workbook: Path | None, verbose: bool
) -> None:
    """Copy-only converter: raw crane data folder -> BIDS-shaped output folder.

    Incremental: subjects that already have a sub-XXX/ folder under output_folder are
    skipped entirely (not re-copied, not touched) -- safe to re-run against a source folder
    that's gained new subjects since the last run.
    """
    summary = convert_crane_to_bids(input_folder, output_folder, debrief_workbook)
    print_conversion_summary(summary)


if __name__ == "__main__":
    mobi_logging.init(__file__)
    main()
