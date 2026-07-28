# Lab Streaming Layer (LSL) & XDF

Everything so far ([Pipeline Rules](pipeline-rules.md), [Interval QC Plot](interval-qc.md),
[EDA & SCRs](eda.md)) used Crane as the example: one Biopac `.mat` file
plus separate behaviour CSVs. FOH recordings work differently — this page
introduces that other path.

!!! note "Work in progress"
    This page documents what exists today. The FOH/LSL code path is
    explicitly rougher than Crane's and is **deferred** — see "Deferred:
    FOH & LongWalk" at the end of [Next Steps](pipeline_next_steps.md#deferred-foh--longwalk).
    Crane's pipeline is being stabilized first; FOH is next.

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
| `processing/foh_pipeline.py` | The FOH experiment's pipeline — the main real caller of the two above. |

!!! note "Going further"
    Per [Code Organization](code-organization.md#inside-src-mooi_toolbox),
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

## A real caller: `run_lsl_pipeline`

From `foh_pipeline.py`, trimmed:

```python
streams = get_and_check_xdf(xdf_fn, verbose=verbose)

streams_to_get = ["OpenSignals", "VR_markers", "VR_trial_events", "FOH_target"]
FOH_dfs = xdf.gather_xdf_data_streams(streams, streams_to_get)

missing_streams = set(streams_to_get) - set(FOH_dfs)
if missing_streams:
    logger.warning(f"Missing streams: {missing_streams}")

if has_missing_requirements(missing_streams, ["VR_markers", "VR_trial_events"]):
    logger.warning("No trial info found in xdf. Cannot create intervals")
else:
    vr_intervals = trial_intervals.create_lsl_trial_intervals(
        FOH_dfs["VR_markers"], FOH_dfs["VR_trial_events"]
    )
```

Notice the shape: load everything available, check what's actually
missing, then proceed with whatever's there — the same "partial data beats
no data" idea as Crane's fallback strategies (see item 5 in
[Next Steps](pipeline_next_steps.md#5-add-a-fallback-for-partialmissing-behaviour-data-using-unlabelled-intervals)),
just handled with plain `if`/`else` here rather than a `fallback_strategy`.

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
  an expected stream list the way `foh_pipeline.py`'s `has_missing_requirements`
  does.
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

---

**Next: [Pipeline Concepts](pipeline-concepts.md)** — back to the
architecture that both the Crane and FOH paths are built on.
