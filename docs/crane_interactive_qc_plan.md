# Crane Interactive QC Plan

## Overview

Currently, Crane trigger-interval QC (`crane_trial_intervals.py`) works by
silently auto-correcting: known false triggers get removed, and
behaviour-to-trigger matches get accepted even when their timing delta
exceeds the expected tolerance, with only a log warning either way. The plan
is to replace this with an interactive QC step: instead of automatically
removing or accepting questionable trigger intervals, run explicit trigger
quality checks (e.g. duration, timing delta, eventually signal/voltage
stability) and flag the results graphically for a human to review.

First iteration (this doc's current scope): a standalone PySide6 app that
visualizes the trigger intervals and the behaviour-to-trigger matching the
pipeline currently produces, and lets someone step through and manually
correct the matching one pair at a time. Standalone/packaged distribution
matters because this tool is meant to be usable by students without them
touching the underlying pipeline code.

Scope beyond this (which fixes become automatic vs. flagged, data
persistence, additional quality tests, integration point in the pipeline)
is intentionally undecided until a working version exists to learn from.

## Decision: Phase 1 needs no changes to `processing`

`match_crane_behav_intervals_with_trigger_intervals` (in
`processing/crane_trial_intervals.py`) doesn't currently return per-match
deltas or the predicted trigger intervals it computed them against — only
the matched `TrialIntervals` and a pass/fail `status`. Rather than changing
`processing` to expose that, the QC/GUI layer can independently call
`get_crane_predicted_trigger_intervals` on the same behaviour data and
recompute each match's delta itself, using only what `processing` already
returns.

This means Phase 1 can be built with zero changes to `processing` — the
working pipeline stays untouched, and any changes to the matching logic
itself get deferred until the QC tool has actually revealed whether they're
needed. This follows the existing "preserve working behaviour, improve one
structural issue at a time" working rule already in
`pipeline_next_steps.md`.
