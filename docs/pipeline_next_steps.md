# Pipeline Next Steps

Consolidates the former `project_next_steps.md` and `refactor_pipeline_plan.md`.
Items confirmed resolved in the code have been dropped; only still-open work
remains below.

## Current State

The toolbox is a modular processing package: pipeline orchestration, EDA
processing, ECG processing, VR interval creation, FOH target processing, XDF
loading, and Biopac loading are separated out.

`crane_pipeline.py` is the pilot implementation of the generic
`PipelineTemplate` defined in `pipeline.py`: import steps, behaviour/debrief
processing, interval matching, and physiology processing are each
strategy-style steps, wired together via `SequentialBehaviourImportSteps`,
`SequentialBehaviourProcessingSteps`, `SequentialPhysiolgyImportSteps`, and
`SequentialPhysiologyProcessingSteps`. The pipeline returns a single
`PipelineOutputData`-derived object with a participant-level dataframe, an
optional QC figure, and a `PipelineStatus`.

**Focus:** get Crane's contract, tests, and cleanup solid first.
**Deferred:** FOH and LongWalk alignment work waits until Crane passes (see
[Deferred: FOH & LongWalk](#deferred-foh--longwalk) at the end). **Update:**
FOH's exception-handling gap was investigated and partly fixed ahead of this
plan, on its own branch — see item 21.

### Note on the original design doc vs. what was actually built

The original refactor plan sketched a `CranePipeline` dataclass with
`behaviour_strategy_steps` / `physiology_strategy_steps` fields plus
`qc_strategy` / `saving_strategy` protocols (`DataQcStrategy`,
`SavingDataStrategy`). What actually exists in `pipeline.py` is
`PipelineTemplate`, with `sequential_behaviour_processing_steps` /
`sequential_physiology_processing_steps` naming, and it does not have QC or
saving strategy steps at all. The Template/Strategy/Composite/null-object
design intent still holds — decide separately whether QC/saving should
become strategy steps too, or stay outside the template.

## Open Work

**Refresh pass, 2026-08-28:** ran the full suite (`MPLBACKEND=Agg python -m pytest tests/`) and
spot-checked several items below against current code (file existence, `grep -rn TODO src/`,
current line numbers). Result: 121 passed, 3 skipped (unchanged — items 15's double-trigger
tests and the still-empty `test_long_walk_pipeline.py`, per item 26), **1 new failure** —
`test_foh_pipeline.py::TestFOHPipeline::test_batch_processing`, root-caused as the FOH
physiology lookup not matching the new real-BIDS task-tag filename shape (a double `sub-`
prefix from `lsl.get_subject_id`). Fixed the same day in commit `8f917fc` ("Both Crane and FOH
batches working again. Tests passed.") — no longer an open item. Everything else checked
(items 18, 19, 26) is still accurate as written — no other drift found this pass.

### 1. Decide: mutate-in-place vs. return-new-object

`PipelineOutputData.append_dataframe()` mutates `self` and returns `None`,
while `PipelineOutputData.merge()` and `PipelineStatus.merge()` build and
return a new instance. This mismatch previously caused a real bug (a debrief
step assumed fluent chaining that `append_dataframe` doesn't provide, and a
separate call site discarded a `PipelineStatus.merge()` result) — both
instances have since been fixed by hand, but the underlying inconsistency
that caused them is still there and will keep producing this class of bug as
more strategy/status classes are added.

Two options, not yet decided:

1. **Fluent style** — mutating methods return `self`, enabling
   `Output(id).append_dataframe(...)`. Smaller diff given existing call
   patterns, but makes mutation less visually obvious.
2. **Void style** — mutating methods stay `-> None`, always require a
   separate variable before use. More explicit, more verbose at call sites.

Guidance for picking, generally:

- Prefer mutate-in-place, return `None` for accumulator-style objects built
  up over a loop (e.g. the raw data stores) — one clear owner, no aliasing
  risk.
- Prefer return-new for small value-like objects that get compared, tested,
  or passed around (e.g. status objects) — but only if every call site can
  be trusted to reassign. Consider naming methods to make the contract
  obvious (e.g. `with_merged(...)` instead of a bare `merge(...)`).
- Never mix both behaviours across sibling methods on the same class.
- Whichever convention is chosen, add a one-line docstring note (`"""Mutates
  self in place."""` or `"""Returns a new instance; does not mutate
  self."""`).

Apply the chosen convention consistently across `PipelineOutputData`,
`PipelineStatus`, and any future strategy result objects.

**Further rethink needed:** per-step tracking (above) still isn't enough on
its own. `PipelineStatus.merge()` currently combines statuses into a single
enum per stage/step, with no room to record *which data type* produced an
error or *why*. Storing datatype + error detail per data type, rather than
folding everything into one merged enum, is likely necessary — otherwise a
merged status can say `intervals=error` without retaining the underlying
cause once several sources have been merged together.

### 2. Track processing status per-strategy, not just per-stage

`PipelineStatus` (`processing_status.py`) only tracks stage-level outcomes
(`data_in`, `behaviour`, `intervals`, `physiology`). When a `Sequential*Steps`
container runs multiple strategy steps, a failure in any one step only shows
up as a single stage-level status — there's no way to tell which individual
strategy within the sequence succeeded, was skipped, or failed.

Needed:

- track status per-step (e.g. keyed by step/class) rather than only
  per-stage;
- decide whether `intervals=error` should stop physiology processing or mean
  physiology was attempted but shouldn't be trusted;
- serialize statuses in a fixed order so tests and CSV/SPSS outputs don't
  depend on update order.

**Update:** the first bullet is done — `PipelineStatus.status`
(`processing_status.py`) is now `dict[type, ProcessingStatus]`, keyed by data
type (`RawCraneBehaviourData`, `RawDebriefBehaviourData`, `RawBioData`,
`TrialIntervals`, …) instead of fixed `data_in`/`behaviour`/`intervals`/
`physiology` fields, and `tests/test_crane_pipeline.py` asserts against
per-type entries directly (e.g. `pipeline_out.status.status[RawBioData]`).
The two leftover `# TODO` comments on the class (`processing_status.py:18-19`)
are now stale relative to the code and can be removed. The third bullet
(fixed serialization order) is **not** explicitly done: `get_as_text()`
iterates `self.status.items()` in dict-insertion order, which is stable today
only because `PipelineTemplate.run()` always calls `.merge()` in the same
fixed sequence — reordering pipeline steps in the future would silently
change the output string and break tests doing exact-string comparison
(`all_ok_status_str` and friends in `tests/test_crane_pipeline.py`). Worth an
explicit sort (e.g. by type name) in `get_as_text()` rather than relying on
call-order coincidence.

### 3. Consolidate duplicated Crane behaviour constants

`EMOTIONS_TESTED`, `BLOCK_TYPES`, `TRIAL_TYPES`, and `BEHAVIOUR_OUTPUT_METRICS`
are each defined independently in more than one place: `crane_pipeline.py`
has its own full copies of all four; `crane_debrief_behaviour.py` separately
redeclares its own `EMOTIONS_TESTED` (as a tuple, not a list) and
`TRIAL_TYPES`. None of these import from a shared source, so keeping them in
sync depends on remembering to edit all copies by hand.

`crane_behaviour.py` is the natural single source of truth, since it's where
these are actually used to build and validate the behaviour schema
(`build_crane_raw_behav_file_schema`, the `EmotionFeedback` isin-check, the
`EMOTIONS_TESTED` reindexing in the summary functions).

Needed:

- move `EMOTIONS_TESTED`, `BLOCK_TYPES`, `TRIAL_TYPES`, and
  `BEHAVIOUR_OUTPUT_METRICS` into `crane_behaviour.py` as canonical
  definitions;
- update `crane_pipeline.py`'s schema-building functions to import them
  instead of redeclaring;
- update `crane_debrief_behaviour.py` to import `EMOTIONS_TESTED` /
  `TRIAL_TYPES` too, deciding on one canonical type (list vs. tuple);
- ~~remove the now-dead `from mooi_toolbox.processing import crane_behaviour as
  crane_behaviour` import in `crane_pipeline.py`~~ **Done** — the dead import is gone
  (was also tracked as item 19, now removed);
- add a small test asserting debrief and pipeline column names line up with
  the behaviour schema's.

### 4. Clean up behaviour-data file matching and loading

`behaviour.py`'s `load_and_validate_behaviour_csv`,
`load_validate_physiology_behav_data`, and `load_from_participant_config`
overlap heavily, and only one path (`load_from_participant_config`, via
`RawBehaviourData.load_from_config`) is actually used by the Crane pipeline
— the other two appear to be dead code. File matching itself
(`behaviour_matches_biopac_physiology_data`) builds its search purely from
the physiology file's stem, silently assuming the `.mat` and `.csv` files for
a session share an identical timestamp prefix.

This is a real bug, not just theoretical mess: participant `PID15868`'s
behaviour CSV was exported with a different timestamp than its `.mat` file
(`...5121237` vs `...5131237`), so the regex-based match found nothing and
raised a generic `FileNotFoundError`. That cascaded — crane behaviour data
never entered the store, so interval matching and physiology processing
failed too, in a way that looked like a pipeline logic bug and took real
effort to trace back to "the file search just didn't find the file, for an
uninformative reason."

Needed:

- one reusable function/contract for "find this participant's file(s) of
  type X," used the same way across behaviour, debrief, and physiology
  loading instead of ad hoc `Path.rglob` + regex per case;
- report *why* a file wasn't found in a way that's distinguishable in logs —
  "no file for this subject at all" vs. "a file exists but doesn't match the
  expected pattern" are different problems and currently produce the same
  generic error;
- don't assume filename conventions (like matching timestamps across file
  types) hold for every participant;
- remove the redundant/dead loading functions once the used path is clear.

**Update:** the core "find this participant's file(s) of type X" contract now
exists — `ParticipantConfig.from_physiology_data` (`input_data.py`) does
physiology + behaviour file discovery via a per-type `filename_glob` class
attribute (`RawBehaviourData.filename_glob`, overridden on
`RawCraneBehaviourData`/`RawDebriefBehaviourData`), driven by
`FindCraneParticipantFilesStrategyStep` (`crane_pipeline.py`). It still
raises on failure rather than reporting distinguishable reasons in
logs/status — see item 12 for the remaining work.

### 5. Add a fallback for partial/missing behaviour data using unlabelled intervals

If behaviour data is partial or missing, interval matching currently has no
fallback: `CraneGetTrialIntervalStrategyStep` needs the behaviour dataframe
to label and match trigger intervals, so a missing/partial behaviour import
cascades into `intervals=error` and physiology is skipped entirely (see
`test_crane_pipeline_labels_missing_behav_correctly`,
`test_crane_missing_debrief_correct_label`).

The old QC procedure had a fallback for exactly this case: when behaviour
labels aren't available, fall back to the raw, unlabelled trigger intervals
so physiology processing can still run. This needs to be reintroduced.

Needed:

- decide where the fallback lives — likely a variant path in
  `CraneGetTrialIntervalStrategyStep.run` (or a fallback strategy step) that
  returns unlabelled intervals when `raw_behaviour_data_in` is unavailable or
  only partially usable;
- decide what `intervals` status means in this case — probably `partial`
  rather than `error`, since physiology can still run on unlabelled
  intervals;
- decide how unlabelled intervals should be named/columned in the
  participant-level output, since the current naming scheme
  (`{metric}_{block_type}_{trial_type}`) assumes labelled intervals;
- add a test mirroring the old QC case: partial/missing behaviour data still
  produces physiology output, using unlabelled intervals, with a `partial`
  status rather than `error`.

**Update:** a fallback mechanism now exists —
`CraneGetTrialIntervalStrategyFallbackStep` (`crane_trial_intervals.py`) is
wired as `CraneGetTrialIntervalStrategyStep.fallback_strategy`, and
`PipelineTemplate.run()` (`pipeline.py:370-381`) calls it when
`get_interval_strategy.run()` raises `(TypeError, ValueError)`, returning
unlabelled trigger intervals via `get_raw_biopac_trigger_intervals` +
`get_biopac_trigger_intervals_pipeline`, marked `TrialIntervals=ERROR` in the
resulting status. This covers the "behaviour data present but alignment
fails" case. It does **not** yet cover this item's original "behaviour data
missing entirely" case: `raw_behav_data_for_intervals` being `None` is
handled by an outer guard (`pipeline.py:362`) that skips straight to "no
trial intervals, skip physiology" *before* `get_interval_strategy.run()` (and
therefore the fallback) is ever reached — see item 17's own note on this. Still
needed: decide whether the `None`-behaviour-data case should also route
through `fallback_strategy`, or whether that's a deliberately separate
decision from the present-but-failed case.

### 6. Extend Pandera dataframe contracts beyond Crane's own schemas

Crane already has schemas for its own dataframe shapes: raw behaviour CSV
(`build_crane_raw_behav_file_schema`), raw debrief file
(`crane_raw_debrief_file_schema`), behaviour/debrief/participant output
(`build_crane_behaviour_output_schema`, `build_crane_debrief_output_schema`,
`build_crane_participant_output_schema`), and the shared base output schema
(`build_base_pipeline_output_schema`).

Still missing, mainly around shared physiology loading:

- OpenSignals EDA / ECG data;
- Biopac EDA / Trigger data;
- VR marker streams / VR trial event streams (FOH-specific, see deferred
  section).

Keep validating mainly at boundaries (after loading, after
renaming/normalizing columns, before analysis functions, after producing
participant-level output) rather than every intermediate dataframe.

### 7. Small cleanup

- Replace remaining `print()` calls with logging — one left in `ecg.py:30`
  (not currently wired into the Crane run).
- Fix obvious return type hints, especially functions that can return
  `None`.
- Fix small robustness issues in loading and missing-column handling.
- Nullable figures in CLIs, consistent status handling.

### 8. Outstanding `# TODO` comments (still present in code)

Reconciled again against a fresh `grep -rn TODO src/` during this REVIEW.
Since the last reconciliation: the two `crane_pipeline.py` TODOs that
annotated `CraneDebriefOutputData`/`build_crane_debrief_output_schema` are
gone, because that dead code was deleted (see the now-removed item 11); the
`pipeline.py:181` "printout the rest" TODO and the `behaviour.py:16` "messy,
half these functions may be redundant" TODO have also disappeared from the
code (the comments were dropped, not the underlying issues — item 2's
ordering gap and item 4's dead-code cleanup are both still genuinely open,
just no longer marked inline); several other TODOs shifted by a line or two
from unrelated edits nearby (noted below) without changing meaning.

- `processing/pipeline.py:17` — could this form part of pipeline as a class
  override?
- `processing/pipeline.py:149` (was `:139`) — make the Sequentials
  unmodifiable, i.e. you can inherit from them.
- `processing/output_data.py:30` — fix that on init it already inits an
  empty participant output data using config.
- `processing/crane_pipeline.py:155` (was `:153`) — needs a classmethod to
  avoid future errors when implementing pipeline.
- `processing/crane_debrief_behaviour.py:28` — more checks possible here.
- `processing/crane_debrief_behaviour.py:95` (was `:93`) — fix this, likely
  out of scope.
- `processing/crane_behaviour.py:12` — convert to tuple.
- `processing/crane_behaviour.py:202` (was `:200`) — see if using BIDS might
  simplify things long-run.
- `processing/behaviour.py:52` (was `:53`) — decide what to do when multiple
  CSV files are found.
- `processing/trial_intervals.py:446` (moved from the now-deprecated
  `crane_trial_intervals.py`) — needs to update with a `partial` status.
- `processing/input_data.py:16` — "Add PipelineStatus to config." Likely the
  seed of item 12: `ParticipantConfig` construction currently raises
  immediately on file-discovery failure; giving the config its own
  `PipelineStatus` field is what would let failures be recorded instead of
  raised.
- `processing/input_data.py:82` (was `:81`) — "implement cross checking for
  this toolbox." Reads as a check that the physiology file and each
  discovered behaviour file actually belong to the same session/date, rather
  than trusting the filename match — the kind of check that would have
  caught the `PID15868` timestamp-mismatch bug (item 4) before it cascaded,
  and would also have caught item 13's date-string bug sooner (now fixed —
  the item-13 section itself has been dropped, see this doc's own convention
  of removing resolved items).
- `processing/trial_intervals.py:19-20` — `MappingProxyType` guard and dunder
  overrides. About hardening the `TrialIntervals` container itself: guard
  against accidental mutation of the sorted interval list, and add
  `__len__`/`__eq__`/etc. so intervals can be compared/iterated directly
  instead of reaching into an internal attribute.
- `processing/trial_intervals.py:279` — "Flag points where voltage drops
  below ~4.8V (Arduino signal instability)." Directly relevant to item 15:
  the working theory is voltage sag causes spurious threshold crossings: this
  TODO is a proposed diagnostic to confirm that theory, rather than only
  filtering the resulting double triggers after the fact.

### 9. Manual QC tool for clock drift verification

The Crane clock/timestamp alignment issue has been corrected, but confirming
it holds across additional participants and files isn't something test
assertions alone can settle — the automated matching
(`match_crane_behav_intervals_with_trigger_intervals` in
`crane_trial_intervals.py`) can silently pick a wrong-but-plausible match
rather than failing loudly, so a manual QC tool is likely needed to visually
spot-check trigger/behaviour alignment per participant/file.

Needed:

- decide what the tool should show: e.g. predicted vs. actual trigger start
  times, matched deltas per interval, and any unmatched behaviour keys,
  plotted against time;
- reuse the existing QC figure plumbing on `PipelineOutputData` where
  possible rather than building a separate ad hoc script;
- decide if this is a one-off manual check for participants already flagged
  as suspect, or a routine QC step run for every participant before trusting
  matched intervals.

**Update (trigger re-alignment refactor, merged to master):** the
crane-specific regression matcher `align_crane_behav_intervals_with_trigger_intervals`
(`crane_trial_intervals.py`, `@deprecated`) has been superseded by a more
general `align_biopac_trigger_drift_from_behav_file` (`trial_intervals.py`),
now called from `CraneGetTrialIntervalStrategyStep.run`. The surrounding
pipeline also gained: a check on trigger interval count against
`EXPECTED_INTERVAL_NR`, known-false-trigger removal
(`remove_biopac_known_false_triggers`), gap filling, and removal of a
spurious extra trigger caused by a late experiment start
(`remove_crane_delayed_start`). Per the WIP commit history on the refactor
branch, interval matching and test-run coverage improved, but the last
recorded state before merge still had some subjects not passing — this needs
re-verification against current `tests/test_crane_pipeline.py` results, and
is exactly the kind of per-subject check this manual QC tool is meant to
cover. `align_crane_behav_intervals_with_trigger_intervals` and its
`get_crane_predicted_trigger_intervals` helper were deleted 2026-09-11 (see item 26) on a
zero-callers check, ahead of the per-subject stability re-verification this paragraph flags as
still needed — if that re-verification later surfaces a real regression, these functions'
history is still in git if a fallback matcher is needed again.

### 10. Document intentional behaviour change: partial data now survives biopac import failure

Master's `crane_pipeline.run_pipeline` loaded biopac EDA data first and
returned immediately via `CranePipelineOutput.error(...)` on failure — a bare
row with only `Subject_ID`/`Processing_Status`, discarding behaviour and
debrief data too. The `PipelineTemplate`-based pipeline processes
behaviour/debrief and physiology as independent stages (`pipeline.py:254-348`),
so a subject with a missing/corrupt biopac file now still gets full
behaviour/debrief columns, with `data_in`/`physiology` marked `error` and
physiology columns left empty, instead of an almost-empty row.

This looks like the right behaviour (partial data beats no data), but it's a
real change in what a "biopac failed" subject's output row looks like, so:

- confirm with anyone consuming the CSV/SPSS output that partial rows are
  expected and won't be mistaken for successfully-processed subjects;
- consider whether downstream filtering (e.g. by `Processing_Status`) needs
  updating now that `physiology=error` rows can still carry valid behaviour
  data.

### 12. ParticipantConfig file discovery: make failures report status instead of raising

`ParticipantConfig.from_physiology_data` (added this session, `input_data.py`)
now self-populates a participant's config from a bare subject ID: it finds
the physiology file, derives a date string from its filename, and finds each
configured behaviour file type (via `filename_glob` class attributes on
`RawBehaviourData` subclasses) under `behav_folder`.
`FindCraneParticipantFilesStrategyStep` (`crane_pipeline.py`) wires this up
for Crane, using `PhysiologyFileFormat` (Enum, `input_data.py`) and the two
Crane behaviour types.

**Current behaviour (revised — the paragraph below is stale, kept for
history):** ~~every failure path (physiology missing/ambiguous, a behaviour
type missing/ambiguous, or a date mismatch between the physiology and
behaviour filenames) raises `FileNotFoundError`/`ValueError` immediately, at
construction time.~~ As of this pass, `from_physiology_data` no longer raises
on any of these paths: a missing/ambiguous physiology file, a missing/
ambiguous behaviour file, a date mismatch, and a non-alphanumeric participant
ID all go through `logger.warning(...)` instead, and construction always
returns a `ParticipantConfig`. Missing behaviour files store `None` in
`_behaviour_file_names[type]`; a missing physiology file is tracked
internally as `None` too, but flattened to `physiology_fn=""` on the returned
dataclass rather than kept as an optional `Path` — an inconsistency with the
behaviour side worth resolving (see revised step 3 below).

**Why physiology stays required/raising for now:** superseded — physiology is
already effectively optional in practice (warns instead of raising, same as
behaviour), just represented with an empty-string sentinel instead of `None`.

**This broke `tests/test_crane_pipeline.py`:** superseded. The four bad-data
IDs (`CRANE_PARTICIPANT_NO_FILE_ID`, `CRANE_PARTICIPANT_NO_BEHAV_BAD_DATE_ID`,
`CRANE_PARTICIPANT_NO_DEBRIEF_ID`, `CRANE_PARTICIPANT_INCORRECT_DATE_ID`) are
now plain module-level string constants, passed straight into `run_pipeline(...)`
or built into a `ParticipantConfig` lazily inside a test's `setUp`/method body
— not eagerly-constructed `ParticipantConfig` objects at module import time.
Import-time crashes from this are no longer possible, both because of this
restructuring and because construction itself no longer raises.

Agreed next steps, revisited:

1. **Done.** `_behaviour_file_names` is `dict[type, Path | None]`; every
   requested behaviour type is always present as a key, `None` if no file was
   found.
2. **Not done.** `from_physiology_data` still returns a bare
   `ParticipantConfig`; failures only reach a `logger.warning(...)` call, with
   nothing structured returned for a caller (e.g. `PipelineTemplate.run()`) to
   fold into its own `PipelineStatus`. (The module-level
   `logger = logging.getLogger(__name__)` this step called for already exists
   in `input_data.py` now — that part of the original note is stale.) Still
   needed: return `tuple[ParticipantConfig, PipelineStatus]` and mark the
   relevant status field at each warning site instead of only logging.
3. **Answered in practice, but inconsistently.** "Subject doesn't exist"
   already applies to physiology as well as behaviour — physiology no longer
   raises. The open part now is representation: behaviour uses `Path | None`
   per type, physiology uses `""` as its missing-sentinel on a `str`-typed
   field. Worth standardizing both to `Path | None`, or writing down why the
   physiology field stays string-typed if that's intentional.
4. **Still open**, blocked on (2): once `from_physiology_data` returns a
   `PipelineStatus`, decide where it merges into `PipelineTemplate.run()`'s
   own status, which currently always starts fresh with no way to seed it
   from a config-construction stage.
5. **Resolved / no longer applicable.** See the "This broke..." note above —
   the fixtures were restructured (or never needed restructuring, since
   construction stopped raising) and no longer crash test collection.

Also confirmed and no longer open: `RawCraneBehaviourData`'s inherited
`filename_glob` pattern matches real Crane behaviour filenames.

### 14. Write a rename script for participant files with label mismatches

Many participant files are currently skipped during import not because the
data is missing, but because filenames don't match the expected
`filename_glob` pattern (`ParticipantConfig.from_physiology_data`, items 12
and 13) — inconsistent or mislabelled filenames across sessions cause the
matcher to silently find nothing.

Needed:

- audit how many currently-excluded files are label mismatches vs. genuinely
  missing data;
- write a rename script to normalize filenames to the expected convention,
  rather than continuing to special-case each mismatch inside the
  glob/matching logic itself;
- decide whether this is a one-off, hand-reviewed cleanup pass or a
  repeatable normalization step run before each import;
- keep a record (log or mapping file) of any renames performed, so original
  filenames aren't silently lost.

### 15. Double triggers still causing problems

Even after the trigger re-alignment refactor (item 9 update), double/duplicate
triggers are still causing problems in interval matching. The current
filtering (`remove_biopac_known_false_triggers`, `trial_intervals.py`) drops
intervals with near-zero or too-short duration, and raw trigger detection
itself (`get_raw_biopac_trigger_intervals`) is a simple threshold-crossing
diff (`trigger_df_in["Trigger"].diff() > 0.47`) — neither appears sufficient
to catch every double-trigger case in practice.

Needed:

- characterize when/why double triggers occur (Arduino bounce? voltage noise
  near the threshold? something else) rather than only filtering symptoms
  after the fact;
- decide whether stricter detection at the source (`get_raw_biopac_trigger_intervals`)
  or better post-hoc filtering (`remove_biopac_known_false_triggers`) is the
  right fix, or both;
- add a regression test/fixture using data known to exhibit double triggers,
  so this doesn't silently regress again.

### 16. Two `UnboundLocalError` crashes in `pipeline.py`, plus a silent status-misattribution bug

Found while revamping `tests/test_crane_pipeline.py` to match the new
type-keyed `PipelineStatus` (see item 2 — `PipelineStatus` now holds
`status: dict[type, ProcessingStatus]` instead of fixed `data_in`/
`behaviour`/`intervals`/`physiology` fields, with a `.set(data_type, status)`
method). Running `run_pipeline` against all fixture IDs used by the test
file surfaced two real crashes and one silent bug, all sharing the same root
cause: an `except` block references a loop variable that isn't guaranteed to
be assigned.

**Crash 1 — `SequentialPhysiolgyImportSteps.run()` (`pipeline.py`, around
line 206-217):**

```python
for step in self.steps:
    pipeline_status = PipelineStatus()
    try:
        data_out = step.run(config_in)
        self.raw_physiology_store.add(data_out)
        pipeline_status.set(type(data_out), ProcessingStatus.OK)
    except (ValueError, FileNotFoundError) as e:
        ...
        pipeline_status.set(type(data_out), ProcessingStatus.ERROR)  # data_out never assigned
```

If `step.run(config_in)` itself raises (e.g. `BiopacDataImportStartegy` when
the physiology file is missing), `data_out` was never assigned, so
`type(data_out)` in the `except` block raises `UnboundLocalError`. Reproduces
with participant `NOFILES` (`CRANE_PARTICIPANT_NO_FILE_ID` in the test file).

**Crash 2 / silent bug — `SequentialBehaviourImportSteps.run()`
(`pipeline.py`, around line 152-165):**

```python
pipeline_status = PipelineStatus()
for step in self.steps:
    try:
        pipeline_raw_behav_data = step.run(config_in=config_in)
        self.raw_behaviour_data_Store.add(pipeline_raw_behav_data)
        pipeline_status.set(type(pipeline_raw_behav_data), ProcessingStatus.OK)
    except (ValueError, FileNotFoundError) as e:
        ...
        pipeline_status.set(type(pipeline_raw_behav_data), ProcessingStatus.ERROR)
```

Same shape, but worse: `pipeline_raw_behav_data` is declared *outside* the
per-step `try`, so it persists across loop iterations. Two distinct failure
modes:

- If the **first** step in `self.steps` (crane behaviour import) raises,
  `pipeline_raw_behav_data` is unbound → `UnboundLocalError`. Reproduces with
  `PID11136` (`CRANE_PARTICIPANT_NO_BEHAV_BAD_DATE_ID`) and `PID15868`
  (`CRANE_PARTICIPANT_INCORRECT_DATE_ID`).
- If the first step **succeeds** and the **second** step (debrief import)
  raises, `pipeline_raw_behav_data` still holds the *first* step's result
  from the previous iteration — so the `except` block silently marks
  `RawCraneBehaviourData` as `ERROR` (overwriting its correct `OK`), instead
  of marking `RawDebriefBehaviourData`. No crash, just a wrong status.
  Reproduces with `PID8495` (`CRANE_PARTICIPANT_NO_DEBRIEF_ID`) — confirmed
  by running the pipeline directly: `status.status` shows
  `RawCraneBehaviourData=ERROR` even though crane behaviour import genuinely
  succeeded for that participant.

**Fix pattern (not yet applied — deliberately left for a follow-up pass):**
in both loops, capture the *step's own declared output type* (e.g.
`step.behaviour_output_type`, already added earlier this session for exactly
this purpose — see item 12/13 area of history) *before* the `try`, and use
that captured type in the `except` block instead of introspecting a variable
that may not exist yet or may be stale from a prior iteration.

**Update — done:** all three tests are un-skipped and pass:
`test_crane_pipeline_labels_missing_physiology_correctly`,
`test_crane_pipeline_labels_missing_behav_correctly`,
`test_crane_spots_errors_when_behav_physiology_no_match`. The `missing_debrief`
status constant no longer needs (and no longer has) a comment flagging a
`RawCraneBehaviourData` artifact for `PID8495` — `test_crane_missing_debrief_correct_label`
now asserts `RawCraneBehaviourData=OK` / `RawDebriefBehaviourData=ERROR` directly, confirming
the artifact described above is gone.

**Update:** both crashes are fixed, using the described pattern —
`SequentialBehaviourImportSteps.run()` now captures `step.behaviour_output_type`
before the `try`; `SequentialPhysiolgyImportSteps.run()` now has an
`output_data_type` attribute added to `ImportBioDataStrategyStep` (and to
`BiopacDataImportStartegy`, to satisfy the protocol structurally) captured the
same way. A third bug in the same method, not originally documented here, was
also found and fixed: `pipeline_status = PipelineStatus()` was re-created
*inside* the `for step in self.steps:` loop, so with more than one physiology
import strategy only the last step's status would have survived to the
returned tuple — moved above the loop so status now accumulates across all
steps. The three skipped tests above still need un-skipping and their
assertions checked against real output. See item 17 for a follow-on issue
found while chasing a runtime crash caused by this fix landing.

### 17. `PipelineTemplate.run()` interval step: `None` inputs surfacing as `AttributeError`, papered over by widening the except tuple

Found immediately after item 16's fixes landed: with the `UnboundLocalError`
crashes gone, the pipeline runs further and hits a new crash at the
trial-interval step ([pipeline.py:361-377](../src/vrlab_toolbox/processing/pipeline.py#L361-L377)).
When either physiology or behaviour data is missing from its store,
`raw_biodata_for_intervals` / `raw_behav_data_for_intervals` are deliberately
set to `None` a few lines above (lines 344, 354) — but `self.get_interval_strategy.run(...)`
is then still called with those `None`s, and whatever attribute access happens
first inside the strategy's `run()` raises `AttributeError` on `None`.

The crash was silenced by adding `AttributeError` to the `except` tuple at
line 368 (previously `(TypeError, ValueError)`). This works, but only
incidentally:

- it will also swallow an unrelated `AttributeError` raised by a genuine bug
  anywhere inside `get_interval_strategy.run()`, silently routing it into the
  fallback path instead of surfacing it;
- it depends on the strategy happening to hit an attribute access (not, say,
  an item access on `None`, which raises `TypeError` instead) — fragile,
  works by luck rather than by design.

Needed:

- before calling `self.get_interval_strategy.run(...)`, explicitly check
  `raw_biodata_for_intervals is None or raw_behav_data_for_intervals is None`
  and skip straight to the "no intervals" handling already at line 390,
  rather than calling `.run()` with `None` and catching whatever exception
  results;
- once that guard exists, reconsider whether `AttributeError` still needs to
  be in the `except` tuple at line 368, or whether it was only ever masking
  the `None`-input case.

**Update: fixed.** `PipelineTemplate.run()` now guards with
`if raw_biodata_for_intervals is not None and raw_behav_data_for_intervals is not None:`
before calling `self.get_interval_strategy.run(...)` — matching the two
variables actually populated by the `try/except ValueError` blocks just
above. `AttributeError` was removed from the `except` tuple (back to
`(TypeError, ValueError)`), since the `None`-input case it was masking can no
longer reach that call. The inner `raw_biodata_for_intervals is not None`
recheck inside the `except` block is now redundant (the outer guard already
guarantees it) — harmless, candidate for a later cleanup pass, not urgent.

One behavioural note surfaced while fixing this: previously, catching
`AttributeError` let a missing-behaviour-data run crash inside
`get_interval_strategy.run()` and, as a side effect of that crash being
caught, fall into `fallback_strategy` (which only needs biodata) — so
physiology would still run on unlabelled intervals when behaviour was
missing, purely by accident. With the explicit guard, a missing-behaviour run
now skips straight to "no trial intervals, skip physiology" instead, which
matches this doc's own item 5 ("missing/partial behaviour import cascades
into `intervals=error` and physiology is skipped entirely... needs to be
reintroduced") — i.e. this removed an accidental, undocumented side-channel
into item 5's still-open gap, it didn't create a new regression.

### 18. Test suite is flaky on an interactive matplotlib backend, and leaks figures

Found while running the full suite for this REVIEW: `python -m pytest tests/` gave a different
2 failures each run (`TestCraneGetIntervalStrategy::test_interval_correction_with_*`, varying
which one), all `_tkinter.TclError` inside `plot_biopac_interval_qc` (`trial_intervals.py:263`,
via `plt.subplots`) — but each failing test passes in isolation. Root cause: nothing in
`tests/` (no `conftest.py`, no `pytest.ini` setting) forces a non-interactive matplotlib
backend, so the suite falls back to whatever GUI backend is available (`TkAgg` here), and this
machine's Tk/Tcl install (Microsoft Store Python) is incomplete — `init.tcl`/`tk.tcl` fail to
load, apparently only once enough figures have accumulated across tests to trigger it, which is
why failures move around between runs rather than hitting the same test every time. Running with
`MPLBACKEND=Agg` made all 27 non-skipped tests pass consistently, and also surfaced a real
resource leak: `RuntimeWarning: More than 20 figures have been opened. Figures created through
the pyplot interface... are retained until explicitly closed` — plotting code (`eda.py:180`,
`trial_intervals.py:263`) never calls `plt.close()`.

The CLI already does the right thing (`matplotlib.use("Agg")` in `cli/vrlab_crane_process.py:12`);
the test suite doesn't inherit that and shouldn't need to guess a machine's GUI toolkit is even
installed to run reliably.

Needed:

- add a `tests/conftest.py` that calls `matplotlib.use("Agg")` before any test imports
  plotting code, so the suite doesn't depend on a working local Tk install;
- close figures after they're used/asserted-on in tests and in production plotting functions
  (`plt.close(fig)`), rather than leaving them to accumulate for the process lifetime.

### 20. Publish project documentation via MkDocs (`docs/` folder), local-only while the repo stays private

Decided during a REVIEW follow-up conversation: use MkDocs (with the
`mkdocs-material` theme) to build browsable docs from Markdown sources in
`docs/`, aimed at helping students/new contributors ramp up on the pipeline.

While the repo stays private, docs are generated **locally only**
(`mkdocs serve` for a live-reload preview, `mkdocs build` for a static
`site/` folder) — no GitHub Pages deploy yet. This isn't just a preference:
**GitHub Pages does not build from a private repository on the free plan** —
it requires GitHub Pro/Team/Enterprise. So "local-only until the repo is
public (or the plan is upgraded)" is the actual constraint, not a stopgap.

Needed:

- confirm `mkdocs` + `mkdocs-material` are available (check if already
  installed in `.venv`, otherwise add as a dev dependency alongside `ruff` —
  follow whatever pattern this repo already uses for dev-only tools);
- decide the docs source layout: flat `docs/*.md` vs. nested by topic (e.g.
  `docs/guide/`, `docs/reference/`);
- add a minimal `mkdocs.yml` (site name, `docs_dir`, nav) and a starter
  `docs/index.md`;
- sketch the nav/table-of-contents sections before writing content — likely
  something like "Getting Started", "Pipeline Concepts" (Template/Strategy
  architecture, per the note at the top of this doc), "API Reference";
- once the repo goes public (or moves to a paid plan), add a GitHub Actions
  workflow to build and deploy to GitHub Pages (`mkdocs gh-deploy` or an
  action-based equivalent) — not needed yet.

### 21. FOH pipeline: exception-handling parity with Crane, trial-interval config migration

Started on `refactor/foh-pipeline`, prompted by a review request comparing
`foh_pipeline.py`'s exception handling against `crane_pipeline.py`'s. Ahead
of this doc's own "Crane first, FOH deferred" plan — noted as a deviation,
not a silent reprioritization.

**Root cause of the original asymmetry:** Crane's behaviour/physiology
modules only ever raise plain `ValueError`/`FileNotFoundError`, which
`pipeline.py`'s generic `except (ValueError, FileNotFoundError)` handlers
catch everywhere. FOH's `TPProcessingError` (`foh_target_behaviour.py`),
`ECGProcessingError` (`ecg.py`), and `EDAProcessingError` (`eda.py`) were all
bare `Exception` subclasses — invisible to those same handlers, so a raise
anywhere inside them could crash a whole participant run instead of being
caught and marked `ERROR`. **Fixed:** all three now subclass `ValueError`.

**Not FOH-specific, found along the way, still open:** `pandera.errors.SchemaError`/
`SchemaErrors` (raised by `RawBehaviourData.__post_init__`'s schema
validation on construction, `behaviour.py:34-38`) also aren't `ValueError`
subclasses — confirmed via `SchemaError.__mro__` / `SchemaErrors.__mro__` at
runtime. This affects Crane too, not just FOH, since `RawCraneBehaviourData`
goes through the same base-class validation. Not fixed anywhere yet; worth
folding into item 6 (Pandera dataframe contracts) or handling at the
`pipeline.py` template level.

**Silent-degradation import bugs, found and fixed:**
- `lsl.py`'s `FohLslPhysiologyDataImportStrategy.run()` returned an empty
  `RawBioData()` on missing streams instead of raising — briefly changed to
  `raise ValueError`, then reverted (see "still open" below) in favour of a
  "let it through" redesign that isn't finished yet.
- `foh_behaviour.py`'s `ImportFohBehaviourDataStrategyStep.run()` logged a
  warning on missing streams but then still indexed the missing key
  unconditionally, crashing via a bare `KeyError` (uncaught by `pipeline.py`).
  Fixed: now `raise ValueError` on the missing-stream path.

**`FohGetTrialIntervalStrategyStep` bugs, found and fixed:**
- It discarded `create_lsl_trial_intervals(...)`'s return value entirely and
  always returned an empty `TrialIntervals()`, regardless of input.
- `create_lsl_trial_intervals` was being called with the whole `RawBioData`/
  `RawFohBehaviourData` wrapper objects instead of the DataFrames inside
  them — `get_lsl_event_time`'s `xdf_df_in["time_stamps"]` access would
  `KeyError` on the wrapper immediately, for every subject, VR_markers
  present or not. Fixed by extracting `raw_biodata_in["VR_markers"]` /
  `raw_behaviour_data_in.raw_behav_df` at the call site.
- `get_lsl_event_time` (`trial_intervals.py`) re-raised its internal
  `KeyError` as `KeyError` instead of `ValueError`, which broke
  `get_lsl_event_time_with_fallback`'s own fallback logic and every
  `except ValueError` layer above it, including `pipeline.py`'s outer catch
  around the interval strategy. Fixed: now re-raises as `ValueError`.

**Update: fixed — `FohGetTrialIntervalStrategyStep.run()`
(`foh_trial_intervals.py:26-33`):** `trial_intervals` and
`interval_pipeline_status` (renamed from `interval_processing_status`, see
the naming TODO below) are now assigned default values (`TrialIntervals()`,
`PipelineStatus()`) *before* the `try` block, so the final `return` always has
something bound regardless of which branch ran — the `UnboundLocalError` trap
is gone. The local `try/except` itself was kept rather than removed in favour
of `pipeline.py`'s outer handler, since it still needs to populate those
defaults.

**Update: fixed — `lsl.py`'s `FohLslPhysiologyDataImportStrategy.run()`:**
now only treats `OpenSignals` as required (`has_missing_requirements(missing_streams,
["OpenSignals"])`, bailing out with `RawBioData()` if it's missing), and
returns `RawBioData(raw_data=selected_lsl_physiology_streams_dfs)` — the dict
`gather_xdf_data_streams` already builds from whatever streams were actually
found — instead of indexing `"VR_markers"` by a fixed key. A missing
`VR_markers` no longer crashes and no longer wipes out an otherwise-good
`OpenSignals` result; it just isn't in the returned dict, which the
downstream fallback logic is already built to handle.

**Finding: `VR_markers` is not actually required by the interval-building
logic.** Per the trial-interval config (now `foh_config.py`, see below),
`VR_markers` is only ever the *primary* source for `baseline`'s start event,
and that already has a working fallback to `VR_trial_events`. `stress` and
`recovery` never reference `VR_markers` at all. But `mobi_FOH_process_batch.py`'s
`has_foh_markers` pre-filter and the deprecated `run_lsl_pipeline`'s
`has_missing_requirements(missing_streams, ["VR_markers", "VR_trial_events"])`
both gate on the *stream's existence*, not on whether any interval actually
needs it — so the fallback never gets a chance to run, and files lacking
`VR_markers` are silently skipped (`logger.info`, not a warning or error) well
before either the CLI or the batch summary would say anything looked wrong.
This is the likely explanation for "the data processed successfully" while
most files actually lack `VR_markers`: the ones that don't have it are
dropped silently, not processed with degraded data.

**Trial-interval config migrated out of `pyproject.toml`:** the
`[tool.mooi_toolbox.trial_intervals.*]` TOML section and `cfg.get_trial_intervals()`
(`config.py`) were untyped, string-keyed, and only ever consumed by FOH
(Crane has always had its own separate, hardcoded interval logic in
`crane_trial_intervals.py`). Replaced with typed constants: `LslEventSpecification`
/ `LslIntervalSpecifications` dataclasses in `lsl.py`, concrete
`BASELINE_INTERVAL` / `STRESS_INTERVAL` / `RECOVERY_INTERVAL` /
`FOH_TRIAL_INTERVALS` in new `processing/foh_config.py`. `trial_intervals.py`'s
`get_lsl_event_time_from_spec` / `get_lsl_event_time_with_fallback` updated
from dict access to attribute access to match. `LslEventSpecification.stream`
is typed `Literal["VR_markers", "VR_trial_events"]` rather than plain `str`,
specifically so a typo'd stream name is a type-checker error instead of a
runtime `KeyError`.

This deliberately breaks the deprecated `trial_intervals.create_lsl_trial_intervals`
(`@deprecated`, still called by `run_lsl_pipeline`, still wired into both
`mobi_FOH_process.py` and `mobi_FOH_process_batch.py`) — accepted as
intentional rather than routed around, on the basis that the deprecated path
is being kept "just in case" until `run_pipeline` checks out, then deleted
outright rather than kept in sync. `pyproject.toml`'s TOML section is now
dead weight for the new path but still read by the (now-broken) deprecated
one — cleanup candidate for the same pass that deletes `run_lsl_pipeline`.

**Near-misses caught during the migration, worth remembering as a pattern:**
transcribing the TOML into `foh_config.py` by hand initially dropped
`baseline_start_fallback`'s `offset_seconds=-300`, which would have made the
fallback path silently compute a zero-length baseline interval (identical to
`baseline_end`'s spec) with no exception anywhere — caught in review before
landing, not by any test. A typo'd stream name (`"VR_tiral_events"`) in the
same file was the concrete motivation for the `Literal` type above. Neither
would have been caught by the type system as it existed before this pass.

**Other gaps noted, not yet fixed:**
- `foh_pipeline.py`'s `import_behav_steps` still doesn't include
  `ImportFohTargetBehaviourDataStrategyStep` — FOH target behaviour data is
  never actually imported into the new pipeline yet.
- `ProcessFohTargetDataWithIntervalsStrategyStep.run()` (`foh_target_behaviour.py`)
  computes `target_df_out` via `run_processing(...)` and discards it, returning
  an empty `PipelineOutputData` (`# TODO: Create PipelineOutput!` in the code
  itself). Even once the item above is wired in, no target data reaches the
  output until this is filled in.
- `foh_pipeline.py`'s `build_foh_participant_output_schema()` returns a bare
  `pa.DataFrameSchema()` — validation is currently a no-op, unlike Crane's
  fully-built schema (`crane_pipeline.py:65-92`).
- The subjective stress measure (self-report, collected alongside the FOH
  physiology/target data) still isn't imported or merged into a subject's
  output row — flagged with a `# TODO` in `mobi_FOH_process_batch.py` where
  `participant_data_out` is assembled. No import strategy step or schema for
  it exists yet; needs the same treatment as target behaviour data above
  (an `ImportFohSubjectiveStressStrategyStep`-shaped step, wired into
  `import_behav_steps`).
- TODO: `PipelineStatus` vs. `ProcessingStatus` (`processing_status.py`) read
  as confusingly similar names for two different things — `PipelineStatus` is
  the per-pipeline-run container (`dict[type, ProcessingStatus]`),
  `ProcessingStatus` is the per-entry enum (`OK`/`ERROR`/...) it holds. Same
  confusion shows up in local variable names built off them, e.g.
  `interval_pipeline_status` (renamed from `interval_processing_status` while
  fixing the `UnboundLocalError` trap above). Worth a naming pass later —
  e.g. renaming the enum to something like `ProcessingOutcome` — across the
  class names and every variable named after them. Not urgent, just flagged.

**Test added:** `tests/test_foh_pipeline.py::test_foh_target_behav_strategy`
now exercises the real import → interval → process chain (mirroring
`test_crane_pipeline.py`'s `test_crane_process_behaviour` shape), replacing
the previous `@unittest.skip` stub. Its final assertion is weak (only
`assertIsInstance(target_output, PipelineOutputData)`) given the
`ProcessFohTargetDataWithIntervalsStrategyStep` stub above — it can't yet
catch a regression in the actual target-processing output, only that the
step doesn't crash.

**Update (target behaviour wired in, batch CLI migrated):** several of the
items below are now done.

- `foh_pipeline.py`'s `import_behav_steps` now includes both
  `ImportFohBehaviourDataStrategyStep` and
  `ImportFohTargetBehaviourDataStrategyStep` — target behaviour data is
  imported into the pipeline, not just interval-matched.
- `ProcessFohTargetDataWithIntervalsStrategyStep.run()`'s
  `# TODO: Create PipelineOutput!` is filled in: it now returns a real
  `FohTargetBehaviourOutputData` (a `PipelineOutputData` subclass, new in
  `foh_target_behaviour.py`) built via `append_dataframe(...)` against a real
  schema — `build_foh_target_behaviour_pipeline_output_schema()`, columns
  named `{trial_type}_{trial_number}_{target_type}_Target` from three new
  constants in `foh_config.py` (`TARGET_TYPES`, `TRIAL_TYPES`,
  `TRIAL_NUMBERS`). A companion schema,
  `build_foh_raw_target_behaviour_file_schema()`, now also validates the raw
  target CSV/XDF shape on `FohRawTargetBehaviourData` construction, the same
  "validate at the boundary" pattern Crane uses (item 6).
- `lsl.py`'s `FohLslPhysiologyDataImportStrategy.run()` now only *requires*
  the `OpenSignals` stream (`has_missing_requirements(missing_streams,
  ["OpenSignals"])`) and returns `RawBioData(raw_data={"EDA": ..., "ECG":
  ...})` — `OpenSignals` is split into separate `EDA`/`ECG` dataframes (each
  with the other's column dropped) instead of being handed back as one
  combined `OpenSignals` entry. `VR_markers` is included only when present,
  no longer required.
- `foh_trial_intervals.py`: the interval-building function was renamed
  `create_lsl_trial_intervals` → `create_foh_lsl_trial_intervals` (the old
  name is still `@deprecated` on `trial_intervals.py`'s copy, used only by
  `run_lsl_pipeline`); `FohGetTrialIntervalStrategyStep.run()`'s `except`
  clause widened from `ValueError` to `(KeyError, ValueError)`, since a
  missing `"VR_markers"` key on `raw_biodata_in` (now genuinely optional, per
  the `lsl.py` change above) raises `KeyError` rather than `ValueError`.
- `mobi_FOH_process_batch.py` (the batch CLI) migrated from the deprecated
  `run_lsl_pipeline` to `run_pipeline`/`PipelineTemplate`: `input_folder`/
  `output_folder` are now typed `Path` at the click layer
  (`click.Path(..., path_type=Path)`) instead of converted by hand inside
  `main()`; and where the old path returned a single optional `Figure`, the
  new `PipelineOutputData.figure_data_out` is a `dict[str, Figure]` (e.g.
  `"eda_qc"`, `"Interval_qc"`), so the batch CLI now loops over and saves
  every figure the pipeline produced, closing each with `plt.close(fig)`
  after saving to avoid the figure-leak issue tracked in item 18.
  **`mobi_FOH_process.py` (the single-file CLI) has not been migrated** —
  it still imports `run_lsl_pipeline as run_foh_pipeline` and calls the
  deprecated path directly, so the two FOH CLIs currently run through two
  different pipelines. Worth migrating together with the batch CLI rather
  than leaving this split in place.
- `tests/test_foh_pipeline.py::test_basic_pipeline` renamed to
  `test_basic_foh_pipeline` and strengthened: beyond the previous
  `assertTrue(pipeline_data_out)`, it now asserts both QC figures are
  present (`figure_data_out["eda_qc"]`, `figure_data_out["Interval_qc"]`) and
  that `RawBioData`, `RawFohBehaviourData`, `FohRawTargetBehaviourData`, and
  `TrialIntervals` all come back `ProcessingStatus.OK` for the known-good
  fixture participant.

Needed, roughly in dependency order:
- ~~fix the `UnboundLocalError` trap in `FohGetTrialIntervalStrategyStep.run()`~~ — done, see update above;
- ~~finish the "let it through" fix in `lsl.py`~~ — done, see update above;
- ~~wire `ImportFohTargetBehaviourDataStrategyStep` into `foh_pipeline.py`~~ — done, see update above;
- ~~fill in `ProcessFohTargetDataWithIntervalsStrategyStep`'s TODO~~ — done, see update above;
- **Pinned, not decided yet:** whether to relax `mobi_FOH_process_batch.py`'s
  `has_foh_markers` gate (`mobi_FOH_process_batch.py:50-62`) — it still
  requires `FOH_target`, `VR_trial_events`, *and* `VR_markers` all present
  before attempting a file, so files missing only `VR_markers` are still
  silently skipped at the batch level, before the `lsl.py` fix or the interval
  fallback ever get a chance to run on them. Deliberately left open for now —
  moot once the deprecated path and its CLIs are deleted, live until then;
- build out `build_foh_participant_output_schema()`, mirroring how Crane's
  schema is built from constants (item 3 territory) — still a bare
  `pa.DataFrameSchema()` no-op, the one piece of the original punch list not
  yet done;
- once `run_pipeline` is validated end-to-end for FOH: delete
  `run_lsl_pipeline`, migrate `mobi_FOH_process.py` onto `run_pipeline` the
  same way the batch CLI now is, and remove the now-stale `pyproject.toml`
  trial-interval TOML section and `cfg.get_trial_intervals()` in the same
  pass;
- decide the fate of the `pandera.errors.SchemaError`/`SchemaErrors` gap —
  affects Crane as much as FOH, likely belongs with item 6.

### 22. Direction: import assumptions should move toward BIDS — one dataset per timepoint, per input folder

Not yet started — a direction for where the import layer (item 4/12/13's
`ParticipantConfig.from_physiology_data` and `from_lsl_data`) should head
next, rather than open work with a concrete task list yet.

Today, file discovery for a given participant searches for files by
name/glob pattern under a single shared `data_folder_in`, across however
many timepoints that folder happens to contain — the "which timepoint is
this?" question is answered indirectly, by whatever the filename or date
string happens to encode (see items 4, 12, 13). The intended direction is
closer to the [BIDS](https://bids.neuroimaging.io/) convention: **one
dataset per timepoint, in its own timepoint input folder** — so "which
timepoint" is answered by *which folder a file was found in*, not by
parsing it back out of a filename. Concretely, this points toward:

- an import entry point that takes a single timepoint's folder, rather than
  a folder spanning multiple timepoints/sessions;
- participant/session identification driven primarily by folder structure,
  with filename matching (today's `filename_glob` pattern) as a
  within-folder detail rather than the only signal;
- less reliance on filename-embedded dates for cross-checking, since the
  folder itself would already scope the timepoint — directly relevant to
  item 13's date-string bug and item 4's "don't assume filename conventions
  hold" finding, both of which exist only because timepoint currently has to
  be inferred from filenames.

This doesn't replace items 4/12/13 — those are about making today's
filename-based matching correct and honest about failures. This item is
about the layer above that: given the recurring pain from filename-based
timepoint inference, moving the *unit of import* to "one timepoint folder"
is the direction to head in, so filename matching only ever has to
disambiguate *within* a timepoint, not across them.

**Update:** the BIDS crosscheck GUI (`gui/crane_bids_crosscheck_gui.py`,
`gui/bids_crosscheck_common.py`) now exists and, as of this session, has a
crane-specific `CraneCandidateExtras` (physiology channel presence, behaviour/
debrief column checks) at parity with FOH's — see `docs/bids_crosscheck_plan.md`.
That tool only ever reads/writes an *already-BIDS-organized* folder; it does
not produce one. There is still no raw→BIDS converter for crane at all (see
`docs/bids_converter_plan.md` — "not yet started"), so this item's actual
direction remains undone at the import-layer end.

**TODO, once a real crane BIDS folder exists and has been validated against
the crosscheck tool:** come back to this item's target — `ParticipantConfig.
from_physiology_data` (`input_data.py`) and `FindCraneParticipantFilesStrategyStep`
(`crane_pipeline.py`) — and identify every place that currently assumes the
flat, filename-encoded-date raw layout (the `filename_glob` patterns on
`RawBehaviourData`/`RawCraneBehaviourData`/`RawDebriefBehaviourData`, the
date-string extraction items 12/13 flag as buggy, `vrlab_crane_process.py`'s
own subject-file globbing) and point out exactly which of those need to
change to read from a `sub-XXX/` BIDS folder instead of a shared flat
`data_folder_in`. Not started — deliberately deferred until the BIDS folder
side (converter + crosscheck) is settled, so this isn't designed twice.

### 23. Manually test the crane raw-filename correction dialog

Not yet run by a human. `crane_convert_to_bids.py` (corrections JSON, `resolve_crane_filename`,
`discover_raw_files_for_review`, `explain_unparseable_filename`, and the `_SUBJECT_ID_PATTERN`/
`_DUPLICATE_COPY_MARKER_PATTERN` split that stopped silently stripping a trailing `" (N)"`
marker — that used to assume it was always a harmless Windows duplicate-copy artifact of the
same file, which in practice merged two genuinely different subjects that happened to share a
base id; now any `(N)`-suffixed filename is unparseable and needs an explicit human decision),
`bids_crosscheck_common.py` (`extra_raw_action` generalized to `extra_raw_actions`, a list), and
`crane_bids_crosscheck_gui.py` (`RawFilenameCorrectionDialog`, "Fix raw filenames..." button —
lists *every* raw physiology/behaviour file with its currently-resolved id, not only ones that
fail to parse, since a `(N)`-marked file resolves to nothing until corrected either way) were all
written and read back for consistency, but never actually launched. Also added: a
`convert_crane_to_bids` warning when a saved debrief-id correction's target doesn't match any
known subject id at all (previously silent — see the "debrief re-attachment" bug this was meant
to surface); and `debrief_correction_key`/`apply_debrief_id_corrections`, so
`DebriefRecordIdCorrectionDialog` and the converter key a correction by *row* (record_id +
occurrence index), not just by record_id value — two rows that share the exact same literal
record_id (the debrief-side counterpart of a `(N)`-marked filename pair) previously could never
both be corrected: fixing one silently resolved *both* via `Series.replace`, so the second
vanished from the dialog with no way to address it. Confirmed against real data as fixing that
exact symptom, but the dialog's new occurrence-aware row listing hasn't been separately
walked through step by step.

Needed — launch the GUI (`python -m vrlab_toolbox.gui.crane_bids_crosscheck_gui`, or however this
is normally invoked) against a raw folder containing a deliberately mis-named file and a pair of
`(1)`/`(2)`-suffixed files, and check:

- both "Raw folder" and "BIDS folder" need to be selected before "Fix raw filenames..." (and
  "Fix debrief record IDs...") enable at all;
- the dialog lists every raw physiology/behaviour file, not just mis-named ones — each row shows
  its correct relative-to-raw-folder path and its "Currently resolves to" value;
- a `(1)`/`(2)`-suffixed pair both show "(unparseable)" in the "Currently resolves to" column
  (in the CROSS/red color), not a silently-collapsed shared id;
- selecting a row updates the "Details" bottom pane with either a plain-English parse-failure
  reason or, for a file that resolves fine, the id it resolves to;
- before ever clicking "Refresh BIDS" in this session, the bottom pane's log-excerpt line reads
  the "no matching line yet" placeholder rather than erroring;
- after clicking "Refresh BIDS" once, reselecting the same row shows the matching captured log
  line instead;
- typing a subject id and clicking Save writes `raw_filename_id_corrections.json` into the BIDS
  folder, keyed by the file's relative path — for *any* row, not only unparseable ones;
- leaving the box blank and saving does *not* add an entry (or removes one if it existed);
- after saving a real correction and clicking "Refresh BIDS" again, the file is copied into the
  corrected subject's `sub-XXX/ses-01/beh/` folder; `acq_time` in `scans.tsv` is `"nodate"` for a
  filename that never matched `_SUBJECT_ID_PATTERN` at all, but the *real* date prefix for a
  `(N)`-marked filename that matched fine and was only rejected for the marker
  (`resolve_crane_filename` still recovers it even though the subject id itself is overridden);
- reopening the dialog afterward still lists that file (the list is no longer filtered down as
  entries resolve), now showing the corrected id under "Currently resolves to";
- two unparseable files that happen to share a bare filename in different raw subfolders can be
  corrected independently, without one overwriting the other's entry;
- saving a debrief-id correction whose target id matches no known subject at all (typo, or a
  dash/case mismatch against the literal `sub-XXX` folder name) produces the new "doesn't match
  any known subject folder" warning in the "Refresh BIDS" status panel, instead of silently
  doing nothing;
- two debrief rows sharing the exact same literal `record_id` both show up in "Fix debrief
  record IDs...", labelled "(1 of 2)"/"(2 of 2)", neither pre-filled with a guess; correcting
  one leaves the other listed (not silently resolved) until it's corrected too;
- after correcting both occurrences and clicking "Refresh BIDS", each ends up in its own
  corrected subject's debrief file, not merged into one;
- the "Fix debrief record IDs..." dialog otherwise still works for the ordinary
  one-row-per-record_id case — regression check on the `extra_raw_action` →
  `extra_raw_actions` list generalization and the row-vs-value-keyed correction change;
- the FOH crosscheck GUI (`gui/foh_bids_crosscheck_gui.py`, which passes no `extra_raw_actions`
  at all) still launches and behaves normally — same shared-code regression concern, FOH side.

### 24. Manually test the FOH raw-folder import feature

Not yet run by a human. `cli/foh_import_to_bids.py` (`import_foh_raw_to_bids`,
`FohImportSummary`), `processing/bids_crosscheck.py` (`existing_subject_ids`, moved out of
`crane_convert_to_bids.py` so both importers share it; `iter_subject_folders`, de-privatized
for the same reason), and `gui/foh_bids_crosscheck_gui.py` (`_run_foh_import` wired in as the
`raw_converter`) were all written, unit-tested (`import_foh_raw_to_bids` against a folder
shaped like a real `sub-XXX/ses-.../eeg/` layout, `_old1`-style duplicates included), and the
full `tests/test_bids_crosscheck.py` suite still passes — but the GUI itself has never been
launched.

Needed — launch `vrlab_foh_bids_crosscheck` and check:

- a **Raw folder** row and **Refresh BIDS** button now appear above the existing **BIDS
  folder** row, same as crane's;
- pointing Raw folder at a copy of a real FOH raw folder and clicking **Refresh BIDS** copies
  every subject across, `_old1`/`_old2`/... duplicates included, and the crosscheck view
  handles them as ordinary duplicates exactly as before;
- hovering **Refresh BIDS** shows the generic tooltip with no mention of debrief anything
  (that clause is crane-only now — see `convert_button_tooltip`);
- the raw folder is untouched afterward (file count/timestamps unchanged);
- resolving a duplicate for one subject (pick, commit, mark crosschecked), then clicking
  **Refresh BIDS** again, leaves that subject completely alone — decision not clobbered, "Last
  conversion" reports it as already-present rather than re-copied;
- adding one more subject to the raw copy and clicking **Refresh BIDS** again adds only that
  subject;
- `foh_import_to_bids <raw_folder> <bids_folder>` works standalone from a terminal too;
- crane's own crosscheck GUI still behaves normally afterward (regression check on the shared
  `bids_crosscheck_common.py`/`existing_subject_ids` changes both features now depend on) —
  can likely be folded into the same pass as item 23's crane regression checks rather than
  repeated separately.

Do not rewrite everything at once. Preserve working behaviour and improve
one structural issue at a time: function-based strategy contracts first,
dataframe contracts alongside them, shared template architecture second.

Folders and files are always `pathlib.Path`, never bare strings — see
[Golden Rules](golden-rules.md#always-use-path-never-strings-for-files-and-folders)
for the rule and why it matters. This applies to new code the same way it
applies to item 22's BIDS direction above: a timepoint input folder should
be handled as a `Path` end to end, not a string that gets converted back and
forth.

### 26. Dead/stale tracked files — candidates for removal

Found during a REVIEW-style audit of `git ls-files` against actual imports/callers across
`src/`, `tests/`, `docs/`, and `pyproject.toml` (2026-08-27). Each entry was independently
verified (grep for every plausible import form, or a direct file-existence check), not taken
on a prior doc's word alone — a couple of these findings are, in fact, *because* an earlier
part of this same doc turned out to be stale (see the `run_lsl_pipeline` entry below).

**High confidence — no callers/references found anywhere in the tree:**

**Done 2026-09-11:** the `__pycache__` cache files, `crane_behav_qc.py`, `opensignals.py`,
`window_layout copy.json`, both `Automate/x.txt` stubs, `eeg.py`'s `run_spiral_eeg_processing`
wrapper, and `crane_trial_intervals.py`'s two `@deprecated` functions
(`align_crane_behav_intervals_with_trigger_intervals`, `get_crane_predicted_trigger_intervals`,
along with their now-orphaned `references/matched_debug_df_testa.parquet` fixture) have all
been deleted, re-verified zero-callers at deletion time — re-confirming item 9's own
"once the new path is confirmed stable" caveat on the two `crane_trial_intervals.py` functions
is worth a second look if any drift/matching issue turns up later, since that stability
re-verification wasn't repeated here beyond the zero-callers check.

- `foh_pipeline.py`'s `run_lsl_pipeline` and `trial_intervals.py`'s `create_lsl_trial_intervals`
  (both `@deprecated`) — zero real callers anywhere in `src/`. **This means several passages
  earlier in this doc (items 21/24's "Needed" list, e.g. "still wired into ... `mobi_FOH_process.py`")
  are themselves stale**: `mobi_FOH_process.py` (the single-file CLI these passages describe as
  the last caller of the deprecated path) was a real file, deleted 2026-08-14 in "WIP: foh batch
  and crosschecking..." — confirmed via `git log --diff-filter=D`, not an accidental loss. That
  confirms this is a real cleanup opportunity, still open: the deprecated
  `run_lsl_pipeline`/`create_lsl_trial_intervals` chain and this doc's own now-inaccurate
  references to `mobi_FOH_process.py` can be cleaned up together whenever someone gets to it.
- ~~`pyproject.toml`'s `[project.scripts]` — two entries point at files that no longer exist in
  the tree~~ **Fixed 2026-08-31**: the `vrlab_foh_process` (→ `mobi_FOH_process.py`, deleted
  2026-08-14) and `vrlab_crane_summary_data` (→ `vrlab_crane_qc.py`, deleted 2026-07-22) entries
  were removed from `pyproject.toml` -- confirmed with the user that no rebuild of either script
  was intended right now, rather than the registration being an oversight. If a generic
  single-file FOH processor or a crane summary-stats command gets built later, re-add the entry
  then, matching an actual file.

**Medium confidence — worth a human check before acting:**

- `src/vrlab_toolbox/window_manager/Automate/TestController.py`, `automation_layer.py`,
  `session_controller.py`, `signal_checker.py` (the top-level `Automate/` folder, not the
  `Automate/Graphomotor/` subfolder) — no tracked launcher script invokes any of these, unlike
  `Automate/Graphomotor/graphomotor_gui.py` (launched by the tracked `Start_Graphomotor.bat`).
  `signal_checker.py` is byte-for-byte identical to the copy already in `Automate/Graphomotor/`,
  and `automation_layer.py` shares most function names with that folder's version — reads as an
  earlier generation of the same automation tooling, superseded by `Graphomotor/`. Needs lab
  context to confirm nothing outside this repo still launches it directly.
- `src/vrlab_toolbox/cli/pull_redcap.py` — no `main()` (runs top-level code on import), a
  hardcoded empty `API_TOKEN = ""`, not registered in `pyproject.toml`, not mentioned in
  `README.md`/`docs/`. Reads as an unfinished/abandoned one-off script.
- `src/vrlab_toolbox/cli/mobi_spiral_process_batch.py` — has a real, working `click`-based
  `main()` and imports live pipeline code (`spiral.py`), but unlike every other `cli/*.py` file
  with a `main()`, it isn't registered in `pyproject.toml`'s `[project.scripts]`. Could be
  intentional WIP rather than dead — confirm with whoever's been working on the Spiral pipeline.
- `for_mooi_xdf_processing.ipynb` (repo root) — an ad hoc exploratory notebook with a hardcoded
  absolute local path and imports (`dash`/`plotly`) not listed in `requirements.txt`/
  `requirements-dev.txt`. Not referenced by `README.md`, `docs/`, or any script.

**Also noted, not a file issue:** `tests/test_long_walk_pipeline.py` is currently empty (no
content at all) — `docs/testing.md` lists it alongside `test_crane_pipeline.py`/`test_bids.py`
as an example of "one file roughly per module under test," which overstates what it actually
has. Either fill it in or flag it explicitly as an intentional stub.

### 27. Cross-platform build: Mac (then Linux), CLI-first distribution

Not started — packaging/distribution, not pipeline architecture, but tracked here as the
project's running punch list. Discussed 2026-08-28, prompted by "would a Mac build be brain
surgery or mechanical, like FSL does it?"

**Current state:** `specs/*.spec` (PyInstaller) are already OS-agnostic — paths are built from
`SPECPATH`/`REPO_ROOT`, not hardcoded Windows paths, and no `.ico`/Windows-only assets are
referenced. 9 of 11 tools are `console=True` (plain CLI); only the two BIDS crosscheck GUIs and
`vrlab_toolbox_launcher` (`gui/toolbox_launcher.py`) are `console=False` (windowed, launched by
double-clicking a Desktop shortcut). `build_mac.sh` exists only as a stub — two tools,
`--onefile`, no `.parquet`/version-metadata bundling (see [packaging.md](packaging.md#L104-L110),
which already flags this as a known gap). Windows packaging (`build.ps1`,
`toolbox_installer.iss`) uses Inno Setup — Windows-only, no equivalent on Mac/Linux — to build a
desktop-shortcut installer that edits `HKEY_CURRENT_USER\Environment` for `PATH`.

**Direction agreed:** drop the double-click launcher model in favor of FSL's — every tool,
GUI included, is just a command typed in a terminal, with the toolbox's `bin`-equivalent folder
added to `PATH` once (shell profile edit, not registry). This removes the need for an Inno-Setup
equivalent, an `.app`/Dock icon, and (for a CLI-first release) likely the Apple Developer
account/notarization pipeline that a double-click-distributed `.app` would need to avoid
Gatekeeper friction.

Needed:

- extend `build_mac.sh` to loop over all `specs/*.spec`, same as `build.ps1` does, instead of the
  two hardcoded `--onefile` tools;
- decide the Mac/Linux PATH-setup step (shell rc edit via install script, vs. just documenting
  "add this folder to PATH");
- decide whether `vrlab_toolbox_launcher` / the two crosscheck GUIs still ship at all in a
  CLI-first model, or become plain terminal-launched commands like the other 9 tools;
- add a `macos-latest` (then `ubuntu-latest`) job to `.github/workflows/release.yml`, alongside
  the existing Windows-only one;
- Mac first, Linux second — Linux adds its own wrinkle Mac doesn't (no single standard installer
  format; PySide6-on-Linux frozen builds have known Qt platform-plugin (`xcb`/Wayland) issues) —
  better to isolate that from the "new install flow" work by doing Mac's simpler case first.

## Deferred: FOH & LongWalk

Picked up once Crane's contract, tests, and cleanup above are settled —
noted here so they aren't lost, not expanded on for now.

- Align FOH and Crane to the same broad pipeline sequence (load → normalize
  → validate → intervals → physiology → behaviour → combine → QC → output),
  once Crane's shape is stable.
- `processing/trial_intervals.py:87` — should not be hardset to the
  platform.
- `processing/foh_target_behaviour.py:13,14,41,58` — logging what's dropped,
  a better header check, a possible bug, and dead code to remove.
- `processing/long_walk_pipeline.py:51` — messy pipeline, same cleanup Crane
  needs.
- **Widen `GetTrialIntervalsFallbackStartegy` to cover "behaviour data
  structurally absent," not just "present but failed."** Long walk has no
  behavioural data at all — its intervals come purely from the Biopac
  Trigger channel (`get_raw_biopac_trigger_intervals`), so `raw_behav_data_for_intervals`
  would always be `None` under `PipelineTemplate`. The outer guard at
  `pipeline.py:406` (`if raw_biodata_for_intervals is not None and
  raw_behav_data_for_intervals is not None:`) only reaches `fallback_strategy`
  from inside the `except` block when `get_interval_strategy.run()` raises —
  never when behaviour data was never attempted in the first place — so
  today a physiology-only pipeline can't reach the fallback path at all.
  Relates to items 5 and 17 above (same guard, same `fallback_strategy`
  mechanism), but is a distinct case: those are about Crane's behaviour data
  being present-but-degraded; this is about a pipeline that structurally
  never has behaviour data. If widened (fallback triggers whenever
  `raw_behav_data_for_intervals is None`, not only on exception), long walk
  could adopt `PipelineTemplate` with an interval strategy whose
  `fallback_strategy` wraps `get_raw_biopac_trigger_intervals` +
  `EXPECTED_INTERVAL_NR` checking, and reuse `ProcessEdaPhysiologyDataStrategyStep`
  (`eda.py:77-92`) as-is instead of calling `run_eda_intervals` directly —
  which would also pick up `correct_order()`, currently missing from long
  walk's own EDA output. Backward compatible: `fallback_strategy` defaults to
  `None`, so Crane/FOH are unaffected unless they opt in. Worth noting to
  whoever owns `pipeline.py` that "fallback" would stretch to mean "the
  primary path" for a physiology-only pipeline, not just a backup — a
  naming/semantics wrinkle, not a functional risk. `mobi_core_pipeline.py`
  is currently just a stub (EEG/EDA-ECG comment list, no code) but reads as
  another physiology-only candidate for this same fix once it's built.
- `processing/input_data.py:3` — dataclass could look for variables and
  generate errors.
- ~~`cli/vrlab_crane_qc.py:19` — add summary data processing.~~ **Dropped 2026-08-31:**
  `vrlab_crane_qc.py` was deleted 2026-07-22 ("Trying to revamp intervals...") and never
  restored; the matching `pyproject.toml` `vrlab_crane_summary_data` entry (item 26, above) has
  now been removed too rather than backfilled. Re-add both together if crane summary-stats
  processing gets built later.
- `cli/check_mobi_xdf.py:24` — show missing streams.
- `cli/vrlab_crane_process.py:109` — data labels for SPSS output.
  (The str-to-path handling previously tracked here is resolved:
  `biopac.get_subject_id_from_mat` now takes a `Path` directly, and the CLI
  passes `output_folder` through to `run_crane_pipeline` instead of a bare
  `input_folder`.)
- `processing/ecg.py:15,26` — NeuroKit warnings to address on update; combine
  outputs (maybe a dict).

### 28. Rename `mobi_mooi_toolbox`/`mooi_toolbox` to `vrlab_toolbox`, retire "mobi"/"mooi" branding

**Progress, 2026-09-15:** buckets 1-2 (package rename, `pyproject.toml`) landed first; buckets
4-5 (docs sweep, packaging/installer/CI) landed in this pass, including deciding the retired
"Mobi"/"Mooi" display name → **VRLab Toolbox** (`mkdocs.yml`'s `site_name`,
`toolbox_installer.iss`'s app name/install folder/output filename, and matching README/docs
mentions). Buckets 3 (legacy "mobi" filenames), 6 (`AGENTS.md`'s own path references), and 7
(GitHub repo/local clone-folder rename, tracked separately as item 29) are still outstanding —
`mobi_mooi_toolbox` mentions throughout this file and `README.md` intentionally still match the
real, not-yet-renamed repo name until item 29 lands.

Originally scoped 2026-09-10 (`git grep -ci` put it at 445 matches across 86 files at the time).
The CLI-facing surface is already `vrlab_*`-branded (every `[project.scripts]` entry in
`pyproject.toml`).

**What's actually in scope, in dependency order:**

1. **Package rename** — `src/mooi_toolbox/` → `src/vrlab_toolbox/`, plus every
   `from mooi_toolbox...`/`import mooi_toolbox` across roughly 50 `.py` files. Mechanical (IDE
   rename-package or scripted find/replace), but breaks the package until every import is
   fixed — do this first, in one commit, verified green (full test suite) before anything else
   depends on it.
2. **`pyproject.toml`** — `name = "mooi-toolbox"` → `vrlab-toolbox`; all 15
   `[project.scripts]` right-hand sides (`mooi_toolbox.cli....` → `vrlab_toolbox.cli....`);
   the `[tool.mooi_toolbox]` config table, including `[tool.mooi_toolbox.trial_intervals.*]`
   (already dead weight pending `run_lsl_pipeline`'s deletion, per item 21) → `[tool.vrlab_toolbox]`.
   **Open question:** does anyone have a local config relying on the old table name? Confirm
   before renaming it out from under them.
3. **Legacy "mobi" filenames** — `read_mobi_xdf/`, `check_mobi_xdf.py`,
   `mobi_FOH_process_batch.py`, `mobi_FOH_assess_data.py`, `mobi_spiral_process_batch.py`.
   **Not a find/replace.** Per discussion: "mobi" originally named the specific mobilab
   station (the spiral task included), and the code under these files has since generalized to
   work over LSL with any biosignal platform — keeping "mobi" in the names now actively
   misdescribes what they do. Rename to something LSL-generic (e.g. `lsl_xdf`,
   `foh_batch_process`) rather than swapping in `vrlab`.
4. **Docs sweep** — heaviest by volume (this file, `lab-streaming.md`, `packaging.md`,
   `README.md`, `mkdocs.yml`), lowest risk — nothing breaks, just needs updating once 1-3 land
   so docs describe real paths instead of stale ones.
5. **Packaging/installer/CI** — `build.ps1`, `build_mac.sh`, `toolbox_installer.iss`,
   `specs/toolbox.spec`, `.github/workflows/release.yml` — installer display name, output
   filenames, any icon/registry strings.
6. **`AGENTS.md` itself** — its BYPASS/OVERRIDE file-scope rules reference
   `src/mooi_toolbox/processing/` by path; needs updating in lockstep with step 1 or the
   governance doc's own scoping goes stale.
7. **Outside the repo** — the GitHub repo name and local clone folder
   (`mobi_mooi_toolbox`) — separate from the above, and breaks the remote URL for any other
   existing clone until `git remote set-url` is run there too. See item 29 for how this
   interacts with the public-repo move.

**Open forks, not yet decided:**
- Rename the `mobi_*` files now, or park until final names are settled (the toolbox "has
  grown beyond" the mobilab station, per discussion)?
- Anyone with a local `[tool.mooi_toolbox]` config override that'd silently stop being read?
- Bundle the repo/folder rename with this pass, or sequence it separately (item 29)?

**Branch/merge workflow, decided 2026-09-10:** do this on a branch (`rename/vrlab-toolbox`
or similar), one commit per bucket above, full test suite run after each commit, merged to
`master` once fully green — standard pattern for a mechanical change like this.

**Real wrinkle:** as of this planning session, five other branches exist locally
(`feature/mobi-foh-assess-data-cli`, `refactor/error-output`, `refactor/foh-pipeline`,
`refactor/pipeline`, `refactor/trigger-alignment`), plus two more remote-only
(`foh-marker-validation`, `graphomotor-pipeline-refactor`). The package-rename commit touches
import lines across roughly 50 files, so merging any of those branches back onto `master`
*after* the rename lands means re-pointing every `from mooi_toolbox...` line they touched by
hand — git's rename detection helps but won't fully absorb it. Land the rename branch either
once those branches are merged, or with the expectation of going back to rebase each one
afterward — not mid-flight on several at once.

**Scope note for execution:** the package-rename commit touches every file under
`src/mooi_toolbox/processing/`, which AGENTS.md's BYPASS/OVERRIDE rules put on the "Verboten
without OVERRIDE" list — even though it's mechanical (import paths only, no logic changes),
that commit needs `OVERRIDE:` invoked explicitly when the work actually happens, per the
loop's own scope rules.

### 29. Move the repo from private to public

Not started — decided 2026-09-10, following on from item 28. A GitHub fork was considered and
ruled out: forking is for giving someone else their own linked copy, and for the same-owner
case here it buys nothing over renaming directly, while still carrying the full commit
history along (item 26's dead-code history included either way).

**Step 2's history audit — done, 2026-09-15:**
- `cli/pull_redcap.py` — checked `API_TOKEN` across every historical revision of the file:
  always `""`. No real token was ever committed.
- `toolbox_installer.iss` / `build.ps1` — checked full history for signing-cert/`.pfx`/password
  references: none found.
- `for_mooi_xdf_processing.ipynb` — confirmed gone from the working tree (deleted in `208046d`,
  2026-09-01) but still present across 7 earlier commits. A targeted search of its historical
  content for path-shaped strings only (not a full read — its cell outputs could carry real
  data, which stays off-limits per the data guardrail) turned up the local Windows username
  (`stefan`) baked into some output paths, plus two participant IDs in `.xdf` filenames
  (`sub-FOH_test`, `sub-TestZuk`) that turned out to be researchers' own pilot recordings, not
  study participant data. Reviewed and judged non-critical — **not purged from history.**
  Considered `git filter-repo --path for_mooi_xdf_processing.ipynb --invert-paths` but ruled
  it out as disproportionate: the file entered history in one of the repo's very first commits,
  so purging it would rewrite every commit on every branch (6 local + 2 remote-only at the
  time), forcing a force-push of all of them and a fresh re-clone for anyone else with a copy
  of the repo — too much disruption for a username and researcher names in dead notebook
  output.

1. Land item 28 (the `mobi`/`mooi` → `vrlab` rename) on the still-private repo, confirmed
   green.
2. ~~Audit git *history* (not just the current working tree) for anything that shouldn't go
   public before flipping visibility — GitHub's secret scanner runs retroactively over all
   history once a repo goes public, so this is worth doing first rather than reactively.~~
   **Done** — see above.
3. GitHub Settings → rename the repo itself (`mobi_mooi_toolbox` → `vrlab_toolbox` — GitHub
   sets up an auto-redirect from the old name).
4. GitHub Settings → change visibility to public.
5. Update the local clone folder name and, for any other existing clone, run
   `git remote set-url` to point at the renamed repo (the auto-redirect covers this for a
   while, but isn't permanent).
6. Once public, item 20's GitHub Pages deferral is unblocked — add the
   `mkdocs gh-deploy`-equivalent Actions job it already describes as "not needed yet."
