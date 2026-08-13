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
