# Lab Streaming Layer (LSL) & XDF

Everything so far ([Pipeline Rules](pipeline-rules.md), [Interval QC Plot](interval-qc.md),
[EDA & SCRs](eda.md)) used Crane as the example: one Biopac `.mat` file
plus separate behaviour CSVs. FOH recordings work differently — this page
covers that other path: the same `PipelineTemplate` architecture from
[Design Patterns](design-patterns.md), wired up to LSL/`.xdf` data instead
of a Biopac `.mat` file.

!!! note "Where FOH currently stands"
    `foh_pipeline.py`'s `run_pipeline()` already builds the same
    `PipelineTemplate` shape as Crane's — this page documents that target
    shape, not a hypothetical future one. Target behaviour data is now
    wired into the import and processing steps (see below); the
    participant-level output schema (`build_foh_participant_output_schema()`)
    is still the one piece left as a no-op. See item 21 in
    [Next Steps](pipeline_next_steps.md#21-foh-pipeline-exception-handling-parity-with-crane-trial-interval-config-migration)
    for the current punch list. The `@deprecated` `run_lsl_pipeline`
    function is the old, pre-refactor path — `mobi_foh_batch_process` has
    already moved off it onto `run_pipeline()`; `mobi_foh_process` (the
    single-file CLI) hasn't yet. It's kept only until both CLIs are off it,
    then deleted (see that same item).

## What is LSL, and what's a `.xdf` file?

**Lab Streaming Layer (LSL)** is middleware used during a live recording
session to synchronize several independent data sources — VR event
markers, physiology, EEG, trial/task events — onto one shared clock, even
though they come from different software and hardware. Each data source is
called a **stream**.

**`.xdf`** is the file format LSL recordings get saved to. One `.xdf` file
contains *all* the streams from a session bundled together, each tagged
with its own name, type, channel info, and timestamps already aligned to
that shared clock. This is different from Crane, where physiology and
behaviour arrive as separate files that then need to be matched up after
the fact (see [Pipeline Rules](pipeline-rules.md)) — with `.xdf`, that
alignment is mostly already done by the time you load the file.

## Where this code lives

| File | Role |
| --- | --- |
| `read_mobi_xdf/xdf_io.py` | Low-level helpers: pull one named stream out of a loaded `.xdf` file and turn it into a labelled `pandas` DataFrame. |
| `cli/check_mobi_xdf.py` | Loads a `.xdf` file (via the third-party [`pyxdf`](https://github.com/xdf-modules/pyxdf) library) and reports which streams it actually contains. |
| `processing/lsl.py` | The LSL/`.xdf` counterpart to `biopac.py`: `FohLslPhysiologyDataImportStrategy` (physiology import), plus `gather_xdf_data_streams` and friends. |
| `processing/foh_config.py` | Typed trial-interval definitions (`LslEventSpecification`, `LslIntervalSpecifications`) — which VR/LSL event marks the start and end of each interval FOH cares about (`baseline`, `stress`, `recovery`). |
| `processing/foh_pipeline.py` | The FOH experiment's pipeline — wires the strategy steps below into the shared `PipelineTemplate`, the same way `crane_pipeline.py` does for Crane. |

!!! note "Going further"
    Per [Code Organization](code-organization.md#inside-src-vrlab_toolbox),
    `read_mobi_xdf/` is planned to move into `processing/`, living next to
    `biopac.py` — both are just physiology-file loaders for different
    formats, and don't need to live in a separate top-level folder.

## Pulling one stream out of a `.xdf` file

Real code, `xdf_io.py`:

```python
def extract_single_stream(streams: list, stream_name: str) -> tuple[pd.DataFrame, dict]:
    """Extract the time series and time stamps from a specified stream in xdf data."""
    for s in streams:
        if s['info']['name'][0] == stream_name:
            single_stream = s
            single_stream_time_series = np.array(single_stream['time_series'])
            single_stream_time_stamps = np.array(single_stream['time_stamps'])
            single_stream_df = pd.DataFrame(single_stream_time_series)
            single_stream_df["time_stamps"] = single_stream_time_stamps
            return single_stream_df, single_stream
    raise xdfIOException(f"Could not find XDF stream {stream_name!r}")
```

`streams` is the list `pyxdf.load_xdf(...)` returns — one dict per stream,
holding its raw metadata plus `time_series`/`time_stamps` arrays. This
function just finds the one stream matching `stream_name` (e.g.
`"VR_markers"`) and reshapes it into a DataFrame.

`gather_xdf_data_streams` wraps this to grab several named streams at once,
and — importantly — **skips a missing stream with a warning instead of
crashing the whole load**, since not every stream is guaranteed to be
present in every recording session.

## Finding a participant's files: `ParticipantConfig.from_lsl_data`

Crane's file-finding rules (see [Pipeline Rules](pipeline-rules.md)) are
built on `ParticipantConfig.from_physiology_data`, which matches a
physiology file *and* one or more separate behaviour files by filename.
FOH doesn't need that — everything (physiology, VR markers, trial events,
target data) lives inside the *same* `.xdf` file — so it has its own
classmethod, `ParticipantConfig.from_lsl_data` (`input_data.py`), used by
FOH's own find-files strategy:

```python
class FindFohParticipantFilesStrategyStep:
    physiology_data_type = FohLslPhysiologyDataImportStrategy.input_data_file_format

    def run(
        self, participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
    ) -> ParticipantConfig:

        return ParticipantConfig.from_lsl_data(
            id_in=participant_id_in,
            physiology_data_type_in=self.physiology_data_type,
            data_folder_in=data_folder_in,
            output_folder_in=output_folder_in,
        )
```

Same `Strategy` contract as Crane's `FindCraneParticipantFilesStrategyStep`
(see [Design Patterns](design-patterns.md#strategy)) — `PipelineTemplate`
calls `.run()` on whichever one it's given, without needing to know Crane's
file-matching and FOH's file-matching work differently under the hood.

A couple of matching rules specific to `from_lsl_data`, worth knowing if
you're troubleshooting a missing participant:

- it globs for `*{id}*.xdf` under `data_folder_in` and only keeps files
  ending in `eeg.xdf` — anything else is logged and skipped as "an old run";
- if more than one match remains, it picks the **last** one (sorted by
  `rglob`'s own order) rather than Crane's "first match wins" rule — worth
  double-checking against your actual filenames if a participant seems to
  pick up the wrong session.

## Importing physiology data: `FohLslPhysiologyDataImportStrategy`

The LSL counterpart to `BiopacDataImportStartegy` (`biopac.py`). Same
`ImportBioDataStrategyStep` contract, same `RawBioData` output type — just
reading streams out of an `.xdf` file instead of channels out of a `.mat`
file:

```python
class FohLslPhysiologyDataImportStrategy:
    input_data_file_format = PhysiologyFileFormat.LSL
    output_data_type = RawBioData

    def run(self, config_in: ParticipantConfig) -> RawBioData:
        streams_to_get = ["OpenSignals", "VR_markers"]
        streams, _ = pyxdf.load_xdf(config_in.physiology_fn)
        selected_lsl_physiology_streams_dfs = gather_xdf_data_streams(streams, streams_to_get)

        if has_missing_requirements(missing_streams, ["OpenSignals"]):
            logger.warning(f"Missing physiology data - {missing_streams}")
            return RawBioData()

        df_dict_out = {
            "EDA": selected_lsl_physiology_streams_dfs["OpenSignals"].copy(),
            "ECG": selected_lsl_physiology_streams_dfs["OpenSignals"].copy(),
        }
        if not has_missing_requirements(missing_streams, ["VR_markers"]):
            df_dict_out["VR_markers"] = selected_lsl_physiology_streams_dfs["VR_markers"].copy()

        ...
        return RawBioData(raw_data=df_dict_out)
```

Only `OpenSignals` is actually required — a missing `VR_markers` stream no
longer fails the whole import, it's just left out of `raw_data`. The single
`OpenSignals` stream is split into separate `"EDA"`/`"ECG"` entries (each
with the other's columns dropped), rather than handed back as one combined
`"OpenSignals"` entry — that split is what lets `ecg.py`'s processing read a
plain `EDA`/`ECG`-keyed `RawBioData`, the same shape Crane's Biopac import
produces.

Because `RawBioData` is the same contract Crane's Biopac import returns
(see [Design Patterns](design-patterns.md#input-and-output-contracts)),
everything downstream of physiology import — EDA processing, QC plotting —
doesn't need to know or care whether the data came from a `.mat` file or an
`.xdf` stream.

## Building trial intervals from LSL events: `foh_config.py`

Crane finds trial intervals from trigger-voltage crossings in the physiology
signal itself (`trial_intervals.py`). FOH instead has explicit VR/LSL
*events* marking when each interval starts and ends, declared as typed
constants in `foh_config.py`:

```python
BASELINE_START_SPEC = LslEventSpecification(stream="VR_markers", column="Markers", event=10)
BASELINE_START_FALLBACK_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="RaiseSafetyPlatform", offset_seconds=-300
)
BASELINE_END_SPEC = LslEventSpecification(
    stream="VR_trial_events", column="VR_trial", event="RaiseSafetyPlatform"
)

BASELINE_INTERVAL = LslIntervalSpecifications(
    start=BASELINE_START_SPEC, end=BASELINE_END_SPEC, start_fallback=BASELINE_START_FALLBACK_SPEC
)

FOH_TRIAL_INTERVALS: dict[str, LslIntervalSpecifications] = {
    "baseline": BASELINE_INTERVAL,
    "stress": STRESS_INTERVAL,
    "recovery": RECOVERY_INTERVAL,
}
```

Reading this: `baseline` normally starts at VR marker `10` on the
`VR_markers` stream; if that marker is missing, fall back to 300 seconds
*before* `RaiseSafetyPlatform` fires on `VR_trial_events` instead
(`offset_seconds=-300`). `stream` is typed as
`Literal["VR_markers", "VR_trial_events"]`, so a typo'd stream name is a
type-checker error rather than a runtime `KeyError`.

`FohGetTrialIntervalStrategyStep.run()` (`foh_trial_intervals.py`) walks
`FOH_TRIAL_INTERVALS`, resolving each `start`/`end` spec (falling back where
one is configured) into an actual timestamp via
`get_lsl_event_time_with_fallback` (`trial_intervals.py`), and returns a
`TrialIntervals` — the same contract Crane's interval strategy returns.

## Physiology processing is shared with Crane, unchanged

Once `RawBioData` and `TrialIntervals` exist, FOH doesn't need its own EDA
processing step — `foh_pipeline.py` wires in the exact same
`ProcessEdaPhysiologyDataStrategyStep` class `crane_pipeline.py` uses:

```python
process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
    steps=[ProcessEdaPhysiologyDataStrategyStep()]
)
```

This is the Strategy pattern paying off directly (see
[Design Patterns](design-patterns.md#strategy)): the same processing code
runs against physiology data from two differently-shaped source files,
because both import steps agree on handing back a `RawBioData`.

## Try it yourself: chain FOH strategies through the contracts

Same idea as [Design Patterns' Crane example](design-patterns.md#try-it-yourself-chain-strategies-through-the-contracts),
run for FOH instead — each strategy step's output feeds the next one's
input, no `PipelineTemplate` involved:

```python
from pathlib import Path

from vrlab_toolbox.processing.foh_behaviour import ImportFohBehaviourDataStrategyStep
from vrlab_toolbox.processing.foh_pipeline import FindFohParticipantFilesStrategyStep
from vrlab_toolbox.processing.foh_trial_intervals import FohGetTrialIntervalStrategyStep
from vrlab_toolbox.processing.lsl import FohLslPhysiologyDataImportStrategy

data_folder = Path("foh_data")
participant_config = FindFohParticipantFilesStrategyStep().run("P001", data_folder)

raw_bio_data = FohLslPhysiologyDataImportStrategy().run(participant_config)
raw_behav_data = ImportFohBehaviourDataStrategyStep().run(config_in=participant_config)

trial_intervals, interval_figure, interval_status = FohGetTrialIntervalStrategyStep().run(
    raw_bio_data, raw_behav_data
)
```

`raw_bio_data` is a `RawBioData` — same type Crane's chain produces, just
built from `.xdf` streams. `trial_intervals` is the same `TrialIntervals`
type Crane's `CraneGetTrialIntervalStrategyStep` returns, just built from
`LslEventSpecification`s instead of Crane's trigger-voltage logic.

## Inspecting a `.xdf` file yourself

Before writing any processing code against a new recording, check what
streams it actually contains:

```bash
mobi_check_xdf path/to/file.xdf --verbose
```

This calls `check_mobi_xdf()` (`cli/check_mobi_xdf.py`), which loads the
file with `pyxdf.load_xdf` and prints each stream's name, type, channel
count, sampling rate, and sample count.

## Known rough edges

- `cli/check_mobi_xdf.py` has an open `# TODO: Show missing streams` — it
  loads and reports what's *present*, but doesn't yet compare that against
  an expected stream list.
- `xdf_io.py` still uses bare `print()` in a couple of places instead of
  `logging` (unlike the rest of this codebase — see
  [Golden Rules](golden-rules.md)).
- `xdf_io.py`'s `get_start_time` isn't called anywhere else in the
  codebase, and looks like it would raise `AttributeError` if it were:
  it calls `datetime.fromisoformat(...)`, but the file only does
  `import datetime` (the module) rather than `from datetime import datetime`
  (the class) — `fromisoformat` exists on the class, not the module. Left
  here as an example of exactly the kind of small, easy-to-miss bug that
  hides in unused code.
- `processing/trial_intervals.py:87` is hardset to one platform rather than
  detecting it — see the deferred items in
  [Next Steps](pipeline_next_steps.md#deferred-foh--longwalk).
- `ImportFohTargetBehaviourDataStrategyStep` is now wired into
  `foh_pipeline.py`'s import steps, and
  `ProcessFohTargetDataWithIntervalsStrategyStep` returns real target output
  (`FohTargetBehaviourOutputData`) instead of discarding it. What's still
  the *target* shape rather than finished: `build_foh_participant_output_schema()`
  is still a no-op, and `mobi_foh_process` (unlike `mobi_foh_batch_process`)
  hasn't moved off the deprecated `run_lsl_pipeline` path yet. Full punch
  list: item 21 in
  [Next Steps](pipeline_next_steps.md#21-foh-pipeline-exception-handling-parity-with-crane-trial-interval-config-migration).

---

**Next: [Pipeline Concepts](pipeline-concepts.md)** — back to the
architecture that both the Crane and FOH paths are built on.
