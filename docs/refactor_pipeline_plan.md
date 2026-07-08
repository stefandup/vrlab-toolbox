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
