# BIDS Crosscheck Plan

## Overview

Raw-to-BIDS conversion for crane and FOH (crane: not yet converted; FOH: partially,
via an external converter) dumps every matching file into the BIDS folder, duplicates
included, since the converter doesn't decide between them. `ParticipantConfig` (in
`processing/input_data.py`) already detects this today: `from_physiology_data` and
`from_lsl_data` both log a warning when zero or multiple files match a subject's
scan type, then silently pick one (`[0]` for crane, `[-1]` for FOH) and move on.

The plan is a small human-in-the-loop desktop tool — modeled loosely on a BIDS
dataset-completeness dashboard from a related project (a Streamlit app that
color-codes a subject x scan-type grid and lets a human pick canonical runs among
duplicates) — that replaces that silent pick with an explicit human decision,
recorded so it doesn't have to be re-made every run.

Two separate tools, one per dataset (crane, FOH), rather than one app with a
dataset switcher — this matches the existing pattern of one standalone `.exe` per
pipeline (`vrlab_crane_process.exe`, `mobi_foh_assess_data.exe`).

This tool assumes a populated BIDS folder already exists. Producing one is a
separate, earlier step this plan doesn't cover — see `bids_converter_plan.md`
for that gap (not yet started for crane; FOH's converter is external to this
repo).

## Current status (as of 2026-08-13)

Both tools exist and are usable — `vrlab_crane_bids_crosscheck` and
`mobi_foh_bids_crosscheck` (console-script commands via `pip install -e .`;
no packaged `.exe` yet, packaging was deliberately deferred). Implementation
went beyond this document's original mockup in a few ways worth knowing
about before reading the layout section below as gospel:

- The subject list became a two-column table (icons in one column, the
  advisory info — FOH's date/duration/streams, or a "Please select correct
  file" prompt — in a separate column next to it), not one combined line
  per subject as originally sketched.
- A `crosschecked` marker (manual "I've reviewed this" flag, independent of
  file status) was added — not in the original decision list above.
- Picking a duplicate's canonical file is now two-step: pick (preview,
  marked ⏳) then a separate commit (either per-subject or a "commit all"
  button across every subject with a pending pick) — and picks persist
  across app restarts (`crosscheck_pending.json`) even before committing.
- A loading-progress indicator was added (terminal `rich.Progress` bar
  before the window is shown, a Qt progress bar after).

For what's actually built, read [BIDS Crosscheck:
Architecture](bids-crosscheck-architecture.md) and the code itself
(`processing/bids_crosscheck.py`, `gui/bids_crosscheck_common.py`) over this
plan's layout mockup. For how to *use* either tool, see [FOH
Crosscheck](foh-crosscheck.md). The decisions below (scan types, JSON
recording, no-auto-merge, code layering) are all still accurate — it's
mainly the UI layout that moved on from the original sketch.

## Decision: BIDS folder only, never the raw folder

The crosscheck tool only ever reads/writes inside the BIDS output folder (including
its own junk folder). It never touches the raw data folder. Raw-to-BIDS conversion
is a separate, earlier step, outside this tool's responsibility — "start over" means
re-running the converter, not anything this tool does.

## Decision: scan types per dataset

Lowercase, BIDS-style naming:

- crane: `physiology`, `behaviour`, `debrief`
- foh: `recording`

## Decision: decisions are recorded, not just applied

Every human decision is one entry in a per-BIDS-folder JSON (naming follows the
same `crosscheck.json` convention as the project that inspired this), keyed
`{subject_id}_{scan_type}` (or `{subject_id}` alone for `id_correction`), tagged
with a `"type"`:

- **`selected_run`** — picks the canonical file among duplicates; non-selected
  files move to a junk folder inside the BIDS folder.
- **`date_correction`** — rewrites a file's date prefix in place. The JSON entry
  must record the original filename/date, since after the rename the filename is
  no longer available as a record of what it used to be — and the JSON write needs
  to happen atomically with (or just before) the actual rename, so a crash mid-op
  can't lose the mapping.
- **`id_correction`** — batch-renames *every* file for a subject, plus the
  `sub-XXX/` folder itself (BIDS folders use per-subject subfolders). JSON records
  original ID, corrected ID, and the full list of renamed files.
- **`task_correction`** (FOH only) — renames a `recording` file to include `FOH`
  in its name. Always available regardless of which LSL streams are present in the
  file (see below) — never gated, since the operator may know things the tool
  can't detect.

## Decision: no automatic collision merging

If a rename (`id_correction`, or a future re-run of the converter) leaves two files
of the same scan type under one subject, that's treated as an ordinary duplicate
and flows into the same `selected_run` review as any other duplicate. Deliberately
no separate merge logic — one mechanism handles both cases.

## FOH: stream indicators for `task_correction`

Reuses `gather_xdf_data_streams()` (`processing/lsl.py`) exactly as
`foh_pipeline.py` already does, to report which of the four expected FOH streams
(`OpenSignals`, `VR_markers`, `VR_trial_events`, `FOH_target`) are present in a
given `.xdf` candidate.

This is shown as an **advisory** indicator next to every `recording` candidate —
it never gates the "Rename to FOH" button. Completeness *does* inform which
duplicate to keep, once one is chosen, but doesn't decide whether a file is
FOH-eligible.

## Deliberately out of scope for now

- **No rule-based replay** against re-converted raw data — the converter's naming
  is deterministic, so a flat filename-keyed JSON is enough; no need to store a
  replay rule.
- **No automatic collision resolution** — see above.
- **No signal/trigger-level QC** (trial intervals, EDA/ECG processing) — that's the
  separately-planned `gui/crane_interval_qc_gui.py` tool's job (see
  `crane_interactive_qc_plan.md`), not this one's.
- **SPIRAL-specific task labeling** — only `FOH` labeling is handled for now.
  Files not recognized as FOH are left untouched and still shown as plain,
  unlabeled candidates.

## Layout: master-detail split

```
┌────────────────────────────────────────────────────────────────────────┐
│ BIDS folder: C:\...\Crane_BIDS                          [Browse...]    │
│ 42 subjects | physiology: 40/42 | behaviour: 41/42 | debrief: 38/42    │
├─────────────────────────────┬──────────────────────────────────────────┤
│ Subjects      [x] issues only│ sub-014                                 │
│ ──────────────────────────── │ ──────────────────────────────────────  │
│ sub-011   ● ● ○               │ physiology  (1 file)                ✓ │
│ sub-012   ● ○ ●               │   sub-014_..._physiology.acq            │
│ sub-013   ● ● ●               │                                          │
│▶sub-014   ⚠ ● ●●              │ behaviour  (0 files)          MISSING ⚠ │
│ sub-015   ● ● ●               │                                          │
│ sub-016   ● ●● ●              │ debrief  (2 files) — pick one:          │
│  ...                          │   ( ) 20240108_sub-014_redcap_v1.csv    │
│                                │   (•) 20240110_sub-014_redcap_v2.csv    │
│                                │       ⚠ date mismatch vs physiology     │
│                                │       [Correct date...]                 │
│                                │                                          │
│                                │ ──────────────────────────────────────  │
│                                │ [Rename subject ID...]                  │
│                                │ [Move non-selected to junk]             │
└───────────────────────────────┴──────────────────────────────────────────┘
```

FOH's `recording` section shows the stream indicators and always-available rename:

```
recording (3 files) — pick one:
  ( ) ..._run-1_eeg.xdf   streams: OpenSignals✓ VR_markers✓ VR_trial_events✗ FOH_target✗  [Rename to FOH]
  (•) ..._run-2_eeg.xdf   streams: OpenSignals✓ VR_markers✓ VR_trial_events✓ FOH_target✓  [Rename to FOH]
  ( ) spiral_2024....xdf  streams: OpenSignals✓ VR_markers✗ VR_trial_events✗ FOH_target✗  [Rename to FOH]
```

Chosen over a flat table with inline popups (loses room for indicators/buttons
per candidate) and a queue/wizard walkthrough (loses the at-a-glance overview,
though it would have mirrored `crane_interval_qc_gui.py`'s step-through style) —
this keeps a Philani-style overview without one long scrolling page.

## Decision: code layering

Mirrors this repo's existing `cli/` (thin) vs `processing/` (logic) split:

- **`processing/bids_crosscheck.py`** — shared logic: BIDS-folder scanning,
  decisions-JSON read/write, `selected_run`/`date_correction`/`id_correction`/
  `task_correction`, junk-move. Parameterized per dataset (scan-type list, glob
  patterns, which correction types apply). No Qt dependency.
- **`gui/crane_bids_crosscheck_gui.py`** and **`gui/foh_bids_crosscheck_gui.py`**
  — thin PySide6 entry points, one per dataset, each supplying its dataset's
  config to the shared logic and rendering the master-detail layout above.

`processing/bids.py` (events.tsv schema validation) is untouched — different
concern.

## Guardrail: no changes to existing processing code

Confirmed additive-only for everything currently planned:

- Subject/scan-type discovery is new, parallel logic scoped to the BIDS folder —
  not a modification of `ParticipantConfig`, which scans the raw folder for
  pipeline purposes.
- `gather_xdf_data_streams()` and the existing `filename_glob` constants are
  reused read-only, exactly as today's pipelines already use them.
- FOH's `_eeg.xdf`-only filter in `from_lsl_data` is not touched — the crosscheck
  tool does its own broader `*.xdf` scan instead of calling that method at all.

## TODO (deferred, not scoped now)

`input_data.py:83` already has `# TODO: implement cross checking for this
toolbox.`, anticipating this work. Once the crosscheck tool exists and has been
used to produce a curated BIDS folder with recorded `selected_run` decisions,
`ParticipantConfig.from_physiology_data`/`from_lsl_data` should eventually stop
silently picking `[0]`/`[-1]` on duplicates and read those decisions instead.
Not scoped now — deliberately deferred until the crosscheck tool exists and has
been used in practice, per the guardrail above.

**FOH info caching.** `FohCandidateExtras._info_cache` (in
`gui/foh_bids_crosscheck_gui.py`) is in-memory only, so every fresh launch (or
re-`Browse` into an already-visited folder) re-parses every "ok" recording's
`.xdf` from scratch for its date/duration/stream indicators — the main source
of the GUI's noticeable load time. Considered options: `functools.cache`
(session-only, doesn't help restarts), a JSON sidecar cache file inside the
BIDS folder keyed by filename + mtime/size (persists across restarts, travels
with the data folder the same way `crosscheck.json` already does, no new
dependency), `shelve` (persistent but opaque/pickle-based), or a
`platformdirs`-based app-local cache (keeps the BIDS folder clean but loses
the "shared with whoever else opens this folder" benefit). Leaning toward the
JSON sidecar as the simplest fit with the existing pattern. Not implemented
yet.

**FOH rename deselects the subject.** Reported: tagging a recording as FOH
(single or bulk "Rename to FOH") appears to clear the subject's selection in
the list afterward. Distinct from the earlier "Issues-only filter evicting
active selection" bug (already fixed) — that one was the Issues-only
checkbox hiding a subject once its last issue was resolved; this is the
rename action itself losing the row selection, independent of that filter.
Not yet reproduced/root-caused — needs a headless repro before fixing.

**No warning when a bulk FOH-rename can't act on an unpicked subject.**
`_on_rename_all_selected` / `_on_rename_selected_to_task_label` already skip
any subject that has more than one candidate and no picked/committed
selection yet (documented in [FOH Crosscheck](foh-crosscheck.md), step 11:
"a subject still waiting on that pick is simply skipped"). That skip is
silent — no feedback that anything was left undone. Should surface which
subjects were skipped and why (e.g. a summary dialog listing them) instead
of failing silently.

**FOH-tagged file's parent folder keeps its old modality name.** After
"Rename to FOH", the file itself gets `_FOH` in its name, but the folder it
lives in (e.g. `sub-XXX/eeg/`) keeps whatever modality name the raw-to-BIDS
conversion gave it — the folder itself isn't renamed to match. Ideally it
should be, alongside the file. Complication: that folder can hold other,
unselected candidate files that must stay put, so a straight folder rename
only works once nothing else remains in it — otherwise this needs a
different strategy than renaming the folder outright. Needs a closer look
at what's actually left in that folder at tag-time before designing the
fix.

**Crane parity with FOH's GUI improvements.** Everything under [Current
status](#current-status-as-of-2026-08-13) above (two-column subject list,
`crosschecked` marking, pending-selection autosave, commit-all, progress
indicators) lives in the shared `gui/bids_crosscheck_common.py`, so crane
already gets all of it for free. The one thing that's FOH-only is the
*content* of the advisory info column — `FohCandidateExtras.describe()`
(date/duration/stream-presence) has no crane equivalent yet, since crane's
`CandidateExtras` is still the no-op default (see [Architecture: known
gaps](bids-crosscheck-architecture.md#known-gaps-todos)). Worth adding a
crane-specific `CandidateExtras` subclass once there's a good candidate for
what to show (something from the `.acq`/behaviour/redcap files worth
surfacing at a glance) — deliberately deferred, one dataset at a time, FOH
first since it's the one currently in active use.

**"Reset everything" button.** There's currently no single action that undoes
an entire crosscheck session for a BIDS folder — doing it by hand means
editing/deleting `crosscheck.json` and `crosscheck_pending.json` directly, and
even then, files already moved to `crosscheck_junk` or renamed via
`record_task_correction`/`record_date_correction`/`record_id_correction` stay
moved/renamed, since those are real filesystem operations, not just JSON
state. A proper reset would need to reverse those too (move junked files back,
undo renames) to actually leave the folder as it started, not just clear the
recorded decisions — that's the open design question, not just the UI. Given
how destructive a real "start from scratch" would be across every subject at
once, it needs the same confirm-before-acting treatment as the other bulk
actions ("Commit all pending selections", "Rename all selected to {label}") —
if anything, a stronger one, since unlike those it can't be scoped down to
"just the files that still need it." Not implemented yet.
