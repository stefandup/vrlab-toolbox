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
[Deferred: FOH & LongWalk](#deferred-foh--longwalk) at the end).

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
- remove the now-dead `from mooi_toolbox.processing import crane_behaviour as
  crane_behaviour` import in `crane_pipeline.py` — nothing in the file
  references `crane_behaviour.` anymore now that it has its own local copy of
  `EMOTIONS_TESTED`;
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

Reconciled against a fresh `grep -rn TODO src/` — three previously-tracked
comments no longer exist in the code (removed below; the code they annotated
was resolved/deleted), one moved file/line without changing meaning, and six
comments exist in code but weren't tracked here yet (added below, each with a
short guess at intent since none had one).

- `processing/pipeline.py:17` — could this form part of pipeline as a class
  override?
- `processing/pipeline.py:139` — make the Sequentials unmodifiable, i.e. you
  can inherit from them.
- `processing/output_data.py:30` — fix that on init it already inits an
  empty participant output data using config.
- `processing/crane_pipeline.py:64` — might be redundant, since physiology is
  less uniquely specified.
- `processing/crane_pipeline.py:68` — this schema can be split into
  behaviour/debrief and physiology types.
- `processing/crane_pipeline.py:153` — needs a classmethod to avoid future
  errors when implementing pipeline.
- `processing/crane_debrief_behaviour.py:28` — more checks possible here.
- `processing/crane_debrief_behaviour.py:93` — fix this, likely out of
  scope.
- `processing/crane_behaviour.py:12` — convert to tuple.
- `processing/crane_behaviour.py:200` — see if using BIDS might simplify
  things long-run.
- `processing/behaviour.py:16` — messy, half these functions may be
  redundant (see item 4 above).
- `processing/behaviour.py:53` — decide what to do when multiple CSV files
  are found.
- `processing/processing_status.py:18` — split `data_in` into behav data,
  physiology data, etc. (see item 2 above).
- `processing/crane_trial_intervals.py:95` — needs to be generalized.
- `processing/trial_intervals.py:446` (moved from the now-deprecated
  `crane_trial_intervals.py`) — needs to update with a `partial` status.

Newly found, not previously tracked here — descriptions below are this
assistant's best guess at intent, not confirmed with the code's author:

- `processing/input_data.py:16` — "Add PipelineStatus to config." Likely the
  seed of item 12: `ParticipantConfig` construction currently raises
  immediately on file-discovery failure; giving the config its own
  `PipelineStatus` field is what would let failures be recorded instead of
  raised.
- `processing/input_data.py:81` — "implement cross checking for this
  toolbox." Reads as a check that the physiology file and each discovered
  behaviour file actually belong to the same session/date, rather than
  trusting the filename match — the kind of check that would have caught the
  `PID15868` timestamp-mismatch bug (item 4) before it cascaded.
- `processing/pipeline.py:181` — "Printout the rest also using data type."
  Ties to item 2: once status is tracked per strategy/data type instead of
  one merged stage-level enum, this is the corresponding printout that would
  break results out by data type instead of one summary line.
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
- `processing/crane_pipeline.py:69` — "Can be rebuilt from a
  `CranePipelineOutputData.from_pipeline_output(...)` classmethod." Ties to
  item 11: rather than deleting the unused `CraneDebriefOutputData` /
  `build_crane_debrief_output_schema` outright, this suggests reconstructing
  it via a classmethod off the pipeline output — worth resolving alongside
  item 11's delete-vs-consolidate decision.

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
`get_crane_predicted_trigger_intervals` helper are no longer called anywhere
in the pipeline and are candidates for deletion once the new path is
confirmed stable across subjects.

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

### 11. Remove unused `CraneDebriefOutputData` / clarify naming vs. `CraneDebriefPipelineOutput`

`crane_pipeline.py` defines `build_crane_debrief_output_schema()` and
`CraneDebriefOutputData` (right under the `# TODO Unlikely to be unique!`
comment tracked in item 8), but neither is referenced anywhere else in the
codebase — the debrief step actually uses a different, similarly-named class,
`CraneDebriefPipelineOutput` in `crane_debrief_behaviour.py`, which builds its
own separate schema (`crane_debrief_pipeline_output_schema`). Two
near-identically-named classes doing unrelated things is an easy way to edit
the wrong one later.

Needed:

- delete `build_crane_debrief_output_schema()` and `CraneDebriefOutputData`
  from `crane_pipeline.py` if confirmed dead;
- if some debrief-schema consolidation is intended instead (see item 3), fold
  this into that work rather than keeping two similarly-named classes in
  play.

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

### 13. Date-string extraction in `from_physiology_data` breaks on the data folder's path separator

Found during review of `crane_pipeline.py`/`FindCraneParticipantFilesStrategyStep`, while
chasing why `tests/test_crane_pipeline.py` couldn't even collect. Two other bugs in the
same code path were found and fixed first (both now resolved):

- `BiopacDataImportStartegy.input_data_file_format` (`biopac.py`) was `PhysiologyFileFormat.BIOPAC`
  (`.acq`) even though `load_biopac_data` loads `.mat` files via `scipy.io.loadmat` — fixed to
  `PhysiologyFileFormat.MATLAB`.
- The physiology glob in `from_physiology_data` (`input_data.py`) was
  `f"*{id_in}_{physiology_data_type_in.value}"`, which assumes the id is immediately followed
  by the extension with nothing in between. Real filenames are
  `{date}_{id}_CraneOut.{ext}`, so nothing ever matched. Fixed to
  `f"*_{id_in}_*{physiology_data_type_in.value}"` and confirmed against all fixture IDs in
  `crane_data/`.

With both of those fixed, collection gets further but still fails:

```
FileNotFoundError: No file matches for RawCraneBehaviourData for participant 00020
```

Root cause, `input_data.py`:

```python
expected_date_string_from_physiology = str(physiology_fn).split("_")[0]
```

`physiology_fn` is a `Path`; `str(path)` on Windows renders with backslashes
(`crane_data\2026481120_00020_CraneOut.mat`). Splitting on `"_"` doesn't split on the
backslash, so the first token is `"crane"` (from `crane_data`) instead of the intended
date prefix `2026481120`. Confirmed by testing directly: `physiology_fn.name.split("_")[0]`
gives the correct value; `str(physiology_fn).split("_")[0]` does not. This wrong date string
then feeds the behaviour-file glob (`{date_string}_{participant_id}_*.csv`), so no behaviour
CSV is ever found for any participant.

This is the remaining blocker on `tests/test_crane_pipeline.py` collecting/running at all —
pick up here next. Likely overlaps with item 4's "don't assume filename conventions hold"
and item 12's broader file-discovery cleanup.

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

**Current test coverage:** `tests/test_crane_pipeline.py` marks the three
affected tests `@unittest.skip(...)` with a reason referencing this item,
rather than guessing at post-fix behaviour:
`test_crane_pipeline_labels_missing_physiology_correctly`,
`test_crane_pipeline_labels_missing_behav_correctly`,
`test_crane_spots_errors_when_behav_physiology_no_match`. Once these bugs are
fixed, un-skip them and update their assertions to match real output (the
`missing_debrief` constant in the same file has a comment flagging the
`RawCraneBehaviourData` artifact for `PID8495`, which should disappear once
this is fixed).

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
trial-interval step ([pipeline.py:361-377](../src/mooi_toolbox/processing/pipeline.py#L361-L377)).
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

## Working Rule

Do not rewrite everything at once. Preserve working behaviour and improve
one structural issue at a time: function-based strategy contracts first,
dataframe contracts alongside them, shared template architecture second.

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
- `processing/input_data.py:3` — dataclass could look for variables and
  generate errors.
- `cli/vrlab_crane_qc.py:19` — add summary data processing.
- `cli/check_mobi_xdf.py:24` — show missing streams.
- `cli/vrlab_crane_process.py:50,62` — fix str-to-path handling; `:114` —
  data labels for SPSS output.
- `processing/ecg.py:15,26` — NeuroKit warnings to address on update; combine
  outputs (maybe a dict).
