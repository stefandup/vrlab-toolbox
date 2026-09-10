# BIDS Crosscheck Plan

## Overview

Raw-to-BIDS conversion for crane and FOH dumps every matching file into the BIDS
folder, duplicates included, since the converter doesn't decide between them.
`ParticipantConfig` (in
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
pipeline (`vrlab_crane_process.exe`, `vrlab_foh_assess_data.exe`).

This tool assumes a populated BIDS folder already exists. Producing one is a
separate, earlier step this plan doesn't cover in detail — see
`bids_converter_plan.md` for how that's actually done for each dataset today
(`cli/crane_convert_to_bids.py`, `cli/foh_import_to_bids.py`).

## Current status (as of 2026-08-13)

Both tools exist and are usable — `vrlab_crane_bids_crosscheck` and
`vrlab_foh_bids_crosscheck` (console-script commands via `pip install -e .`,
and packaged as `vrlab_crane_bids_crosscheck.exe`/`vrlab_foh_bids_crosscheck.exe`
via the toolbox installer — see [Building & Releasing](packaging.md)).
Implementation
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
Crosscheck](foh-crosscheck.md) or [Crane Crosscheck](crane-crosscheck.md).
The decisions below (scan types, JSON
recording, no-auto-merge, code layering) are all still accurate — it's
mainly the UI layout that moved on from the original sketch.

**Update (2026-08-27): junk/review became a single delete-and-restore
mechanism, and FOH tagging now writes real BIDS entities.** `crosscheck_junk/`
and `crosscheck_review/` (mentioned throughout this doc below) no longer
exist — `record_subject_junked`/`restore_all_from_junk`/`restore_all_from_review`/
`delete_all_in_review` were replaced by `record_subject_excluded` and
`restore_all_from_bids` (`processing/bids_crosscheck.py`), which delete a
removed subject/candidate outright instead of moving it into a special
folder inside BIDS -- safe only because the raw folder (see "BIDS folder
only" below) is never touched, so it was always the real recoverable copy.
Separately, `task_correction`/`record_task_correction`/`remove_task_correction`
were renamed to `task_tag`/`record_task_tag`/`remove_task_tag`, and FOH's
tag itself changed from a bare non-BIDS `_foh` suffix to real BIDS entities
(`task-foh`, `acq-lsl`, a real `beh` suffix) -- see
`gui/foh_bids_crosscheck_gui.py`'s `FOH_DATASET_CONFIG`. The pipeline-side
physiology lookup (`processing/input_data.py`'s `ParticipantConfig.from_lsl_data`) was
updated to match this new filename shape in commit `8f917fc` (2026-08-28) --
`TASK_LABEL`'s manual sync with `FOH_DATASET_CONFIG.task_tag_task` (two independent
hardcoded strings) is still an open loose end, tracked by the `TODO` at
`processing/input_data.py:14`. The rest of this document (below) still describes the
mechanics in their *previous* shape -- read it for the reasoning, not as a
literal description of current filenames/folders.

## Decision: BIDS folder only, never *writes to* the raw folder

The crosscheck tool's own scanning/renaming logic (`scan_bids_folder`, every
`record_*` decision function) only ever reads/writes inside the BIDS output folder
(including its own junk folder) — it never touches the raw data folder. The one
carve-out is the optional `raw_converter` hook (`gui/bids_crosscheck_common.py`):
both crane's and FOH's crosscheck windows now offer a "Refresh BIDS"/import step
that *reads* the raw folder to copy new subjects across, but that logic lives in
its own separate module (`cli/crane_convert_to_bids.py`, `cli/foh_import_to_bids.py`)
and never writes back into it — "start over" still means re-pointing this tool at a
fresh BIDS folder, not anything that touches raw data.

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
- **`task_correction`** (FOH only) — renames a `recording` file to include `foh`
  in its name. Always available regardless of which LSL streams are present in the
  file (see below) — never gated, since the operator may know things the tool
  can't detect.

## Decision: no automatic collision merging

If a rename (`id_correction`, or a future re-run of the converter) leaves two files
of the same scan type under one subject, that's treated as an ordinary duplicate
and flows into the same `selected_run` review as any other duplicate. Deliberately
no separate merge logic — one mechanism handles both cases.

## Decision: junk means a whole subject; review means "not this pick"

`record_selected_run` (committing a duplicate pick) always sends the
non-selected candidate(s) to `crosscheck_review/`, never `crosscheck_junk/`.
`crosscheck_junk/` is reserved entirely for `record_subject_junked` -- a whole
subject that's genuinely disposable (a pilot run, a non-participant, a test
recording). The two functions never share a destination.

That wasn't the first design. The first version gave `record_selected_run` a
`non_selected_destination` parameter and let the GUI choose junk or review per
commit, on the theory that a duplicate is sometimes genuinely wrong (junk-like)
and sometimes just ambiguous (review-like). In practice this made the GUI worse,
not better: a "Move non-selected to junk" button sitting right next to "Move
non-selected to review" forced a judgment call on every single commit, and
testing it made clear that from the crosschecking seat, an unpicked duplicate
essentially never *feels* like junk in the pilot-data sense -- it's simply not
this pick. Collapsing the choice to always-review removed a source of
friction and confusion without losing anything: "junk" now means exactly one
thing (a whole subject you're removing on purpose), which is also the only
place it was ever unambiguous.

`crosscheck_review/` mirrors `crosscheck_junk/`'s mechanics exactly: same
move-and-mirror mechanism (`_move_to` / `_restore_all_from`), its own
`.bidsignore` entry, its own restore button (`restore_all_from_review`) --
deliberately a *separate* button from "Restore all from junk," not a combined
one, so restoring one can never accidentally sweep up the other.

**Considered and rejected: leaving the non-selected file(s) in place instead of
moving them anywhere.** `scan_bids_folder` derives "ok"/"duplicate" status
purely from how many candidate files are still physically present -- it never
reads `crosscheck.json`. Committing a pick without moving anything aside would
leave the scan finding the same files it always did, so the subject would
immediately look unresolved again (⚠, "Please select correct file") on the very
next scan, as if nothing had been decided -- the recorded decision would exist
but be invisible in the UI, since `_effective_candidate_file` only trusts a
still-"duplicate" scan type's `_pending_selections` (radio-pick) state, which
committing clears. Making "leave it in place" actually work would mean teaching
that resolution logic to fall back to a committed `selected_run` decision even
when raw files still look ambiguous -- a real architecture change, and one that
blurs "decisions are recorded, not applied" (see above), since the file-move and
the decision-record would no longer be the same atomic step. The second-folder
approach gets the same practical outcome (nothing is junked, everything's still
findable) without any of that.

**`delete_all_in_review`** is the one exception to "nothing is ever deleted"
anywhere in this tool -- for once a second crosschecker has actually gone
through `crosscheck_review/` and confirmed none of it is needed, so it isn't
just accumulating forever. Deliberately its own explicit, separately-confirmed
action, not folded into "Restore all from review" or any other button -- the
GUI's confirmation dialog for it says outright that this is the one thing here
that can't be undone.

## FOH: stream indicators for `task_correction`

Reuses `gather_xdf_data_streams()` (`processing/lsl.py`) exactly as
`foh_pipeline.py` already does, to report which of the four expected FOH streams
(`OpenSignals`, `VR_markers`, `VR_trial_events`, `FOH_target`) are present in a
given `.xdf` candidate.

This is shown as an **advisory** indicator next to every `recording` candidate —
it never gates the "Tag as foh" button. Completeness *does* inform which
duplicate to keep, once one is chosen, but doesn't decide whether a file is
foh-eligible.

## Decision: FOH's tagged-file parent folder becomes `beh/`, not `eeg/`

FOH's raw collection folder is always literally named `eeg`, regardless of what's
actually in it -- these are OpenSignals/LSL physiology (and sometimes behaviour)
recordings, not EEG. `record_task_correction` renames that parent folder to
`beh` (`DatasetConfig.task_correction_folder_name`, `foh_bids_crosscheck_gui.py`)
once a recording's confirmed and tagged, carrying along anything else still in
the folder (e.g. an unresolved duplicate not yet picked). `remove_task_correction`
and `revert_all_decisions` rename it back.

`beh` ("behavioral") was picked as the closest fit in BIDS's own datatype
vocabulary -- it's the datatype for task data collected without a concurrent
brain-imaging modality, and the spec explicitly allows continuous physiological
recordings (`_physio.tsv.gz`-style channels) inside it even alone. Alternatives
considered and rejected: `physio` (not actually a valid top-level BIDS datatype
directory -- only a filename suffix within another datatype's folder), `motion`
(a real BIDS-extension datatype, but scoped to kinematic/motion-capture channels,
not EDA/ECG), and `foh` itself (not real BIDS vocabulary at all -- same problem
already avoided in filenames by not tacking `_foh` onto more than the run token).

**Update (2026-09-01): decisions are now a history, not a single record per key,
and a decisions backup can be replayed onto a fresh raw import.** `crosscheck.json`
used to store exactly one entry per `{subject_id}_{scan_type}` key, overwritten by
whichever decision was recorded most recently — so a file corrected twice (e.g.
date-fixed, then tagged) only had the second correction on record, and "Revert all
changes" could only undo that latest step. `load_decisions`/`_append_decision`/
`_latest_decision` (`processing/bids_crosscheck.py`) changed this to an append-only
list per key (oldest first), transparently upgrading an old single-entry file to
`[entry]` on load — no manual migration needed for a `crosscheck.json` already in
use. `revert_all_decisions` now walks each key's history newest-to-oldest, so a
file corrected more than once reverts all the way back to its true original name.
This also made a real disaster-recovery story possible: `backup_decisions` copies
`crosscheck.json`/`excluded_subjects.json`/`crosscheck_pending.json` to a folder of
your choice (deliberately not `crosscheck_info_cache.json` — that's a re-derivable
performance cache, not a decision record), and `rebuild_from_raw` replays a backed-up
history's filesystem effects onto a BIDS folder that's just been freshly re-imported
from raw, resolving out-of-order entries via a retry loop rather than requiring them
in exact chronological order (JSON's `sort_keys=True` write means on-disk key order
was never chronological anyway). Anything that can't be matched against what's
actually on disk is reported unresolved rather than guessed at, in keeping with this
tool's "never guess" philosophy (see the FOH stream-indicators section above). See
[BIDS Crosscheck: Architecture](bids-crosscheck-architecture.md) for the code map.

**Update (2026-09-10): scans.tsv rows can now be bulk-dated or individually removed from the
GUI.** Longwalk's behaviour/events step (`longwalk_behaviour.py`) appends a `scans.tsv` row via
`longwalk_bids.create_bids_events_file_in_folder` alongside its physiology row -- already picked
up by the existing scans.tsv pane (`dates_in_scans_tsv=True` in
`gui/longwalk_bids_crosscheck_gui.py`) with no changes needed there. Two gaps this surfaced:

- That events row was recorded with a hardcoded empty `acq_time`, regardless of what its caller
  passed in -- `create_bids_events_file_in_folder` accepted an `acq_date` parameter but never
  used it. Fixed in `processing/longwalk_bids.py` to actually pass it through. The pipeline caller
  itself (`longwalk_behaviour.py`, protected by `AGENTS.md`'s OVERRIDE, not BYPASS) still calls it
  with `""` today, so existing/new events rows still land empty -- the fix below is how an
  operator backfills them, not an automatic one.
- There was no way to fill a missing date, or remove a stray row, without hand-editing the tsv.
  `processing/bids_crosscheck.py` gained `fill_missing_scans_tsv_dates` (backfills every
  missing/unparseable row for a subject from that subject's own `scans_tsv_reference_date` --
  e.g. copying the physiology row's date onto an empty events row -- never touching a row that
  already has *some* parseable date) and `record_scans_tsv_row_removed` (deletes one row,
  matched by filename *and* acq_time together so it can target one specific line even when two
  rows share a filename -- e.g. a duplicate events line left behind by a reprocessing run, since
  `append_scan_row` never dedupes). Both are recorded decisions, so `revert_all_decisions`/
  `rebuild_from_raw` already know how to undo/replay them. `gui/bids_crosscheck_common.py`
  exposes the first as a "Fill missing scans.tsv dates" action in the Subject/Group Actions panel
  (works the same for one or many selected subjects) and the second as a "Remove row..." button
  next to each scans.tsv row's existing "Edit date...".
- `SCANS_TSV_DATE_FORMAT`/date-parsing (`parse_scans_tsv_date`, `scans_tsv_reference_date`) moved
  from the GUI module into `processing/bids_crosscheck.py` in the process, since
  `fill_missing_scans_tsv_dates` needed the same parsing with no Qt dependency -- the GUI now
  imports these instead of keeping its own copy.

## Deliberately out of scope for now

- **No automatic collision resolution** — see above.
- **No signal/trigger-level QC** (trial intervals, EDA/ECG processing) — that's the
  separately-planned `gui/crane_interval_qc_gui.py` tool's job (see
  `crane_interactive_qc_plan.md`), not this one's.
- **SPIRAL-specific task labeling** — only `foh` labeling is handled for now.
  Files not recognized as foh are left untouched and still shown as plain,
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

FOH's `recording` section shows the stream indicators and always-available tag button:

```
recording (3 files) — pick one:
  ( ) ..._run-1_eeg.xdf   streams: OpenSignals✓ VR_markers✓ VR_trial_events✗ FOH_target✗
  (•) ..._run-2_eeg.xdf   streams: OpenSignals✓ VR_markers✓ VR_trial_events✓ FOH_target✓  [Tag as foh]
  ( ) spiral_2024....xdf  streams: OpenSignals✓ VR_markers✗ VR_trial_events✗ FOH_target✗
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

Related: `input_data.py:15`'s `PIPELINE_ID = "foh"` happens to match this
tool's `task_correction_label` (both `"foh"`), but they're independent
hardcoded strings with nothing keeping them in sync — see the TODO at that
line. Likely resolves naturally once the above lands (`PIPELINE_ID`'s
glob-matching role goes away if `from_lsl_data` reads recorded decisions
instead of guessing), so not worth a separate fix before then.

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

**No warning when a bulk FOH-rename can't act on an unpicked subject.**
`_on_rename_all_selected` / `_on_rename_selected_to_task_label` still
silently skip any subject that has more than one candidate and no
picked/committed selection yet (documented in [FOH
Crosscheck](foh-crosscheck.md#working-with-several-subjects-at-once): "a
subject still waiting on that pick is simply skipped") — no feedback that
anything was left undone. Should surface which subjects were skipped and
why (e.g. a summary dialog listing them) instead of failing silently.
Note this is now the *only* remaining "acted on an unselected file" gap:
the related per-candidate mis-click (clicking "Tag as foh"/"Correct
date..." on the wrong one of several duplicate candidates in the
recording pane) is fixed — those buttons only appear on the row that's
actually picked.

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
even then, files already moved to `crosscheck_junk`/`crosscheck_review` or renamed via
`record_task_correction`/`record_date_correction`/`record_id_correction` stay
moved/renamed, since those are real filesystem operations, not just JSON
state. A proper reset would need to reverse those too (move junked files back,
undo renames) to actually leave the folder as it started, not just clear the
recorded decisions — that's the open design question, not just the UI. Given
how destructive a real "start from scratch" would be across every subject at
once, it needs the same confirm-before-acting treatment as the other bulk
actions ("Move all non-selected to crosscheck_review", "Tag all selected as
  {label}") —
if anything, a stronger one, since unlike those it can't be scoped down to
"just the files that still need it." Not implemented yet.
