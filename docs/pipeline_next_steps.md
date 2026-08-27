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
- `processing/processing_status.py:18-19` — split `data_in` into behav data,
  physiology data, etc.; might need a builder in the pipeline template. Both
  now stale — see item 2's update above; safe to delete once someone
  confirms nothing else was meant by the second line.
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
  and would also have caught item 13's still-open date-string bug sooner.
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

**Update — stale, corrected:** the line itself (`input_data.py:57`) is still unfixed today,
but the paragraph above overstates its consequence. The actual behaviour-file glob
(`input_data.py:85-89`) is built with `glob_pattern = behav_data_type.filename_glob.format(date_string=TEMP, ...)`
where `TEMP = "*"` — a hardcoded wildcard, not `expected_date_string_from_physiology`. That
variable is only used ~10 lines later to build a diagnostic mismatch warning
(`behav_date_mismatches`), so the bug never actually blocked file discovery, and does not
explain any test failure. `tests/test_crane_pipeline.py` collects and mostly passes today (see
item 16's update).

The bug is still real, though, and worth fixing on its own terms: `expected_date_string_from_physiology`
evaluates to `"crane"` in this repo (`str(Path("crane_data/2026481120_00020_CraneOut.mat")).split("_")[0]`),
and the mismatch check (`not str(file).startswith(expected_date_string_from_physiology)`) currently
never fires as a false positive purely because every real file path here starts with `crane_data\`,
which also starts with `"crane"` — coincidence, not correctness. Point `data_folder_in` at a path that
doesn't start with `"crane"` (an absolute path, a different-named folder) and every file would wrongly
be flagged as a date mismatch; conversely, a real date mismatch that doesn't happen to also fail the
`"crane"` prefix check would go undetected. Fix: use `physiology_fn.name.split("_")[0]` instead of
`str(physiology_fn).split("_")[0]`, same as originally diagnosed. Likely overlaps with item 4's
"don't assume filename conventions hold" and item 12's broader file-discovery cleanup.

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

### 19. Small note: `crane_pipeline.py`'s `import crane_behaviour as crane_behaviour` is still dead

Confirmed again this REVIEW: `crane_pipeline.py:8` still imports
`from mooi_toolbox.processing import crane_behaviour as crane_behaviour`, and nothing in the
file references `crane_behaviour.` — this is the same dead import flagged in item 3, kept here
only as a pointer since it's easy to miss inside item 3's larger consolidation ask and cheap to
delete on its own before that lands.

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

### 23. Manually test the crane unparseable-filename correction dialog

Not yet run by a human. `crane_convert_to_bids.py` (corrections JSON, `resolve_crane_filename`,
`discover_unparseable_raw_files`, `explain_unparseable_filename`), `bids_crosscheck_common.py`
(`extra_raw_action` generalized to `extra_raw_actions`, a list), and `crane_bids_crosscheck_gui.py`
(`UnparseableFilenameCorrectionDialog`, new "Fix unparseable filenames..." button) were all
written and read back for consistency, but never actually launched.

Needed — launch the GUI (`python -m mooi_toolbox.gui.crane_bids_crosscheck_gui`, or however this
is normally invoked) against a raw folder containing a deliberately mis-named file, and check:

- both "Raw folder" and "BIDS folder" need to be selected before "Fix unparseable filenames..."
  (and "Fix debrief record IDs...") enable at all;
- the dialog lists the mis-named file(s) with the correct relative-to-raw-folder path;
- selecting a row updates the "Why this failed" bottom pane with a sensible plain-English reason;
- before ever clicking "Refresh BIDS" in this session, the bottom pane's log-excerpt line reads
  the "no matching line yet" placeholder rather than erroring;
- after clicking "Refresh BIDS" once, reselecting the same row shows the matching captured log
  line instead;
- typing a subject id and clicking Save writes `raw_filename_id_corrections.json` into the BIDS
  folder, keyed by the file's relative path;
- leaving the box blank and saving does *not* add an entry (or removes one if it existed) — the
  file should still be skipped and still show up next time the dialog is opened;
- after saving a real correction and clicking "Refresh BIDS" again, the file is copied into the
  corrected subject's `sub-XXX/ses-01/beh/` folder, with `acq_time` recorded as `"nodate"` in
  `scans.tsv` (corrected entries have no derivable date prefix);
- reopening the dialog afterward no longer lists that now-resolved file;
- two unparseable files that happen to share a bare filename in different raw subfolders can be
  corrected independently, without one overwriting the other's entry;
- the existing "Fix debrief record IDs..." button/dialog still works unchanged — regression
  check on the `extra_raw_action` → `extra_raw_actions` list generalization;
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

Needed — launch `mobi_foh_bids_crosscheck` and check:

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

### 25. `input_data.py`'s FOH physiology lookup needs updating for the new real-BIDS task tag

Not done yet — flagged 2026-08-27 for the project owner to pick up themselves; out of
scope for the crosscheck/converter rework that prompted it (see
[bids_converter_plan.md](bids_converter_plan.md)'s TODO section for the FOH+crane
re-implementation reminder this is part of).

The FOH crosscheck GUI's "Tag as..." action (`gui/foh_bids_crosscheck_gui.py`'s
`FOH_DATASET_CONFIG`, via `processing/bids_crosscheck.record_task_tag`) now writes real BIDS
entities instead of a bare non-BIDS label: a tagged recording used to end in `..._foh.xdf`
and now ends in `..._task-foh_acq-lsl_run-<NNN>_beh.xdf` (task-foh entity, acq-lsl entity,
real `beh` suffix, same `.xdf` extension).

`processing/input_data.py:167-183` (`ParticipantConfig.from_lsl_data`'s physiology lookup)
still expects the *old* shape: it globs `*{id}*{PIPELINE_ID}{extension}` (`PIPELINE_ID =
"foh"`, hardcoded at `input_data.py:20`) and then requires the filename's last
underscore-delimited token to be exactly `"foh.xdf"`
(`str(xdf_path.name).split("_")[-1] != f"{PIPELINE_ID}.xdf"`). Once real FOH data actually
gets tagged with the new scheme, that check's last token will be `"beh.xdf"`, not `"foh.xdf"`
— every real recording would raise `ValueError("No physiology files matching *_foh.xdf found
for participant ...")` instead of being found. This is real pipeline/processing code
(`processing/`, not `cli/`/`gui/`), so it was deliberately left untouched by the
crosscheck/converter rework — needs its own pass to match the new filename shape (and decide
whether `PIPELINE_ID`'s manual sync with `FOH_DATASET_CONFIG.task_tag_task`, already flagged
as a loose end, gets addressed at the same time).

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
- `cli/vrlab_crane_qc.py:19` — add summary data processing.
- `cli/check_mobi_xdf.py:24` — show missing streams.
- `cli/vrlab_crane_process.py:109` — data labels for SPSS output.
  (The str-to-path handling previously tracked here is resolved:
  `biopac.get_subject_id_from_mat` now takes a `Path` directly, and the CLI
  passes `output_folder` through to `run_crane_pipeline` instead of a bare
  `input_folder`.)
- `processing/ecg.py:15,26` — NeuroKit warnings to address on update; combine
  outputs (maybe a dict).
