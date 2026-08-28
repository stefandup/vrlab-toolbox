# BIDS Crosscheck: Architecture

[BIDS Crosscheck Plan](bids_crosscheck_plan.md) covers the *design*
decisions behind this tool — why it exists, what's deliberately out of
scope, the mockup it was built from. This page is the *code* map: what's
actually built, where it lives, and what to touch to change or extend it.
If you're looking to *use* the tool instead, see [FOH
Crosscheck](foh-crosscheck.md).

## Philosophy

- **Human-in-the-loop, decisions recorded not applied.** The tool never
  guesses which file is right. Every choice a person makes is written to a
  JSON file *before* anything on disk changes, so the record survives even
  if the app crashes mid-operation.
- **One tool per dataset**, not one app with a dataset switcher — matches
  this repo's existing pattern of one CLI/entry point per pipeline
  (`vrlab_crane_process`, `vrlab_foh_assess_data`, …).
- **No automatic collision resolution.** If a rename ever leaves two files
  looking like duplicates again, that's treated as an ordinary duplicate,
  routed through the same review — deliberately one mechanism, not two.
- **Additive-only.** Nothing here changes `ParticipantConfig` or any
  existing pipeline code — see the plan's own guardrail section for the
  full reasoning.

## Code layout

```
processing/bids_crosscheck.py        Qt-free engine: scanning, JSON I/O, corrections
gui/bids_crosscheck_common.py        shared PySide6 window (BidsCrosscheckWindow)
gui/crane_bids_crosscheck_gui.py     thin entry point: crane's DatasetConfig
gui/foh_bids_crosscheck_gui.py       thin entry point: FOH's DatasetConfig + CandidateExtras
tests/test_bids_crosscheck.py        tests for the engine (no Qt dependency)
```

Everything Qt-specific stays out of `processing/bids_crosscheck.py` on
purpose — it's plain Python + `pathlib`, testable without a display, and in
principle reusable from a future non-GUI entry point.

## Key types

| Type | Lives in | What it is |
| --- | --- | --- |
| `DatasetConfig` | `processing/bids_crosscheck.py` | One dataset's scan types, glob patterns, and whether/how task-tagging (FOH's "Tag with foh BIDS tags") applies -- `task_tag_task`/`task_tag_acq`/`task_tag_suffix` (the BIDS entities/suffix a tag writes) plus an optional `task_tag_folder_name`, which also renames a tagged file's parent folder (e.g. FOH's `eeg/` -> `beh/`), carrying along anything else still in it. |
| `ScanTypeConfig` | same | One scan type's name + the glob patterns that find its candidate files. |
| `SubjectScan` | same | One subject/scan-type's candidate files, with a `status` property (`"ok"` / `"missing"` / `"duplicate"`, derived purely from file count). |
| `BidsFolderScan` | same | The result of scanning a whole folder — every subject × scan-type, plus `has_issues()`. |
| `CandidateExtras` | `gui/bids_crosscheck_common.py` | The hook dataset-specific GUIs override to add per-candidate info (see FOH below). Crane uses the no-op default. |
| `BidsCrosscheckWindow` | same | The actual master-detail window: subject table (Subject / Tag / Datatype / Info columns) on the left, per-scan-type detail panel on the right. |

`BidsCrosscheckWindow` never imports anything crane- or FOH-specific — it
only knows `DatasetConfig` and the `CandidateExtras` protocol. That's what
lets `crane_bids_crosscheck_gui.py` and `foh_bids_crosscheck_gui.py` stay a
few dozen lines each.

## The subject table's Tag and Datatype columns

`_build_subject_tag_widget` shows, per tag-eligible scan type (i.e.
`extras.task_tag_available(scan_type)` is true), whether the
currently-effective candidate carries the `task-<task>` marker yet -- the
task value itself if tagged, `"not tagged"` in `PLEASE_SELECT_COLOR` if not.
Blank for a scan type that doesn't support tagging at all (e.g. every one of
Crane's), or with nothing effective yet. Same underlying check as
`_needs_task_tag`, just surfaced as its own column instead of only
the 🏷 icon.

`_build_subject_datatype_widget` shows, per scan type, the BIDS datatype
folder (`file.parent.name`) the currently-effective candidate lives in right
now -- blank if there's nothing effective yet (missing, or an unresolved
duplicate). `_datatype_tooltip` explains the value on hover: what the current
folder is, and -- if `task_tag_folder_name` is configured and differs
from the current folder -- what it becomes once tagged. `BIDS_DATATYPE_NAMES`
(a small, dataset-agnostic dict of BIDS's own datatype abbreviations, e.g.
`"beh": "behavioural"`) glosses both in plain English wherever it recognizes
the folder name; an unrecognized one is shown without a gloss rather than
guessed. Deliberately doesn't assert anything about the *current* folder's
accuracy (only the *target* one, which the dataset config author chose on
purpose) -- FOH's `eeg/` is a real example of a current folder whose name is
simply wrong for what it contains.

Column order is Subject / Tag / Datatype / Info, left to right.

## The artifacts a BIDS folder ends up with

The tool never touches anything outside the BIDS folder it's pointed at
(see the plan's "BIDS folder only" decision). Inside it, these appear as
you use the tool:

- **`crosscheck.json`** — finalized decisions: `selected_run`,
  `date_correction`, `id_correction`, `task_tag`/`task_tag_removed`,
  `crosschecked`. Keyed by `{subject_id}_{scan_type}` (`_decision_key`),
  except `crosschecked` uses a *different* key (`_crosschecked_key`, same
  base plus `_crosschecked`) so marking something crosschecked can never
  overwrite an existing `selected_run` entry for that same subject/scan-type.
- **`crosscheck_pending.json`** — radio picks made but not yet committed
  (`load_pending_selections`/`save_pending_selections`). Kept in a
  *separate* file from `crosscheck.json` on purpose: these aren't decisions
  yet, just in-progress GUI state, autosaved so closing the app before
  clicking "commit" doesn't lose the picks. Filenames only, not full
  paths — re-resolved against a fresh scan's actual candidates on load, so
  a stale entry (file renamed/deleted outside the tool) is silently
  dropped rather than crashing.
- **`excluded_subjects.json`** — `{subject_id: reason}` for every subject
  `record_subject_excluded` has removed from BIDS. Unlike the earlier
  `crosscheck_junk/`/`crosscheck_review/` folders (removed 2026-08-27), a
  removed subject's `sub-XXX/` folder is deleted outright, not moved
  anywhere -- safe only because neither importer/converter ever touches
  the raw folder (see "BIDS folder only" in the plan), so it's always the
  real recoverable copy. `existing_subject_ids` unions this file's keys
  with the folders actually on disk, so an excluded subject doesn't look
  "new" again to the next raw-to-BIDS refresh. `record_selected_run` (a
  duplicate's non-selected candidate) deletes the file directly instead
  and does *not* write here -- it's still recorded in `crosscheck.json`'s
  `selected_run` entry, which is enough for restore (below) to find it.
  `restore_all_from_bids` reverses both: it clears this file entirely, and
  for every `selected_run` decision it finds, deletes that subject's whole
  `sub-XXX/` folder and the decision itself, so the next raw-to-BIDS
  refresh re-derives them fresh. There's no more permanent-delete
  operation in this module -- deleting *was* already the only operation,
  so a separate "confirm forever" action on top of it would be redundant.

Both JSON writes go through `_write_json_atomic` — write to a `.tmp` file,
then `os.replace()` — so a crash mid-write can't corrupt either file.

## Extending: adding a new dataset

A new dataset needs exactly two things: a `DatasetConfig`, and a `main()`
that calls `run_bids_crosscheck_app`. `crane_bids_crosscheck_gui.py` is the
minimal template (no `CandidateExtras` override):

```python
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
        CRANE_DATASET_CONFIG, "Crane BIDS Crosscheck", CandidateExtras(),
        settings_app_name="CraneBidsCrosscheck",
    )
```

`foh_bids_crosscheck_gui.py` shows the richer path: a `CandidateExtras`
subclass (`FohCandidateExtras`) that overrides `describe()` to show a
recording's date/duration/stream-presence (colored HTML, parsed via
`pyxdf` + `processing/lsl.gather_xdf_data_streams`/`get_start_time`), and
`task_tag_available()` to enable the "Tag with foh BIDS tags" button.
Every parse result is cached per-file in `self._info_cache` for the life
of the window — see the caching TODO below for the next step (persisting
that across restarts too).

Add `settings_app_name` (used as the `QSettings` application name — see
below) unique per dataset, and register a console-script entry in
`pyproject.toml`'s `[project.scripts]`, matching the existing
`vrlab_crane_bids_crosscheck` / `vrlab_foh_bids_crosscheck` pattern.

## Libraries used

- **[PySide6](https://doc.qt.io/qtforpython-6/)** — the GUI framework
  itself (official Python bindings for Qt).
- **`QSettings`** (part of `PySide6.QtCore`) — remembers the last-opened
  BIDS folder across restarts, one registry/plist entry per
  `settings_app_name`, so crane and FOH don't share state.
- **[`rich.progress.Progress`](https://rich.readthedocs.io/)** — the same
  progress-bar library the CLIs already use (`vrlab_crane_process.py`,
  `mobi_FOH_assess_data.py`). Used for exactly one case: the very first
  auto-restore on startup happens before `window.show()`, so the Qt
  progress bar would be invisible — `BidsCrosscheckWindow` falls back to a
  terminal bar via `self.isVisible()`, then switches to the normal Qt one
  for every subsequent rescan.
- **[`pyxdf`](https://github.com/xdf-modules/pyxdf)** — FOH-only, for
  reading stream/timestamp info out of `.xdf` files (already a toolbox
  dependency via `processing/lsl.py`).

## Known gaps / TODOs

- **FOH info caching isn't persistent yet** — logged in [BIDS Crosscheck
  Plan](bids_crosscheck_plan.md#todo-deferred-not-scoped-now).
- **Bulk FOH-rename silently skips unpicked subjects** — no warning is shown
  when a subject is skipped because no recording had been picked yet. See
  [BIDS Crosscheck Plan](bids_crosscheck_plan.md#todo-deferred-not-scoped-now).
- **Crane parity with FOH's `CandidateExtras`** — FOH is ahead (rich
  `describe()` info, `task_tag`); crane still uses the no-op base.
  Deliberately one dataset at a time — bring crane's GUI up to match FOH's
  once a good crane-specific info source is identified, not scoped yet.
- **Crane's glob patterns are still placeholders** — see the note at the
  top of `crane_bids_crosscheck_gui.py`; there's no real crane BIDS output
  to check them against yet (see [BIDS Converter
  Plan](bids_converter_plan.md)).

## Testing

`tests/test_bids_crosscheck.py` covers `processing/bids_crosscheck.py`
directly — no Qt, no display needed, plain `unittest.TestCase` with
`tempfile.mkdtemp()` BIDS-folder fixtures (see `TestScanBidsFolder` for the
pattern). GUI-level behaviour has been verified with ad hoc headless
scripts (`QT_QPA_PLATFORM=offscreen`) during development rather than a
committed GUI test suite — worth formalizing if this tool keeps growing.

---

**Also see:** [FOH Crosscheck](foh-crosscheck.md) for the user-facing
walkthrough, and [BIDS Crosscheck Plan](bids_crosscheck_plan.md) for the
original design rationale.
