# Core Data Classes

[Design Patterns](design-patterns.md) covered the contract *shapes*
(`ParticipantConfig`, `RawBioData`/`RawBehaviourData`, `PipelineOutputData`)
in passing. This page is a closer look at three classes you'll touch
directly while writing or debugging a pipeline: `TrialIntervals`,
`PipelineStatus`, and `PipelineOutputData`.

## Declaring a class (and a child class) — the basics

If classes are still new: a **class** is a blueprint for objects that
bundle data and behaviour together. A **child class** (or "subclass")
reuses everything a parent class already has, and only needs to state
what's *different* — new fields, or a method it wants to replace:

```python
class Dish:
    def __init__(self, name):
        self.name = name

    def describe(self):
        return f"{self.name}"


class Salad(Dish):                    # Salad IS-A Dish — inherits __init__ and describe()
    def __init__(self, name, dressing):
        super().__init__(name)        # reuse the parent's setup
        self.dressing = dressing

    def describe(self):               # override: same method name, different behaviour
        return f"{self.name} with {self.dressing}"
```

`Salad("Greek Salad", "olive oil")` gets `self.name` for free from `Dish`;
it only had to add `self.dressing` and change what `describe()` returns.
Every class below (and every `Protocol` in [Design Patterns](design-patterns.md#strategy))
is a variation on this same idea, written with `@dataclass` instead of a
hand-written `__init__` — see [below](#declaring-fields-default-vs-fielddefault_factory)
for what that changes.

## `TrialIntervals`

A named set of `(start, end)` time pairs for one participant — e.g.
`"Baseline": (0.0, 5.0)`. Produced by a `GetTrialIntervalsStartegy`,
consumed by every processing step that needs to slice data per trial. See
[Interval QC Plot](interval-qc.md#what-is-a-trial-interval) for the full
treatment of what a trial interval means and how it's built.

```python
@dataclass
class TrialIntervals:
    intervals: dict[str, tuple[float, float]] = field(default_factory=dict)

    def __len__(self):
        return len(self.intervals)
```

```python
from mooi_toolbox.processing.trial_intervals import TrialIntervals

intervals = TrialIntervals(intervals={"Baseline": (0.0, 5.0), "Task": (5.0, 65.0)})
len(intervals)          # 2 — via __len__
intervals.intervals     # sorted by start time via __post_init__
```

## `PipelineStatus`

A `type → ProcessingStatus` mapping (`OK`, `PARTIAL`, `CORRECTED`,
`ERROR`, `NOT_RUN`) — one entry per data type the pipeline touched for a
participant. Every `Sequential*Steps.run()` returns one alongside its
data, and `PipelineTemplate.run()` merges them all into a single status
for the participant.

```python
@dataclass
class PipelineStatus:
    status: dict[type, ProcessingStatus] = field(default_factory=dict)

    def set(self, data_type, status: ProcessingStatus):
        self.status[data_type] = status

    def merge(self, other: "PipelineStatus") -> "PipelineStatus":
        ...  # worst status per type wins, across both
```

```python
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.crane_behaviour import RawCraneBehaviourData

status = PipelineStatus()
status.set(RawCraneBehaviourData, ProcessingStatus.OK)
status.get_as_text()   # "RawCraneBehaviourData=ok" — this is what ends up in the output row
```

## `PipelineOutputData` — and why it has child classes

One participant's output: a one-row `subject_df_out` DataFrame, a
`status` (`PipelineStatus`), and any QC `figure_data_out`. Every
processing step returns one; `.merge()` combines two into one, **always
staying one row** — see [One participant at a time](design-patterns.md#one-participant-at-a-time)
for why that invariant matters.

```python
@dataclass
class PipelineOutputData:
    subject_id: str
    subject_df_out: pd.DataFrame = field(init=False)
    figure_data_out: dict[str, Figure] = field(default_factory=dict, init=False)
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_pipeline_output_schema)
    status: PipelineStatus = field(default_factory=PipelineStatus, init=False)

    def validate_participant_output(self) -> pd.DataFrame:
        return self.validation_schema.validate(self.subject_df_out)
```

Every experiment ends up with its own output columns — Crane's row looks
nothing like the Long Walk pipeline's row. Rather than rewrite `.merge()`,
`.append_dataframe()`, and the row-shape rules per experiment, each
experiment defines a **child class** that changes only the one thing that
actually differs — which Pandera schema validates the row:

```python
@dataclass
class CranePipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_crane_participant_output_schema().validate(self.subject_df_out)
```

That's the whole class. `merge()`, `append_dataframe()`, `figure_data_out`,
the one-row rule — all inherited unchanged from `PipelineOutputData`, same
as `Salad` inheriting `Dish.__init__` above. You'll see the same pattern
for `CraneBehaviourOutputData`, `CraneDebriefPipelineOutput`,
`EdaPhysiologyOutputData`, `LongWalkPipelineOutputData`, and
`FohPipelineOutputData` (`foh_pipeline.py`) — one override each, nothing
more, all still exactly one row per subject.

!!! note "Going further"
    `FohPipelineOutputData.validate_participant_output()` currently
    validates against a bare `pa.DataFrameSchema()` — the override exists,
    but `build_foh_participant_output_schema()` hasn't been filled in with
    real columns yet, so validation is a no-op today. Once it is, it'll
    follow the same "build from constants" shape
    `build_crane_participant_output_schema()` already uses. See
    [Lab Streaming](lab-streaming.md) for the rest of FOH's anticipated
    pipeline shape.

## Declaring fields: `= default` vs. `field(default_factory=...)`

All three classes above use `@dataclass`, and all three mix both styles of
default. The difference matters, and Python enforces it rather than just
recommending it:

```python
@dataclass
class Broken:
    intervals: dict[str, tuple[float, float]] = {}     # in-place literal default
```

```
ValueError: mutable default <class 'dict'> for field intervals is not
allowed: use default_factory
```

A plain `= {}` (or `= []`, `= SomeDataclass()`) would mean every instance
starts out *sharing the exact same dict object* — mutate one participant's
`intervals`, and every other `TrialIntervals` ever created without an
explicit value would see the change too. `@dataclass` refuses to let you
write that by accident:

```python
@dataclass
class TrialIntervals:
    intervals: dict[str, tuple[float, float]] = field(default_factory=dict)
```

`field(default_factory=dict)` says "call `dict()` fresh, once per
instance" instead — the fix, not just a longer way to write the same
thing. The same reasoning is why `PipelineOutputData.status` is
`field(default_factory=PipelineStatus, init=False)` rather than
`= PipelineStatus()`: a fresh `PipelineStatus()` per participant, not one
`PipelineStatus` silently shared across every `PipelineOutputData` ever
built.

Plain, *immutable* defaults (`str`, `int`, `float`, `bool`, `None`) don't
have this problem — they can't be mutated in place, so there's nothing to
accidentally share. That's why `subject_id: str` above never needs
`field(...)` at all; only the mutable ones do.

---

**See also:** [Design Patterns](design-patterns.md) for the `Protocol`
contracts these classes flow through, and [Data Stores](data-stores.md)
for where `RawBioData`/`RawBehaviourData` instances (a related but
separate pair of classes) get held between import and processing.
