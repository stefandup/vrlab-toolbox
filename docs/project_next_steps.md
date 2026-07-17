# Project Next Steps

## Progress Log: Multi-Paradigm Processing Refactor

The toolbox has moved beyond a single-script research workflow into a more modular processing package. The current code separates major responsibilities into pipeline orchestration, EDA processing, ECG processing, VR interval creation, FOH target processing, XDF loading, and Biopac loading.

The FOH pipeline now handles multiple LSL/XDF streams, including physiology, VR markers, trial events, and target behaviour. It checks for missing streams, logs warnings, and tries to continue where possible instead of failing the whole participant immediately. This is the right direction for messy research data where recordings are often incomplete.

A second VR paradigm, Crane, has also been added. Crane introduces Biopac `.mat` input, trigger-derived intervals, behaviour/debrief processing, and reuse of the existing interval-based EDA processing and QC plotting. Adding this second paradigm showed that the code can support multiple environments, but also exposed the next major design issue: pipeline input/output contracts and dataframe identity need to be explicit before a shared pipeline architecture is introduced.

Crane is now being used as the pilot for a strategy-style pipeline boundary. The pipeline has been moved toward a single input object and a single output object, with a participant-level dataframe, optional QC figure, and processing status. This is the right level of structure for now: each environment can become a function-based strategy first, while a shared template/runner can wait until FOH and Crane prove the same shape in practice.

The Crane clock issue has been corrected, but it still needs more testing against additional participants/files before treating it as fully settled.

## Main Lesson

The next step is not a whole rewrite. The code already has good bones and should be refactored gradually.

The main problem is that it is often unclear which dataframe is being passed around:

- raw loaded data;
- renamed signal data;
- timestamped physiology data;
- trigger data;
- marker data;
- parsed behaviour data;
- interval-level output;
- participant-level wide output.

This makes it harder to add new pipelines and harder for students to know where new code belongs.

## Planned Direction

Use a contract-first refactor before doing a larger architecture refactor.

The immediate architectural direction is:

1. make each paradigm pipeline a clear function-based strategy;
2. align inputs, outputs, statuses, and validation behaviour;
3. only then consider a shared template/runner for common orchestration.

### 1. Small cleanup

- Replace remaining `print()` calls with logging.
- Fix obvious return type hints, especially functions that can return `None`.
- Fix small robustness issues in loading and missing-column handling.
- Finish Crane's small contract cleanup: tests, nullable figures in CLIs, and consistent status handling.

### 2. Standardize pipeline input/output contracts

Before extracting shared abstractions, make each paradigm pipeline expose the same broad contract:

- one input dataclass;
- one output dataclass;
- participant-level output dataframe;
- optional QC figure;
- processing status such as `ok`, `partial`, or `error`;
- validation at the output boundary.

Crane is the pilot implementation for this pattern. FOH should follow next, without introducing a shared template yet.

Crane is heading in the right direction as the reference pipeline shape. The useful pattern is that it now returns both a Python status object and an exported `Processing_Status` column. Before copying this pattern into FOH, make the status contract more rigorous:

- use fixed status keys across pipelines, such as `data_in`, `behaviour`, `debrief`, `intervals`, and `physiology`;
- serialize statuses in a fixed order so tests and CSV/SPSS outputs do not depend on update order;
- define what `ok`, `partial`, and `error` mean for each stage;
- decide whether `intervals=error` should stop physiology processing or mean that physiology was attempted but should not be trusted;
- make core participant output columns such as `Subject_ID` and `Processing_Status` required once the Crane output shape is settled.

Important design rules:

- missing optional data should produce a logged warning and a `partial` output where possible;
- unrecoverable participant-level failures should produce an `error` output row when that helps downstream accounting;
- the output dataframe should carry processing status so CSV/SPSS analysis can spot partial or failed subjects;
- the Python output object and exported dataframe should agree on status.
- Next NB: correct the output columns so stress-first and stress-last recordings produce consistent, predictable column names, using one explicit normalization rule rather than letting recording order leak into final column names.

### 3. Add dataframe contracts

Introduce Pandera schemas for important dataframe shapes.

Pandera may be especially useful in this project because many pipeline errors come from uncertainty about dataframe identity: which columns are present, whether signal columns have already been renamed, whether timestamps are attached, and whether a dataframe is raw, parsed, interval-level, or participant-level.

The benefit is not just stricter validation. Pandera schemas can act as executable documentation. A schema gives each important dataframe a name and makes its expected columns, types, and null-handling rules visible to both the code and the students reading it.

This should reduce scattered manual checks such as repeatedly asking whether `time_stamps`, `EDA`, `Trigger`, or `FOH_target` exist. Instead, each pipeline stage can validate its input once at the boundary and then assume a clear contract internally.

Likely first schemas:

- OpenSignals EDA data;
- OpenSignals ECG data;
- Biopac EDA data;
- Biopac Trigger data;
- VR marker streams;
- VR trial event streams;
- FOH raw target data;
- parsed target data;
- interval-level EDA summaries;
- participant-level wide outputs.

Pandera should not replace all error handling. It should make dataframe expectations explicit and reduce scattered manual checks.

Use Pandera mainly at boundaries:

- after loading data;
- after renaming or normalizing columns;
- before analysis functions;
- after producing participant-level outputs.

Avoid validating every tiny intermediate dataframe unless it prevents a real source of confusion or failure.

### 4. Add small tests

Start with tiny synthetic dataframe tests rather than full real-file tests.

Good first targets:

- Crane output status for successful, partial, and error cases;
- Crane output dataframe includes `Processing_Status`;
- missing stream checks;
- trigger interval creation;
- schema accepts valid EDA data;
- schema rejects missing `time_stamps`;
- schema rejects missing signal columns;
- FOH target parsing with missing header compensation;
- interval fallback logic.

### 5. Standardize soft failure rules

Decide which failures should:

- stop a participant;
- skip one modality;
- warn but continue.

Examples:

- missing physiology stream: skip physiology, continue if behaviour can run;
- missing interval data: likely stop interval-based processing;
- one failed EDA interval: skip that interval;
- malformed target data: skip target behaviour;
- corrupted input file: return an error output row or skip participant/file, depending on whether downstream accounting needs a row.

### 6. Align FOH and Crane pipeline shape

Both pipelines should eventually follow the same broad sequence:

1. load raw streams or files;
2. normalize column names;
3. validate dataframe contracts;
4. create intervals;
5. run physiology processors;
6. run behaviour processors;
7. combine outputs;
8. generate QC figures;
9. return participant-level output, diagnostics, and processing status.

Do this alignment with function-based strategy objects first. Avoid a class hierarchy unless a pipeline needs persistent state or lifecycle methods.

### 7. Later: add a lightweight runner/template

Only after contracts and tests are clearer, introduce a lightweight pipeline runner, template, `ParadigmSpec`, or similar structure.

The long-term goal is that a student can add a new VR environment by defining:

- required inputs;
- optional inputs;
- column normalization rules;
- interval creation strategy;
- physiology processors;
- behaviour processors;
- output naming rules.

The likely future shape is a small runner that accepts a pipeline context and a list of step functions. Each step should return a predictable result: output dataframe, optional figure, status/skip reason, and logs. This should come after Crane and FOH both follow the simpler input/output strategy contract.

### 8. Decide: in-place mutation vs. return-new-object

While refactoring the pipeline status/store classes, a real bug showed up: `PipelineStatus.merge()` returns a *new* `PipelineStatus` instead of mutating `self`, but a call site wrote `pipeline_status.merge(other)` without reassigning the result — the merge silently did nothing. Both call sites in the SequentialSteps runner and the mismatch went unnoticed because there was no consistent rule for which style a given class follows.

Before extending this pattern to more classes (stores, statuses, future strategy result objects), pick one convention and apply it consistently, rather than deciding per-class by feel.

**Option A — mutate in place, return `None`.** Callers just call the method; nothing to forget.

```python
# Restaurant domain: a running kitchen_queue that absorbs new orders in place.
class KitchenQueue:
    def __init__(self):
        self.orders = []

    def add_order(self, order: dict) -> None:
        self.orders.append(order)

# Call site: no reassignment needed, mutation is implicit.
queue = KitchenQueue()
queue.add_order({"table": 1, "dish": "burger"})
```

**Option B — return a new object, never mutate `self`.** Safer to reason about (no hidden side effects, easy to test), but every call site *must* reassign or the update is silently lost — exactly the bug found above.

```python
# Restaurant domain: order_status is immutable; combining two produces a new one.
@dataclass(frozen=True)
class OrderStatus:
    prepared: bool = False
    served: bool = False

    def merge(self, other: "OrderStatus") -> "OrderStatus":
        return OrderStatus(
            prepared=self.prepared or other.prepared,
            served=self.served or other.served,
        )

# Call site: MUST reassign, or the merge is a no-op.
status = status.merge(other_status)  # correct
status.merge(other_status)           # bug: return value discarded
```

**Guidance for picking:**

- Prefer Option A (mutate in place) for accumulator-style objects that exist only to be built up over a loop (e.g. the raw data stores) — there is one clear owner and no risk of aliasing surprises.
- Prefer Option B (return-new) for small value-like objects that get compared, tested, or passed around (e.g. status objects) — but only if every call site can be trusted to reassign. Consider naming methods to make the contract obvious (e.g. `with_merged(...)` instead of a bare `merge(...)`) so a bare, non-reassigned call reads as obviously wrong.
- Never mix both behaviours across sibling methods on the same class — that's what made the bug easy to miss here.
- Whichever convention is chosen, add a one-line docstring note (`"""Mutates self in place."""` or `"""Returns a new instance; does not mutate self."""`) so it doesn't have to be re-derived by reading the implementation.

### 9. Clean up behaviour-data file matching and loading

`behaviour.py` already carries a TODO flagging this ("This is very messy. Not sure if half of these functions arent redundant!") — worth expanding into a concrete cleanup item rather than leaving it as a one-line note.

Current state: `load_and_validate_behaviour_csv`, `load_validate_physiology_behav_data`, and `load_from_participant_config` overlap heavily, and only one of those paths (`load_from_participant_config`, via `RawBehaviourData.load_from_config`) is actually used by the Crane pipeline — the other two appear to be dead code left over from an earlier version. File matching itself (`behaviour_matches_biopac_physiology_data`) builds its search purely from the physiology file's stem, meaning it silently assumes the `.mat` and `.csv` files for a session share an identical timestamp prefix.

This surfaced as a real bug, not just theoretical mess: participant `PID15868`'s behaviour CSV was exported with a different timestamp than its `.mat` file (`...5121237` vs `...5131237`), so the regex-based match found nothing and raised a generic `FileNotFoundError`. That failure then cascaded — crane behaviour data never entered the store, so interval matching and physiology processing failed too, in a way that looked like a pipeline logic bug and took real effort to trace back to "the file search just didn't find the file, for an uninformative reason."

Needed: a straightforward and more consistent way of checking whether a participant's files exist, that:

- has one reusable function/contract for "find this participant's file(s) of type X," used the same way across behaviour, debrief, and physiology loading instead of ad hoc `Path.rglob` + regex per case;
- reports *why* a file wasn't found in a way that's distinguishable in logs — "no file for this subject at all" vs "a file exists but doesn't match the expected pattern" are very different problems and currently produce the same generic error;
- doesn't assume filename conventions (like matching timestamps across file types) hold for every participant — real recordings can have mismatched or manually-corrected filenames, and the matching logic should make that visible rather than silently returning zero matches;
- removes the redundant/dead loading functions once the used path is clear, so there's exactly one way to load and validate a participant's behaviour CSV.

### 10. Consolidate duplicated Crane behaviour constants

`EMOTIONS_TESTED`, `BLOCK_TYPES`, `TRIAL_TYPES`, and `BEHAVIOUR_OUTPUT_METRICS` are each currently defined independently in more than one place — `crane_pipeline.py` has its own full copies of all four; `crane_debrief_behaviour.py` separately redeclares its own `EMOTIONS_TESTED` (as a tuple, not a list) and `TRIAL_TYPES`. None of these import from a shared source, so keeping the emotion list or trial types consistent across files depends on remembering to edit all of them by hand, with nothing catching it if they drift apart.

`crane_behaviour.py` is the natural single source of truth for these, since it's where they're actually used to build and validate the behaviour schema (`build_crane_raw_behav_file_schema`, the `EmotionFeedback` isin-check, the `EMOTIONS_TESTED` reindexing in the summary functions) rather than just referenced for building output column names elsewhere.

Needed:

- move `EMOTIONS_TESTED`, `BLOCK_TYPES`, `TRIAL_TYPES`, and `BEHAVIOUR_OUTPUT_METRICS` into `crane_behaviour.py` as the canonical definitions;
- update `crane_pipeline.py`'s schema-building functions to import them from there instead of redeclaring;
- update `crane_debrief_behaviour.py` to import `EMOTIONS_TESTED`/`TRIAL_TYPES` from `crane_behaviour.py` too, deciding on one canonical type (list vs tuple) when consolidating;
- once consolidated, a small test asserting the debrief and pipeline column names line up with the behaviour schema's would catch future drift.

## Working Rule

Do not rewrite everything at once. Preserve working behaviour and improve one structural issue at a time.

The next major refactor should be:

> function-based strategy contracts first, dataframe contracts alongside them, shared template architecture second.
