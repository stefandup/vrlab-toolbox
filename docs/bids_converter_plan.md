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

## Out of scope for now

- Actual implementation — this is a scoping placeholder, not a design.
- Whether crane and FOH end up sharing one converter or stay separate
  (the crosscheck tool itself deliberately stayed one-tool-per-dataset;
  the converter doesn't have to follow the same split).
