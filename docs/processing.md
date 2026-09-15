# Process Your Data

This is step 2: once your data has been crosschecked (see [FOH
Crosscheck](foh-crosscheck.md) or [Crane Crosscheck](crane-crosscheck.md)),
run the processing tool for your experiment. It reads through your
crosschecked data, computes the physiology measures the pipeline is built
to produce, and writes out one combined file ready for statistics — no
manual copying or combining of per-participant results needed.

Both tools work the same basic way: point them at a folder of input data
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

---

**Next: [Check Your Output](eda.md)** — step 3, reviewing the QC plots
before you trust the numbers.
