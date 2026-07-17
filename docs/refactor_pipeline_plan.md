# Pipeline Refactor Plan

## Goal

Refactor the current pipeline so that the high-level pipeline skeleton stays stable, while individual import, behaviour, physiology, QC, and saving steps remain easy to replace, extend, skip, or combine.

The key design idea is:

```text
Import once
→ Run zero or more behaviour steps
→ Run zero or more physiology steps
→ QC
→ Save
```

This uses a combination of:

- **Template Method pattern**: the pipeline defines the overall order of operations.
- **Strategy pattern**: each operation is delegated to replaceable strategy objects.
- **Composite pattern**: multiple processing steps can be grouped into one sequential runner.
- **Null-object style empty composites**: skipped stages are represented by empty step lists rather than `None`.

---

## 1. Core Protocols

Start by defining the contracts that concrete classes must satisfy.

```python
from typing import Protocol


class ImportDataStrategy(Protocol):
    def import_data(
        self,
        config_in: ParticipantConfig,
    ) -> PipelineData:
        ...


class PipelineBehaviourStep(Protocol):
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        ...


class PipelinePhysiologyStep(Protocol):
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        ...


class DataQcStrategy(Protocol):
    def qc_data(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> None:
        ...


class SavingDataStrategy(Protocol):
    def save_data(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> None:
        ...
```

### Why split behaviour and physiology?

Even if the method shape is currently the same:

```python
(config_in, data_in) -> data_out
```

behaviour and physiology represent different conceptual contracts. Later, they may need different input data, validation rules, or configuration options.

For example, physiology steps may later depend on raw ECG/EDA streams, while behaviour steps may depend on task logs or debrief data. Keeping separate protocols makes this future change easier.

---

## 2. Sequential Step Containers

Use composite strategy classes to run several steps back to back.

```python
from dataclasses import dataclass, field
from collections.abc import Sequence


@dataclass
class SequentialBehaviourSteps:
    steps: Sequence[PipelineBehaviourStep] = field(default_factory=list)

    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        for step in self.steps:
            data_in = step.run(
                config_in=config_in,
                data_in=data_in,
            )

        return data_in


@dataclass
class SequentialPhysiologySteps:
    steps: Sequence[PipelinePhysiologyStep] = field(default_factory=list)

    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        for step in self.steps:
            data_in = step.run(
                config_in=config_in,
                data_in=data_in,
            )

        return data_in
```

### Important design point

These containers can hold one step, many steps, or no steps.

```python
SequentialPhysiologySteps(
    steps=[
        ProcessECG(),
        ProcessEDA(),
    ]
)
```

or:

```python
SequentialPhysiologySteps()
```

An empty container simply returns `data_in` unchanged. This makes skipping a stage robust without needing `None` checks.

Avoid this where possible:

```python
physiology_strategy_steps: SequentialPhysiologySteps | None
```

because then every pipeline must remember to check for `None`.

Prefer this:

```python
physiology_strategy_steps=SequentialPhysiologySteps()
```

---

## 3. Example Concrete Behaviour Steps

```python
class ProcessCraneBehaviour:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        # Load/process main Crane task behaviour data.
        # Add results to data_in.
        return data_in


class ProcessCraneDebrief:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        # Load/process debrief questionnaire data.
        # Add results to data_in.
        return data_in
```

Both classes satisfy the `PipelineBehaviourStep` protocol because they implement:

```python
def run(config_in, data_in) -> PipelineData:
    ...
```

---

## 4. Example Concrete Physiology Steps

```python
class ProcessCraneECG:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        # Load/process ECG data.
        # Add ECG outputs to data_in.
        return data_in


class ProcessCraneEDA:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        # Load/process EDA data.
        # Add EDA outputs to data_in.
        return data_in
```

Both classes satisfy the `PipelinePhysiologyStep` protocol.

---

## 5. Pipeline Skeleton

The pipeline itself owns the order of operations.

```python
from dataclasses import dataclass


@dataclass
class CranePipeline:
    import_strategy: ImportDataStrategy
    behaviour_strategy_steps: SequentialBehaviourSteps
    physiology_strategy_steps: SequentialPhysiologySteps
    qc_strategy: DataQcStrategy
    saving_strategy: SavingDataStrategy

    def run(self, config_in: ParticipantConfig) -> PipelineData:
        data_out = self.import_strategy.import_data(
            config_in=config_in,
        )

        data_out = self.behaviour_strategy_steps.run(
            config_in=config_in,
            data_in=data_out,
        )

        data_out = self.physiology_strategy_steps.run(
            config_in=config_in,
            data_in=data_out,
        )

        self.qc_strategy.qc_data(
            config_in=config_in,
            data_in=data_out,
        )

        self.saving_strategy.save_data(
            config_in=config_in,
            data_in=data_out,
        )

        return data_out
```

### Naming note

`processing_strategy_steps` was considered as a general name. However, once behaviour and physiology are split, the clearer names are:

```python
behaviour_strategy_steps
physiology_strategy_steps
```

These names make it obvious that each field contains a sequential group of strategy-like steps.

---

## 6. Example Pipeline With Behaviour and Physiology

```python
pipeline = CranePipeline(
    import_strategy=CraneImportStrategy(),

    behaviour_strategy_steps=SequentialBehaviourSteps(
        steps=[
            ProcessCraneBehaviour(),
            ProcessCraneDebrief(),
        ]
    ),

    physiology_strategy_steps=SequentialPhysiologySteps(
        steps=[
            ProcessCraneECG(),
            ProcessCraneEDA(),
        ]
    ),

    qc_strategy=CraneQcStrategy(),
    saving_strategy=CraneSavingStrategy(),
)


data_out = pipeline.run(config_in)
```

---

## 7. Example Behaviour-Only Pipeline

Some pipelines may not have physiology data. This is handled by passing an empty physiology step container.

```python
pipeline = CranePipeline(
    import_strategy=CraneImportStrategy(),

    behaviour_strategy_steps=SequentialBehaviourSteps(
        steps=[
            ProcessCraneBehaviour(),
            ProcessCraneDebrief(),
        ]
    ),

    physiology_strategy_steps=SequentialPhysiologySteps(),

    qc_strategy=CraneQcStrategy(),
    saving_strategy=CraneSavingStrategy(),
)
```

The pipeline can still call:

```python
data_out = self.physiology_strategy_steps.run(
    config_in=config_in,
    data_in=data_out,
)
```

If there are no physiology steps, `data_out` is returned unchanged.

---

## 8. Overriding or Replacing Steps

There are two main ways to override behaviour.

### Option A: Replace the whole step

This is the most strategy-pattern-friendly approach.

```python
class ProcessCraneEDA:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        # Standard EDA processing.
        return data_in


class ProcessCraneEDANeuroKit:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        # Alternative EDA processing using NeuroKit.
        return data_in
```

Then choose the implementation during pipeline construction:

```python
physiology_strategy_steps=SequentialPhysiologySteps(
    steps=[
        ProcessCraneECG(),
        ProcessCraneEDANeuroKit(),
    ]
)
```

### Option B: Subclass and override one internal method

Use inheritance only when most of the algorithm is shared and only one part changes.

```python
class ProcessCraneEDA:
    def run(
        self,
        config_in: ParticipantConfig,
        data_in: PipelineData,
    ) -> PipelineData:
        raw_eda = self.load_eda(config_in)
        clean_eda = self.clean_eda(raw_eda)
        features = self.extract_features(clean_eda)

        data_in.eda_features = features
        return data_in

    def load_eda(self, config_in: ParticipantConfig):
        ...

    def clean_eda(self, raw_eda):
        ...

    def extract_features(self, clean_eda):
        ...


class ProcessCraneEDANeuroKit(ProcessCraneEDA):
    def clean_eda(self, raw_eda):
        # Override only the cleaning step.
        ...
```

Then use it exactly like any other physiology step:

```python
physiology_strategy_steps=SequentialPhysiologySteps(
    steps=[
        ProcessCraneECG(),
        ProcessCraneEDANeuroKit(),
    ]
)
```

---

## 9. Suggested Migration Steps

### Step 1: Define protocols

Create protocols for:

```python
ImportDataStrategy
PipelineBehaviourStep
PipelinePhysiologyStep
DataQcStrategy
SavingDataStrategy
```

Place them somewhere central, for example:

```text
mooi_toolbox/processing/protocols.py
```

or:

```text
mooi_toolbox/processing/strategies.py
```

---

### Step 2: Create sequential containers

Create:

```python
SequentialBehaviourSteps
SequentialPhysiologySteps
```

Suggested location:

```text
mooi_toolbox/processing/sequential_steps.py
```

or keep them near the protocol definitions if the project is still small.

---

### Step 3: Convert concrete processing classes

Update each concrete processing class so that it implements `.run(...)`.

For example:

```python
class ProcessCraneBehaviour:
    def run(self, config_in: ParticipantConfig, data_in: PipelineData) -> PipelineData:
        ...
```

and:

```python
class ProcessCraneEDA:
    def run(self, config_in: ParticipantConfig, data_in: PipelineData) -> PipelineData:
        ...
```

---

### Step 4: Update the main pipeline class

Update the pipeline so that it has:

```python
behaviour_strategy_steps: SequentialBehaviourSteps
physiology_strategy_steps: SequentialPhysiologySteps
```

and calls both in order:

```python
data_out = self.behaviour_strategy_steps.run(config_in, data_out)
data_out = self.physiology_strategy_steps.run(config_in, data_out)
```

---

### Step 5: Configure each concrete pipeline

For each pipeline, explicitly configure the relevant steps.

A full VR physiology pipeline might use:

```python
behaviour_strategy_steps=SequentialBehaviourSteps(
    steps=[
        ProcessCraneBehaviour(),
        ProcessCraneDebrief(),
    ]
)

physiology_strategy_steps=SequentialPhysiologySteps(
    steps=[
        ProcessCraneECG(),
        ProcessCraneEDA(),
    ]
)
```

A behaviour-only pipeline might use:

```python
behaviour_strategy_steps=SequentialBehaviourSteps(
    steps=[
        ProcessCraneBehaviour(),
        ProcessCraneDebrief(),
    ]
)

physiology_strategy_steps=SequentialPhysiologySteps()
```

---

## 10. Recommended Rule of Thumb

Use protocols for the broad contract:

```text
What kind of thing is this?
```

Use concrete step classes for the actual implementation:

```text
How does this specific pipeline do it?
```

Use sequential containers when more than one step belongs to the same stage:

```text
Run these behaviour steps in order.
Run these physiology steps in order.
```

Use empty sequential containers instead of `None` when a stage is skipped:

```python
SequentialPhysiologySteps()
```

This keeps the high-level pipeline simple, predictable, and robust.

---

## 11. Final Target Shape

The final architecture should feel like this:

```text
CranePipeline
│
├── import_strategy
│   └── CraneImportStrategy
│
├── behaviour_strategy_steps
│   └── SequentialBehaviourSteps
│       ├── ProcessCraneBehaviour
│       └── ProcessCraneDebrief
│
├── physiology_strategy_steps
│   └── SequentialPhysiologySteps
│       ├── ProcessCraneECG
│       └── ProcessCraneEDA
│
├── qc_strategy
│   └── CraneQcStrategy
│
└── saving_strategy
    └── CraneSavingStrategy
```

For a behaviour-only pipeline:

```text
CranePipeline
│
├── import_strategy
│   └── CraneImportStrategy
│
├── behaviour_strategy_steps
│   └── SequentialBehaviourSteps
│       ├── ProcessCraneBehaviour
│       └── ProcessCraneDebrief
│
├── physiology_strategy_steps
│   └── SequentialPhysiologySteps
│       └── no steps
│
├── qc_strategy
│   └── CraneQcStrategy
│
└── saving_strategy
    └── CraneSavingStrategy
```

This is the main benefit of the design: the pipeline skeleton stays the same even when individual pipelines include different combinations of steps.

---

## 12. Progress Log & Decisions

### 2026-07-17

**Decided - TypeVar variance split (not yet applied to code)**

`pipeline.py` had a single shared `BehaviourDataType` TypeVar marked `covariant=True`, but it is used in two different roles across the Protocols in that file:

- Output-only role: `ImportBehaviourDataStrategyStep` (`run()` only returns `BehaviourDataType`) - this position is safe as covariant.
- Input role: `ProcessBehaviourDataStrategyStep` and `GetTrialIntervalsStartegy` (`run()` takes it as a parameter) - this position needs invariant.

A single TypeVar object cannot satisfy both, since variance is per-usage, not a global property of the name. Decision: split into two TypeVars, following the `_in`/`_out` naming convention already used elsewhere in the file (`config_in`, `raw_behaviour_data_in`, `biodata_in`):

```python
BehaviourDataType = TypeVar("BehaviourDataType", bound="RawBehaviourData")
BehaviourDataOutType = TypeVar("BehaviourDataOutType", bound="RawBehaviourData", covariant=True)
```

`ImportBehaviourDataStrategyStep` would use `BehaviourDataOutType`; the other two keep the invariant `BehaviourDataType`. **Not yet applied to the code.**

**Found - bug in `ProcessCraneDebriefBehaviourDataStrategyStep.run()`**

In `crane_debrief_behaviour.py`, `run()` is declared to return `CraneDebriefPipelineOutput` but does:

```python
return CraneDebriefPipelineOutput(config_in.subject_id).append_dataframe(
    raw_behaviour_data_in.raw_behav_df, {}
)
```

`PipelineOutputData.append_dataframe()` mutates `self.subject_df_out` in place and returns `None` (see `output_data.py`), so this method actually returns `None` at runtime despite its type signature. **Not yet fixed** - fix is on hold pending the consistency decision below, since fixing it by hand now would be inconsistent with whatever convention gets picked next.

**Found - processing status does not report per-strategy (not yet fixed)**

`PipelineStatus` in `processing_status.py` only tracks stage-level outcomes (`data_in`, `behaviour`, `intervals`, `physiology`). When a `Sequential*Steps` container runs multiple strategy steps, a failure in any one step only shows up as a single stage-level status - there is no way to tell which individual strategy within the sequence succeeded, was skipped, or failed. This needs to be fixed, likely by tracking status per-step (e.g. keyed by step/class) rather than only per-stage.

**Open decision - mutate-in-place vs. return-new-instance consistency**

The bug above surfaced a broader inconsistency in `PipelineOutputData` (`output_data.py`): `append_dataframe()` mutates and returns `None`, while `merge()` builds and returns a new instance (though it still calls `append_dataframe` internally for the mutation). This mismatch is what caused the bug - the debrief step assumed fluent/chained behaviour that `append_dataframe` does not provide.

Two options under consideration, not yet decided:

1. **Fluent style** - mutating methods return `self`, enabling `Output(id).append_dataframe(...)`. Smaller diff given existing call patterns, but makes mutation less visually obvious.
2. **Void style** - mutating methods stay `-> None`, always require a separate variable before use. More explicit, but more verbose at call sites (`merge` in particular).

---

## 13. Outstanding TODOs (from codebase, collected 2026-07-17)

This is a snapshot of existing `# TODO` comments across `src/mooi_toolbox`, grouped by file, for planning which ones the pipeline refactor should resolve along the way.

**`processing/pipeline.py`**
- Line 12: This could potentially form part of pipeline as a class override?
- Line 98: Make the Sequentials unmodifiable i.e. you can inherit from them.

**`processing/output_data.py`**
- Line 30: Fix that on init it inits already an empty participant output data using config.

**`processing/crane_pipeline.py`**
- Line 76: Unlikely to be unique!
- Line 84: Might be redundant as the physiology is less uniquely specified.
- Line 88: This schema can be split into behaviour/debrief and physiology types.
- Line 152: This needs a classmethod to avoid future errors when implementing pipeline.

**`processing/crane_debrief_behaviour.py`**
- Line 26: More checks possible here.
- Line 90: Fix this as it is likely out of scope.

**`processing/crane_behaviour.py`**
- Line 12: convert to tuple.
- Line 200: See if using bids might simplify things long run.
- Line 254: Create strategy.

**`processing/behaviour.py`**
- Line 16: This is very messy. Not sure if half of these functions arent redundant!
- Line 52: Decide what to do when multiple csv files are found.

**`processing/processing_status.py`**
- Line 18: Split data_in into behav data, physiology data etc.

**`processing/crane_trial_intervals.py`**
- Line 47: Improve! This needs to update with a partial.
- Line 98: Needs to be generalized.
- Line 164: Make more robust.

**`processing/trial_intervals.py`**
- Line 87: This should not be hardset to the platform.

**`processing/foh_target_behaviour.py`**
- Line 13: Consider logging what is dropped in the na below.
- Line 14: Examine a better way of checking the hdr.
- Line 41: BUG?
- Line 58: This should be removed.

**`processing/ecg.py`**
- Line 15: nk has several warnings that will hopefully be addressed at update.
- Line 26: Combine all these outputs together... maybe a dictionary?

**`processing/long_walk_pipeline.py`**
- Line 51: Make less of a messy pipeline! Fix Crane as well to be less messy!

**`processing/input_data.py`**
- Line 3: Dataclass can be used to also look for the variables and generate errors.

**`cli/vrlab_crane_qc.py`**
- Line 19: Add summary data processing here.

**`cli/check_mobi_xdf.py`**
- Line 24: Show missing streams.

**`cli/vrlab_crane_process.py`**
- Line 50: fix str to path.
- Line 62: Fix fn to path.
- Line 114: Do data labels for SPSS out.
