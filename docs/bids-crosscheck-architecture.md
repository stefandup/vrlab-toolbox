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
  (`vrlab_crane_process`, `mobi_foh_assess_data`, …).
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
| `DatasetConfig` | `processing/bids_crosscheck.py` | One dataset's scan types, glob patterns, and whether/how task-correction (FOH's "rename to FOH") applies. |
| `ScanTypeConfig` | same | One scan type's name + the glob patterns that find its candidate files. |
| `SubjectScan` | same | One subject/scan-type's candidate files, with a `status` property (`"ok"` / `"missing"` / `"duplicate"`, derived purely from file count). |
| `BidsFolderScan` | same | The result of scanning a whole folder — every subject × scan-type, plus `has_issues()`. |
| `CandidateExtras` | `gui/bids_crosscheck_common.py` | The hook dataset-specific GUIs override to add per-candidate info (see FOH below). Crane uses the no-op default. |
| `BidsCrosscheckWindow` | same | The actual master-detail window: subject table on the left, per-scan-type detail panel on the right. |

`BidsCrosscheckWindow` never imports anything crane- or FOH-specific — it
only knows `DatasetConfig` and the `CandidateExtras` protocol. That's what
lets `crane_bids_crosscheck_gui.py` and `foh_bids_crosscheck_gui.py` stay a
few dozen lines each.

## Three files a BIDS folder ends up with

The tool never touches anything outside the BIDS folder it's pointed at
(see the plan's "BIDS folder only" decision). Inside it, three artifacts
appear as you use the tool:

- **`crosscheck.json`** — finalized decisions: `selected_run`,
  `date_correction`, `id_correction`, `task_correction`, `crosschecked`.
  Keyed by `{subject_id}_{scan_type}` (`_decision_key`), except
  `crosschecked` uses a *different* key (`_crosschecked_key`, same base
  plus `_crosschecked`) so marking something crosschecked can never
  overwrite an existing `selected_run` entry for that same subject/scan-type.
- **`crosscheck_pending.json`** — radio picks made but not yet committed
  (`load_pending_selections`/`save_pending_selections`). Kept in a
  *separate* file from `crosscheck.json` on purpose: these aren't decisions
  yet, just in-progress GUI state, autosaved so closing the app before
  clicking "commit" doesn't lose the picks. Filenames only, not full
  paths — re-resolved against a fresh scan's actual candidates on load, so
  a stale entry (file renamed/deleted outside the tool) is silently
  dropped rather than crashing.
- **`crosscheck_junk/`** — where `record_selected_run` moves non-selected
  duplicates, mirroring the subject-folder structure it came from. Nothing
  is ever deleted.

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
`task_correction_available()` to enable the "Rename to FOH" button. Every
parse result is cached per-file in `self._info_cache` for the life of the
window — see the caching TODO below for the next step (persisting that
across restarts too).

Add `settings_app_name` (used as the `QSettings` application name — see
below) unique per dataset, and register a console-script entry in
`pyproject.toml`'s `[project.scripts]`, matching the existing
`vrlab_crane_bids_crosscheck` / `mobi_foh_bids_crosscheck` pattern.

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
- **FOH rename deselects the subject** — tagging a recording as FOH appears
  to clear the subject's list selection afterward; not yet root-caused. See
  [BIDS Crosscheck Plan](bids_crosscheck_plan.md#todo-deferred-not-scoped-now).
- **Bulk FOH-rename silently skips unpicked subjects** — no warning is shown
  when a subject is skipped because no recording had been picked yet. See
  [BIDS Crosscheck Plan](bids_crosscheck_plan.md#todo-deferred-not-scoped-now).
- **FOH-tagged file's parent folder keeps its old modality name** — only the
  file is renamed, not the folder it lives in. See [BIDS Crosscheck
  Plan](bids_crosscheck_plan.md#todo-deferred-not-scoped-now).
- **Crane parity with FOH's `CandidateExtras`** — FOH is ahead (rich
  `describe()` info, `task_correction`); crane still uses the no-op base.
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
