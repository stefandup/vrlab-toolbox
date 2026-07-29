# Design Patterns

A **design pattern** is a named, reusable solution to a coding problem that
keeps coming up — a shared vocabulary, not special syntax or a library you
import. Almost all the pattern names used in Python (and most other
object-oriented languages) trace back to one book: *Design Patterns:
Elements of Reusable Object-Oriented Software* by Erich Gamma, Richard Helm,
Ralph Johnson & John Vlissides (1994) — often just called "the Gang of
Four" or "GoF" book.

[Pipeline Concepts](pipeline-concepts.md) gave the short version with a toy
example. This page goes deeper, with real code from this repository.

## Template Method Pattern

**Idea:** fix the *order* steps happen in; let each individual step's
behaviour vary.

`PipelineTemplate` (`processing/pipeline.py`) is built around one `run()`
method whose overall shape never changes:

```python
class PipelineTemplate:
    def __init__(
        self,
        find_participant_strategy_step,
        sequential_physiology_import_steps,
        sequential_behaviour_data_import_steps,
        sequential_behaviour_processing_steps,
        get_intervals_strategy,
        sequential_physiology_processing_steps,
    ) -> None:
        self.find_participant_strategy_step = find_participant_strategy_step
        self.sequential_physiology_import_steps = sequential_physiology_import_steps
        self.sequential_behaviour_data_import_steps = sequential_behaviour_data_import_steps
        self.sequential_behaviour_processing_steps = sequential_behaviour_processing_steps
        self.sequential_physiology_steps = sequential_physiology_processing_steps
        self.get_interval_strategy = get_intervals_strategy

    def run(self, participant_id_in, data_folder_in, output_folder_in=None):
        participant_config = self.find_participant_strategy_step.run(...)
        # ... import behaviour, process behaviour, import physiology,
        #     build intervals, process physiology, combine, save — always
        #     in this order, for every experiment.
```

The order (find files → import behaviour → process behaviour → import
physiology → …) is fixed by this one method. What actually happens at each
step is supplied from *outside* — six objects passed into `__init__`. That's
the next pattern.

## Strategy

**Idea:** a small, interchangeable piece of behaviour that follows a shared
contract, so it can be swapped without changing the code that calls it.

`pipeline.py` defines each contract as a `typing.Protocol`, e.g.:

```python
class ImportBehaviourDataStrategyStep(Protocol[BehaviourDataType]):
    behaviour_output_type: type[BehaviourDataType]

    def run(self, config_in: ParticipantConfig) -> BehaviourDataType: ...
```

!!! note "Going further"
    `Protocol` means **structural** typing: a class satisfies this contract
    just by *having* a matching `run()` method and attribute — it doesn't
    need to inherit from `ImportBehaviourDataStrategyStep` at all. This is
    Python's own spin on Strategy: the GoF book assumes languages where you
    inherit from a shared interface; Python can check the shape instead
    ("if it has `run()`, it fits").

Here's a real strategy that satisfies a similar contract, unmodified,
from `crane_pipeline.py`:

```python
class FindCraneParticipantFilesStrategyStep:
    physiology_data_type = BiopacDataImportStartegy.input_data_file_format
    behaviour_data_types = [
        ProcessCraneBehaviourDataStrategyStep.input_data_type,
        ProcessCraneDebriefBehaviourDataStrategyStep.input_data_type,
    ]

    def run(self, participant_id_in, data_folder_in, output_folder_in=None):
        return ParticipantConfig.from_physiology_data(
            id_in=participant_id_in,
            physiology_data_type_in=self.physiology_data_type,
            data_folder_in=data_folder_in,
            behaviour_data_types_in=self.behaviour_data_types,
            output_folder_in=output_folder_in,
        )
```

`PipelineTemplate` calls `.run()` on whatever it's given here — it never
needs to know this specific class exists.

### Try it yourself: run a single strategy directly

Because every strategy step is just an object with a `run()` method, you
can call any one of them on its own — no `PipelineTemplate` involved —
useful for exploring or debugging one stage in isolation. This is exactly
how `tests/test_crane_pipeline.py` does it:

```python
from pathlib import Path
from mooi_toolbox.processing.crane_pipeline import FindCraneParticipantFilesStrategyStep

data_folder = Path("crane_data")
participant_config = FindCraneParticipantFilesStrategyStep().run("00020", data_folder)
```

`participant_config` is a `ParticipantConfig` — the input contract from
the [next section](#input-and-output-contracts) — ready to be passed into
any other strategy step.

### Required vs. optional data: splitting a Strategy Protocol in two

`pipeline.py` actually defines *two* Protocols for processing behaviour
data — `ProcessBehaviourDataStrategyStep` and
`ProcessBehaviourDataWithIntervalsStrategyStep` — rather than one Protocol
whose `run()` takes `trial_intervals_in: TrialIntervals | None`:

```python
class ProcessBehaviourDataStrategyStep(Protocol[BehaviourDataType]):
    input_data_type: type[BehaviourDataType]

    def run(
        self, config_in: ParticipantConfig, raw_behaviour_data_in: BehaviourDataType
    ) -> PipelineOutputData: ...


class ProcessBehaviourDataWithIntervalsStrategyStep(Protocol[BehaviourDataType]):
    input_data_type: type[BehaviourDataType]

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: BehaviourDataType,
        trial_intervals_in: TrialIntervals,
    ) -> PipelineOutputData: ...
```

A single Protocol with an `Optional` parameter would work at runtime, but
it pushes a `None`-check into every implementation that actually needs
intervals, and lets a step that *requires* intervals be built and called
without them — the mistake only surfaces when `run()` executes, not when
the type checker looks at it.

Splitting the Protocol instead makes "needs intervals" part of the type:

- **`ProcessBehaviourDataStrategyStep`** — never touches trial intervals
  (e.g. a step that summarises raw survey answers as a whole).
- **`ProcessBehaviourDataWithIntervalsStrategyStep`** — takes a *required*
  `trial_intervals_in: TrialIntervals` (e.g. a step that slices behaviour
  data into per-trial windows). There is no valid way to call one of these
  without real intervals, so nothing downstream has to defend against a
  missing value.

Restaurant analogy: a `PlateStarter` step that just plates a starter has
no use for a table's seating time; a `ServeMainCourse` step that must be
timed against the table being seated should require
`seating_time: datetime`, not `datetime | None` with an "oh, it's `None`,
skip" branch copy-pasted into every course that needs timing.

!!! note "Open gap"
    `SequentialBehaviourProcessingSteps.run()` currently only iterates
    `self.steps`, not `self.steps_with_trial_intervals` — so right now
    `ProcessBehaviourDataWithIntervalsStrategyStep` is defined but not yet
    wired into the pipeline run loop.

## Composite: the `Sequential*Steps` classes

**Idea:** let a *group* of objects be used the same way as a single object.

Sometimes one stage needs more than one strategy step — Crane imports both
crane-task behaviour *and* debrief behaviour, for instance. Rather than
`PipelineTemplate` having to loop over a list itself (and know how to
handle each item's success/failure), that looping is wrapped in its own
class that exposes the *same* `run()` shape as a single strategy:

```python
@dataclass
class SequentialBehaviourImportSteps:
    raw_behaviour_data_Store: RawBehaviourDataStore = field(default_factory=RawBehaviourDataStore)
    steps: Sequence[ImportBehaviourDataStrategyStep] = field(default_factory=list)

    def run(self, config_in: ParticipantConfig):
        pipeline_status = PipelineStatus()
        for step in self.steps:
            try:
                pipeline_raw_behav_data = step.run(config_in=config_in)
                self.raw_behaviour_data_Store.add(pipeline_raw_behav_data)
                pipeline_status.set(step.behaviour_output_type, ProcessingStatus.OK)
            except (ValueError, FileNotFoundError) as e:
                pipeline_status.set(step.behaviour_output_type, ProcessingStatus.ERROR)
        return (self.raw_behaviour_data_Store, pipeline_status)
```

`PipelineTemplate.run()` calls `sequential_behaviour_data_import_steps.run(...)`
without caring whether it wraps one step or five — that's the point of
Composite: a *group* of strategies, itself shaped like a single strategy.

This is also what keeps `PipelineTemplate` general-purpose rather than
Crane-specific. There are four of these `Sequential*Steps` classes in
`pipeline.py` — one per stage that might need more than one strategy:

| Class | Wraps a list of... |
| --- | --- |
| `SequentialBehaviourImportSteps` | `ImportBehaviourDataStrategyStep` |
| `SequentialBehaviourProcessingSteps` | `ProcessBehaviourDataStrategyStep` |
| `SequentialPhysiolgyImportSteps` | `ImportBioDataStrategyStep` |
| `SequentialPhysiologyProcessingSteps` | `ProcessPhysiologyDataStrategyStep` |

Crane happens to pass **two** steps into `SequentialBehaviourImportSteps`
(crane behaviour + debrief) but only **one** into
`SequentialPhysiolgyImportSteps` (Biopac). `PipelineTemplate` doesn't need
an `if` statement anywhere to handle that difference — both cases look
identical from its point of view: "a thing with a `run()` method." A future
experiment that needs three physiology import steps instead of one wouldn't
need any change to `PipelineTemplate` either — just a longer `steps=[...]`
list.

## Input and output contracts

A **contract** here just means: a fixed shape of data that every step
agrees to accept and return, so steps can be swapped, chained, and combined
without knowing about each other's internals. Three classes carry these
contracts through the whole pipeline:

- **`ParticipantConfig`** (`input_data.py`) — the universal *input*. Every
  strategy step's `run()` takes this (or data derived from it). See
  [Pipeline Rules](pipeline-rules.md) for what goes into building one.
- **`RawBioData`** (`biodata.py`) / **`RawBehaviourData`** and friends
  (`behaviour.py`) — the *intermediate* contract between import steps and
  processing steps. Whatever format the source file was in (`.mat`, `.csv`,
  `.xdf`, …), an import step must hand back something shaped like this, so
  a processing step never needs to know or care which importer produced it.
- **`PipelineOutputData`** (`output_data.py`) — the universal *output*.
  Every processing step returns one of these, however different their
  actual computations are (behaviour scoring vs. EDA peak-counting look
  nothing alike internally).

`RawBioData` enforces its contract at *construction time*, not just via a
type hint — it's validated with a [Pandera](https://pandera.readthedocs.io/)
schema the moment it's built:

```python
@dataclass(frozen=True)
class RawBioData:
    raw_data: dict[str, pd.DataFrame] = field(default_factory=dict)

    def __post_init__(self):
        validated_data: dict[str, pd.DataFrame] = {}
        for label, df in self.raw_data.items():
            validated_data[label] = raw_bio_data_schema.validate(df)
        object.__setattr__(self, "raw_data", validated_data)
```

If an import step tries to hand back data that doesn't fit the contract
(e.g. missing a `time_stamps` column), this raises immediately — the
contract violation is caught right where the bad data was produced, not
somewhere downstream where it'd be harder to trace.

`raw_bio_data_schema` is a **[Pandera](https://pandera.readthedocs.io/)**
schema — Pandera is a library for declaring what shape a `pandas`
DataFrame should have (which columns, what type, nullable or not, custom
checks) and then checking real data against that declaration with
`schema.validate(df)`, which raises a clear, specific error if the data
doesn't match. This project uses it wherever a dataframe crosses a
boundary — after loading raw data, before/after processing, on the final
output — rather than trusting every dataframe implicitly and finding out
something was wrong three functions later, from a confusing error. Other
schemas you'll run into: `build_base_pipeline_output_schema` (below),
`build_crane_participant_output_schema` (`crane_pipeline.py`, the full
Crane output row), and `build_eda_physiology_output_schema` (`eda.py`).

`PipelineOutputData` carries the matching *output* contract — always a
one-row `subject_df_out` DataFrame, a `status` (`PipelineStatus`), and any
QC `figure_data_out`:

```python
@dataclass
class PipelineOutputData:
    subject_id: str
    subject_df_out: pd.DataFrame = field(init=False)
    figure_data_out: dict[str, Figure] = field(default_factory=dict, init=False)
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_pipeline_output_schema)
    status: PipelineStatus = field(default_factory=PipelineStatus, init=False)

    def merge(self, other: "PipelineOutputData") -> "PipelineOutputData":
        ...  # combine two steps' output into one row, one status, one set of figures
```

Because every processing step returns the *same shape* of object, `.merge()`
can combine a behaviour step's output with a physiology step's output
without either step knowing the other exists — that's the contract doing
its job.

### One participant at a time

Easy to misread `.merge()` as combining *multiple participants'* rows
together — it doesn't. `PipelineTemplate.run()` (`pipeline.py`), and every
strategy step, `ParticipantConfig`, and `PipelineOutputData` in this whole
page, all operate on **exactly one participant, one row, per call**.
`.merge()` combines different *steps'* output columns for that *same*
participant — behaviour columns next to physiology columns, side by side —
not different participants' rows stacked on top of each other. The actual
`append_dataframe` method `.merge()` calls underneath is explicit about
this, right down to the axis it concatenates on and a check that enforces
it:

```python
combined_df = pd.concat([existing_df_reset, data_in_reset], axis=1)  # side by side, same row
...
if not len(combined_df) == 1:
    raise ValueError("Output data must contain exactly one row.")
```

Combining *multiple participants'* rows into one file happens **only at
the CLI level**, after `run_pipeline()` has already returned — e.g.
`vrlab_crane_process.py` collects each participant's one-row
`subject_df_out` in a list across its loop, then:

```python
participant_df_out = pd.concat(out_file_parts, axis=0)  # stacked, one row per participant
```

Same `pd.concat` function, opposite `axis` — worth knowing the difference:
`axis=1` glues columns together side by side (what `.merge()` does, within
one participant); `axis=0` stacks rows on top of each other (what the CLI
does, across participants). See
[Getting Started](getting-started.md#what-you-get-out) for where that
combined file actually comes from.

### Try it yourself: chain strategies through the contracts

Each strategy step's output is the next one's input — that's the contract
doing its job. Run three real strategies back to back, feeding one's output
into the next, no `PipelineTemplate` involved:

```python
from mooi_toolbox.processing.biopac import BiopacDataImportStartegy
from mooi_toolbox.processing.crane_behaviour import ImportCraneBehaviourDataStrategyStep
from mooi_toolbox.processing.crane_trial_intervals import CraneGetTrialIntervalStrategyStep

raw_bio_data = BiopacDataImportStartegy().run(participant_config)
raw_behav_data = ImportCraneBehaviourDataStrategyStep().run(participant_config)

trial_intervals, interval_figure, interval_status = (
    CraneGetTrialIntervalStrategyStep().run(raw_bio_data, raw_behav_data)
)
```

`raw_bio_data` and `raw_behav_data` are `RawBioData` / `RawBehaviourData` —
the intermediate contract above — which is exactly why
`CraneGetTrialIntervalStrategyStep` can accept them without knowing which
concrete importer produced either one.

## Going further

- *Design Patterns: Elements of Reusable Object-Oriented Software*, Gamma,
  Helm, Johnson & Vlissides (1994) — the original source for all three
  names above.
- Real Python's [design patterns tutorials](https://realpython.com/tutorials/design-patterns/)
  cover the same patterns with smaller, runnable examples.
- **Read `processing/pipeline.py` yourself.** Every `Protocol` (a contract),
  every `Sequential*Steps` class (a composite), and `PipelineTemplate`
  itself (the template) live in that one file. Once you can point at the
  lines implementing each pattern above, you've got the architecture.
- On the Python side specifically: `Protocol` and the dunder-method-based
  contracts Python uses throughout (`__len__`, `__eq__`, `__iter__`, …) are
  covered in depth in *Fluent Python* by Luciano Ramalho (O'Reilly). There's
  a live example of exactly this in this codebase: `TrialIntervals`
  (`trial_intervals.py`) already has `__len__` (so `len(my_intervals)`
  works — see [Interval QC Plot](interval-qc.md#what-is-a-trial-interval)),
  and gets `__eq__` for free from `@dataclass`. What's still missing —
  tracked as an open TODO — is `__iter__`/`__getitem__`, so you still have
  to write `my_intervals.intervals.items()` to loop over one, rather than
  `for name, (start, end) in my_intervals:` directly. A real spot where
  that book's material on the Python data model would apply directly.

## Write your own pipeline

`crane_pipeline.py`'s `run_pipeline()` is the template to copy for a new
experiment: build your `Sequential*Steps` containers out of your own
strategy steps, hand them to `PipelineTemplate`, call `.run()`.

```python
from mooi_toolbox.processing import pipeline

def run_pipeline(participant_id_in, data_folder_in, output_folder_in=None):
    my_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=MyFindParticipantFilesStep(),
        sequential_physiology_import_steps=pipeline.SequentialPhysiolgyImportSteps(
            steps=[MyPhysiologyImportStep()]
        ),
        sequential_behaviour_data_import_steps=pipeline.SequentialBehaviourImportSteps(
            steps=[MyImportBehaviourStep()]
        ),
        get_intervals_strategy=MyGetTrialIntervalStep(),
        sequential_behaviour_processing_steps=pipeline.SequentialBehaviourProcessingSteps(
            steps=[MyProcessBehaviourStep()]
        ),
        sequential_physiology_processing_steps=pipeline.SequentialPhysiologyProcessingSteps(
            steps=[MyPhysiologyProcessStep()]
        ),
    )
    _, output_data = my_pipeline.run(participant_id_in, data_folder_in, output_folder_in)
    return output_data
```

Every `My...Step()` above just needs to satisfy the matching
[Strategy](#strategy) `Protocol` — right `run()` signature, right contract
type in and out. `PipelineTemplate` itself never changes.

---

**Next: [Testing](testing.md)** — see how these strategy steps get tested
individually.
