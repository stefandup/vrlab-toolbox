# Process Your Data

This is step 2: once your data has been crosschecked (see [FOH
Crosscheck](foh-crosscheck.md), [Crane Crosscheck](crane-crosscheck.md) or
[LongwalkV3 Crosscheck](longwalkv3-crosscheck.md)),
run the processing tool for your experiment. It reads through your
crosschecked data, computes the physiology measures the pipeline is built
to produce, and writes out one combined file ready for statistics — no
manual copying or combining of per-participant results needed.

Every tool works the same basic way: point them at a folder of input data
and a folder for the output, and let them run.

## Crane

```bash
vrlab_crane_process <input_folder> <output_folder>
```

- `input_folder` — searched through for each participant's files. You can
  point it at the top of your data folder; it finds the right files
  wherever they are inside it.
- `output_folder` — where the combined participant-level output files are
  written.

By default it processes **every** participant found under `input_folder`.
To process just one, add `--subject_id`:

```bash
vrlab_crane_process crane_data crane_data/output --subject_id P00018
```

Add `--verbose` for more detailed log output while it runs:

```bash
vrlab_crane_process crane_data crane_data/output --verbose
```

### Crane's output files

Two combined files land in `output_folder`:

```text
vrlab_crane_process_batch_data_out.csv
vrlab_crane_process_batch_data_out.sav
```

(`.sav` is an SPSS file.) When `--subject_id` is used, both filenames are
prefixed with that subject's ID instead. Either file is ready to open
directly in your statistics software — one row per participant, one
column per measure.

## FOH

```bash
vrlab_foh_process <input_folder> <output_folder>
```

Searches `input_folder` recursively for every `.xdf` recording and
processes each one it finds, writing the combined result to
`output_folder`.

Add `--verbose` for more detailed log output while it runs:

```bash
vrlab_foh_process local_lsl_data local_lsl_data/output --verbose
```

### FOH's output files

Two combined files land in `output_folder`:

```text
FOH_process_batch_out.csv
FOH_process_batch_out.sav
```

(`.sav` is an SPSS file.) One row per participant, ready to open directly
in your statistics software.

## LongwalkV3

You can process LongwalkV3 from the results viewer or from a terminal;
both run exactly the same processing.

### From the results viewer (easiest)

1. Open **LongwalkV3 Process Results** from the VR Lab Toolbox launcher
   (or type `vrlab_longwalk3_process_GUI` in a terminal).
2. Next to the **BIDS folder**, click **Browse...** and pick your
   crosschecked LongwalkV3 BIDS folder (the one the
   [crosscheck](longwalkv3-crosscheck.md) works on, not the raw folder).
3. Next to the **output folder**, click **Browse...** and pick an empty
   folder of its own. It can't be inside the BIDS folder.
4. Click **Process BIDS Folder**. A progress bar shows each subject as it
   goes. With **Skip already-processed subjects** ticked (the default),
   only new subjects are processed and everyone else's results are kept.
   Untick it to redo everyone, e.g. after correcting something in the
   crosscheck.

When it's done the viewer shows the results straight away; see
[LongwalkV3 Output Checks](longwalkv3-output.md) for what to look at.

### From a terminal

```bash
vrlab_longwalk3_process <bids_folder> <output_folder>
```

- `bids_folder` — the crosschecked LongwalkV3 BIDS folder.
- `output_folder` — must already exist, and be separate from the BIDS
  folder.

Every subject with a physiology recording is processed, all of their
sessions. Subjects already processed into this output folder are skipped;
add `--rerun` to redo everyone. `--subject_id <text>` only adds a prefix
to the output filenames. Add `--verbose` for more detailed log output.

```bash
vrlab_longwalk3_process longwalkv3_bids longwalkv3_output --rerun
```

### LongwalkV3's output files

In `output_folder`:

```text
vrlab_longwalk3_process_batch_data_out.csv
vrlab_longwalk3_process_batch_data_out.sav
```

(`.sav` is an SPSS file.) There is **one row per participant**, with all
their sessions side by side; every session's columns start with
`ses01_`, `ses02_`, `ses03_`:

| Column | What it holds |
| --- | --- |
| `Subject_ID` | The participant. |
| `Processing_Status` | The worst status across their sessions (see [Output Checks](longwalkv3-output.md#processing-status)). |
| `sesNN_Processing_Status` | That session's own status, per processing step. |
| `sesNN_ThreatLevelMarkerNew2_SCR_per_min` | Skin conductance responses per minute in that session, from threat marker 2 to threat marker 3. One column per threat-marker segment, named after the marker it starts at. |

The SCR columns only cover **consecutive** threat markers: a segment runs
from marker N's trigger to marker N+1's. If a marker is missing from a
recording, the segments either side of it are left out (the log says
which). A marker passed twice counts from its first pass. Other triggers
(NPCs, phone, panic events…) don't split segments; they're shown on the
QC plots only.

Also in `output_folder`: the QC plots for every subject and session (see
[Output Checks](longwalkv3-output.md)), a `logs` folder with a log per
subject, and `processed_subjects.json`, which records who has already been
processed.

---

**Next: [Check Your Output](eda.md)** — step 3, reviewing the QC plots
before you trust the numbers.
