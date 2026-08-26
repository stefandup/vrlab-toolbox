# BIDS Converter Plan

## Overview

`bids_crosscheck_plan.md`'s crosscheck tool assumes a populated BIDS folder
already exists to point it at. That earlier step — raw-to-BIDS conversion —
doesn't exist in this toolbox today: FOH is partially converted via an
external converter (not part of this repo, exact tooling/location unknown),
and crane has no converter at all. `pipeline_next_steps.md` item 22 flags
"move toward BIDS" as a direction for the import layer, but that's about
`ParticipantConfig` reading from timepoint folders, not about producing a
BIDS folder in the first place.

**Not yet started.** This page is a placeholder recording that the gap
exists and where it sits relative to related work, so it doesn't need to be
rediscovered from scratch later — not a design.

**Update: crane's converter now exists** — `cli/crane_convert_to_bids.py`
(`convert_crane_to_bids()`), copy-only and incremental (skips subjects
already present in the output folder), integrated directly into
`gui/crane_bids_crosscheck_gui.py` via a "Convert to BIDS..." button (raw
folder + BIDS folder + an optional debrief-workbook override selector, all
in the crosscheck window itself — see `bids_crosscheck_common.py`'s generic
`raw_converter`/`override_file_label` hooks, which FOH doesn't use and gets
no UI for). The debrief design idea below is implemented as described: each
subject gets their own extracted row, written `..._debrief_events.tsv`
(tab-delimited, not the whole shared workbook). FOH's converter is still
external, as noted above.

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

## Known constraints from related work

- **The converter should dump, not decide.** `bids_crosscheck_plan.md`'s
  whole premise is a converter that "dumps every matching file into the
  BIDS folder, duplicates included," with a human resolving duplicates
  afterward. A converter that already picked canonical runs itself would
  make the crosscheck tool partly redundant — keep that division of labor
  deliberate rather than let the converter creep into picking winners.
- **FOH:** whatever the existing external converter already produces is
  real precedent (naming convention, `sub-XXX/` layout) worth inspecting
  before designing anything crane-side, rather than inventing a scheme from
  nothing.
- **Crane:** no naming convention decided yet. The crosscheck tool's own
  glob patterns (`processing/bids_crosscheck.py`'s `CRANE_DATASET_CONFIG`,
  in `gui/crane_bids_crosscheck_gui.py`) are currently guesses grounded in
  `bids_crosscheck_plan.md`'s mockup — a real converter's output naming is
  what should settle those, not the other way around.
- **Debrief file, design idea (not decided):** the raw debrief source is one
  shared REDCAP workbook (`crane_debrief_behaviour.REDCAP_FN`) covering every
  subject, not a per-subject file. Copying that whole workbook as-is into
  every `sub-XXX/` folder (one `*redcap*` glob match each) would work
  mechanically but duplicates every other subject's row into each subject's
  folder for no reason. Discussed alternative: the converter extracts just
  that one subject's row and writes it as its own per-subject file, in the
  same spirit as `crane_behaviour.RawCraneBehaviourData.to_bids_events()`
  already does for behaviour (a `BidsEventsData`/events-style output) — i.e.
  a small per-subject debrief file, not a duplicated multi-subject workbook.
  Not spec'd further than that; revisit once a converter is actually being
  built.

## Out of scope for now

- Actual implementation — this is a scoping placeholder, not a design.
- Whether crane and FOH end up sharing one converter or stay separate
  (the crosscheck tool itself deliberately stayed one-tool-per-dataset;
  the converter doesn't have to follow the same split).
