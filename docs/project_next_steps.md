# Project Next Steps

## Progress Log: Multi-Paradigm Processing Refactor

The toolbox has moved beyond a single-script research workflow into a more modular processing package. The current code separates major responsibilities into pipeline orchestration, EDA processing, ECG processing, VR interval creation, FOH target processing, XDF loading, and Biopac loading.

The FOH pipeline now handles multiple LSL/XDF streams, including physiology, VR markers, trial events, and target behaviour. It checks for missing streams, logs warnings, and tries to continue where possible instead of failing the whole participant immediately. This is the right direction for messy research data where recordings are often incomplete.

A second VR paradigm, Crane, has also been added. Crane introduces Biopac `.mat` input, trigger-derived intervals, behaviour/debrief processing, and reuse of the existing interval-based EDA processing and QC plotting. Adding this second paradigm showed that the code can support multiple environments, but also exposed the next major design issue: pipeline input/output contracts and dataframe identity need to be explicit before a shared pipeline architecture is introduced.

Crane is now being used as the pilot for a strategy-style pipeline boundary. The pipeline has been moved toward a single input object and a single output object, with a participant-level dataframe, optional QC figure, and processing status. This is the right level of structure for now: each environment can become a function-based strategy first, while a shared template/runner can wait until FOH and Crane prove the same shape in practice.

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

Important design rules:

- missing optional data should produce a logged warning and a `partial` output where possible;
- unrecoverable participant-level failures should produce an `error` output row when that helps downstream accounting;
- the output dataframe should carry processing status so CSV/SPSS analysis can spot partial or failed subjects;
- the Python output object and exported dataframe should agree on status.

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

## Working Rule

Do not rewrite everything at once. Preserve working behaviour and improve one structural issue at a time.

The next major refactor should be:

> function-based strategy contracts first, dataframe contracts alongside them, shared template architecture second.
