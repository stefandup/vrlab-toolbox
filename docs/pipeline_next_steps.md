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

- `processing/pipeline.py:12` — could this form part of pipeline as a class
  override?
- `processing/pipeline.py:98` — make the Sequentials unmodifiable, i.e. you
  can inherit from them.
- `processing/output_data.py:30` — fix that on init it already inits an
  empty participant output data using config.
- `processing/crane_pipeline.py:76` — unlikely to be unique.
- `processing/crane_pipeline.py:84` — might be redundant, since physiology is
  less uniquely specified.
- `processing/crane_pipeline.py:88` — this schema can be split into
  behaviour/debrief and physiology types.
- `processing/crane_pipeline.py:153` — needs a classmethod to avoid future
  errors when implementing pipeline.
- `processing/crane_debrief_behaviour.py:26` — more checks possible here.
- `processing/crane_debrief_behaviour.py:90` — fix this, likely out of
  scope.
- `processing/crane_behaviour.py:12` — convert to tuple.
- `processing/crane_behaviour.py:200` — see if using BIDS might simplify
  things long-run.
- `processing/crane_behaviour.py:254` — create strategy.
- `processing/behaviour.py:16` — messy, half these functions may be
  redundant (see item 4 above).
- `processing/behaviour.py:52` — decide what to do when multiple CSV files
  are found.
- `processing/processing_status.py:18` — split `data_in` into behav data,
  physiology data, etc. (see item 2 above).
- `processing/crane_trial_intervals.py:47` — needs to update with a
  `partial` status.
- `processing/crane_trial_intervals.py:98` — needs to be generalized.
- `processing/crane_trial_intervals.py:164` — make more robust.

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
