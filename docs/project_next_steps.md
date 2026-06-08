# Project Next Steps

## Progress Log: Multi-Paradigm Processing Refactor

The toolbox has moved beyond a single-script research workflow into a more modular processing package. The current code separates major responsibilities into pipeline orchestration, EDA processing, ECG processing, VR interval creation, FOH target processing, XDF loading, and Biopac loading.

The FOH pipeline now handles multiple LSL/XDF streams, including physiology, VR markers, trial events, and target behaviour. It checks for missing streams, logs warnings, and tries to continue where possible instead of failing the whole participant immediately. This is the right direction for messy research data where recordings are often incomplete.

A second VR paradigm, Crane, has also been added. Crane introduces Biopac `.mat` input, trigger-derived intervals, and reuse of the existing interval-based EDA processing and QC plotting. Adding this second paradigm showed that the code can support multiple environments, but also exposed the next major design issue: dataframe identity and dataframe contracts are still too implicit.

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

### 1. Small cleanup

- Replace remaining `print()` calls with logging.
- Fix obvious return type hints, especially functions that can return `None`.
- Fix small robustness issues in loading and missing-column handling.
- Make Crane's failure handling more consistent with FOH.

### 2. Add dataframe contracts

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

### 3. Add small tests

Start with tiny synthetic dataframe tests rather than full real-file tests.

Good first targets:

- missing stream checks;
- trigger interval creation;
- schema accepts valid EDA data;
- schema rejects missing `time_stamps`;
- schema rejects missing signal columns;
- FOH target parsing with missing header compensation;
- interval fallback logic.

### 4. Standardize soft failure rules

Decide which failures should:

- stop a participant;
- skip one modality;
- warn but continue.

Examples:

- missing physiology stream: skip physiology, continue if behaviour can run;
- missing interval data: likely stop interval-based processing;
- one failed EDA interval: skip that interval;
- malformed target data: skip target behaviour;
- corrupted input file: skip participant/file.

### 5. Align FOH and Crane pipeline shape

Both pipelines should eventually follow the same broad sequence:

1. load raw streams or files;
2. normalize column names;
3. validate dataframe contracts;
4. create intervals;
5. run physiology processors;
6. run behaviour processors;
7. combine outputs;
8. generate QC figures;
9. return participant-level output and diagnostics.

### 6. Later: add a paradigm specification

Only after contracts and tests are clearer, introduce a lightweight `ParadigmSpec` or similar structure.

The long-term goal is that a student can add a new VR environment by defining:

- required inputs;
- optional inputs;
- column normalization rules;
- interval creation strategy;
- physiology processors;
- behaviour processors;
- output naming rules.

## Working Rule

Do not rewrite everything at once. Preserve working behaviour and improve one structural issue at a time.

The next major refactor should be:

> dataframe contracts first, shared pipeline architecture second.
