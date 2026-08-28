# BIDS Converter Plan

## Overview

`bids_crosscheck_plan.md`'s crosscheck tool assumes a populated BIDS folder
already exists to point it at. This page tracks that earlier step —
raw-to-BIDS conversion — which now exists for both datasets (see the updates
below), each living in its own `cli/` module rather than being an external,
outside-this-repo tool. `pipeline_next_steps.md` item 22 flags "move toward
BIDS" as a direction for the import layer, but that's about
`ParticipantConfig` reading from timepoint folders, not about producing a
BIDS folder in the first place.

**Update: crane's converter now exists** — `cli/crane_convert_to_bids.py`
(`convert_crane_to_bids()`), copy-only and incremental (skips subjects
already present in the output folder), integrated directly into
`gui/crane_bids_crosscheck_gui.py` via a "Convert to BIDS..." button (raw
folder + BIDS folder + an optional debrief-workbook override selector, all
in the crosscheck window itself — see `bids_crosscheck_common.py`'s generic
`raw_converter`/`override_file_label` hooks, which FOH doesn't use and gets
no UI for). The debrief design idea below is implemented as described: each
subject gets their own extracted row, written `..._acq-debrief_run-001_beh.tsv`
(tab-delimited, not the whole shared workbook). **Update: FOH's importer now exists too** — `cli/foh_import_to_bids.py`
(`import_foh_raw_to_bids()`), wired into `gui/foh_bids_crosscheck_gui.py` the
same way as crane's, via the same generic `raw_converter` hook. Unlike
crane's, it's a plain recursive copy, not a real conversion: FOH's raw
recording software already writes each subject's `.xdf` files straight into
a real `sub-XXX/ses-.../eeg/` BIDS layout at the point of recording (see
[FOH Crosscheck](foh-crosscheck.md#2-point-it-at-your-raw-folder-and-import)),
so there's no filename reshaping or per-subject-id parsing to do — just
`existing_subject_ids()` (moved into `processing/bids_crosscheck.py` so both
importers share it) to decide which `sub-XXX/` folders are new, then
`shutil.copytree()` for each. No debrief-equivalent complexity, so it skips
the `override_file_label`/`extra_raw_action` hooks crane's wiring uses.

**TODO: schema-validate the debrief workbook input.** The converter
currently reads whatever the REDCAP export happens to contain and does
best-effort header/dtype normalization (case-insensitive column matching, a
dash-insensitive PID id fix, forced text dtype for Subject_ID) rather than
validating the shape up front. REDCAP exports are human-triggered, and
someone taking liberties with the export options (wrong columns, wrong
format) is exactly the kind of thing a schema check — reusing or adapting
`crane_debrief_behaviour.crane_raw_debrief_file_schema` — would catch with a
clear error instead of a silent downstream mismatch (see the real incident:
83 subjects came back "no debrief row found" before the dtype bug was
found). Not done yet: needs a real design pass on what "invalid enough to
reject" means for a converter that's meant to dump, not decide — a schema
strict enough to catch real mistakes but not so strict it rejects
legitimate export variations needs actual thought, not a quick add.

**Decision: the dummy-data generator stays a separate, dev-only CLI tool --
not part of the crosscheck GUI.** `crane_generate_sample_data`
(`crane_dummy_data.py`) exists purely to produce synthetic data for local
development and testing; it has nothing to do with reviewing real
participant data, which is what the crosscheck window is for. A "Generate
dummy data..." button was briefly wired into the crosscheck window's raw-folder
actions and then removed again -- worth noting so it doesn't get
re-added by mistake later. Along the way this surfaced a real point of
confusion worth recording: the crosscheck window's "Last conversion" panel
only reflects conversions run *from that window's own "Refresh BIDS" button,
in the current session* -- generating data or converting via the standalone
CLIs (`crane_generate_sample_data`, `crane_convert_to_bids`) and then pointing
the crosscheck window at the result leaves the panel reading "No conversion
run yet.", correctly, since no conversion happened through the window itself.
That's expected, not a bug.

**Update: `crane_generate_sample_data` can now also convert what it
generates.** A new optional `--bids-folder` flag runs the freshly-generated
raw data straight through `crane_convert_to_bids.convert_crane_to_bids`,
printing both the "Generated crane dummy data" and "Crane raw -> BIDS
conversion" tables in one call -- e.g.
`crane_generate_sample_data examples/crane_templates examples --with-errors --seed 42 --bids-folder examples/crane_bids_dummy`
(`examples/crane_bids_dummy` is the actual folder `tests/test_crane_pipeline.py`
now reads from -- see docs/testing.md).
`output_folder` (the plain raw CraneOut folder) is always written regardless
of whether `--bids-folder` is given; the BIDS folder is purely additive. See
the README's "Generate sample data" section and docs/testing.md for the
user-facing writeup.

**Update: crane naming moved to real BIDS conventions (no date in filenames).**
A student reviewing the output pointed out the filenames weren't real BIDS
(`{date}_sub-XXX_run-001_{suffix}.ext`, date first) -- real BIDS never puts a
date in a scan filename; per-scan acquisition dates belong in a
`sub-XXX/ses-01/sub-XXX_ses-01_scans.tsv` sidecar instead (`filename`,
`acq_time` columns, one row per file). Decided:

- New layout: `sub-XXX/ses-01/beh/sub-XXX_ses-01_task-crane_acq-<label>_run-001_{suffix}.ext`,
  plus `sub-XXX/ses-01/sub-XXX_ses-01_scans.tsv` listing every file underneath
  with its date.
- `ses-01` is a fixed placeholder, same spirit as `run-001` -- crane has no
  real multi-session concept today, so no session-detection logic was added.
- Suffixes: `physiology` -> `physio` (real BIDS suffix, `.mat`, raw copy),
  `behaviour` -> `events` (real BIDS suffix for per-trial task/timing data --
  reformatted from the raw `.csv` to true tab-delimited `.tsv` on copy, since
  BIDS requires `.tsv` for `_events`), `debrief` -> `beh` (real BIDS suffix
  for genuinely behavioural, non-timing data -- the REDCAP post-task
  questionnaire; already tab-delimited, so this was a pure suffix rename).
  Every filename also carries an `acq-<label>` entity
  (`acq-physiology`/`acq-behaviour`/`acq-debrief`) naming which raw source it
  came from, since behaviour and debrief now share both a `.tsv` extension
  and (as of this rename) real BIDS suffixes that alone don't disambiguate
  them from a same-named file of a different scan type. **Decided
  2026-08-27** -- see `cli/crane_convert_to_bids.py`'s module docstring for
  the full reasoning; previously `behaviour` was `_beh` and `debrief` was
  `_debrief_events` (not a real BIDS suffix), which had the two swapped
  relative to what they actually contain.
- `acq_time` values are carried through as-is (same as the old filename date
  prefix was) -- not normalized to true ISO8601, since they aren't reliably
  parseable as real calendar dates (inconsistent length/format across raw
  filenames).
- The crosscheck GUI's "Correct date..." button now edits the matching
  `scans.tsv` row for crane instead of renaming the file, gated through a new
  `DatasetConfig.dates_in_scans_tsv` flag -- FOH keeps today's filename-rename
  behavior unchanged. `record_id_correction`, `record_task_correction`, and
  `remove_task_correction` (bids_crosscheck.py) were also updated to keep
  `scans.tsv`'s `filename` column in sync whenever they rename a file, so the
  sidecar doesn't go stale.
- **Crane's "Tag as crane" step was removed entirely** (`CraneCandidateExtras`
  no longer overrides `task_correction_available`, so it falls back to
  `False`). It only ever existed for UI parity with FOH's workflow, not
  because crane's raw filenames carried non-BIDS junk needing cleanup -- FOH's
  tagging exists to replace free text the *raw collection software* tacks on
  after the run token (`..._eeg_philani.xdf` -> `..._foh.xdf`). Crane's
  converter already writes real BIDS suffixes (`_physio`/`_events`/
  `_beh`) itself, so there's nothing left to clean up -- and tagging
  would instead have *destroyed* that distinction, since `record_task_correction`
  replaces everything after `run-<NNN>` with one generic label, the same for
  all three scan types. Duplicate-picking (`record_selected_run`) and
  `set_crosschecked` already cover "this is the confirmed file" without
  touching the filename, so nothing was lost by dropping it.

## Known constraints from related work

- **The converter should dump, not decide.** `bids_crosscheck_plan.md`'s
  whole premise is a converter that "dumps every matching file into the
  BIDS folder, duplicates included," with a human resolving duplicates
  afterward. A converter that already picked canonical runs itself would
  make the crosscheck tool partly redundant — keep that division of labor
  deliberate rather than let the converter creep into picking winners.
- **FOH:** the raw recording software's own naming convention (`sub-XXX/`
  layout, real BIDS filenames from the start) was real precedent worth
  inspecting before designing anything crane-side, rather than inventing a
  scheme from nothing -- see the "FOH's importer now exists too" update
  above for where that ended up.
- **Crane:** ~~no naming convention decided yet~~ **Decided** — see the
  "crane naming moved to real BIDS conventions" update above; the crosscheck
  tool's `CRANE_DATASET_CONFIG` glob patterns (`gui/crane_bids_crosscheck_gui.py`)
  now match the converter's real output rather than being guesses.
- **Debrief file, design idea:** ~~not decided~~ **Decided and implemented** —
  the converter extracts just the matching subject's row from the shared
  REDCAP workbook and writes it as its own per-subject `..._acq-debrief_run-001_beh.tsv`
  file (`load_debrief_export`/`convert_crane_to_bids` in
  `cli/crane_convert_to_bids.py`), exactly the small-per-subject-file
  alternative discussed below rather than duplicating the whole workbook.

## TODO

- **Re-implement/re-verify raw-to-BIDS conversion for both FOH and crane once
  their real pipelines change.** Noted 2026-08-27 by the project owner while
  finalizing the crane debrief/behaviour suffix swap above — a reminder that
  today's `crane_convert_to_bids.py`/`foh_import_to_bids.py` naming will need
  a fresh implementation pass on both sides later, not a scoped task right
  now.

## Out of scope for now

- Actual implementation — this is a scoping placeholder, not a design.
- Whether crane and FOH end up sharing one converter or stay separate
  (the crosscheck tool itself deliberately stayed one-tool-per-dataset;
  the converter doesn't have to follow the same split).
