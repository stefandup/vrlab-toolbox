# Getting Started

This page gets the toolbox installed and walks through running one real
pipeline — the Crane pipeline — end to end, as a worked example. The other
command-line tools (FOH and friends) follow the same overall shape; see
[Other pipelines](#other-pipelines) below.

## 1. Install

From the workspace root, with your virtual environment active:

```bash
pip install -e .
```

This installs the toolbox itself in **editable mode** — code changes are
picked up immediately, no reinstalling needed — and pulls in everything
listed in `requirements.txt` along with it (`pyproject.toml` points at that
file as the dependency list). It's also what makes the command-line tools
below, and `import mooi_toolbox` in scripts, available in your environment.

## 2. Run the Crane pipeline

The Crane command is `vrlab_crane_process`:

```bash
vrlab_crane_process <input_folder> <output_folder>
```

- `input_folder` — searched **recursively** for each participant's Biopac
  `.mat` file (matching `*_CraneOut.mat`) *and* their behaviour/debrief CSV
  files. Both file types can live anywhere under this one folder.
- `output_folder` — where the combined participant-level output files are
  written.

Under the hood, the actual pipeline (`run_pipeline()`) only ever processes
**one participant at a time**, returning one row of output — see
[Design Patterns](design-patterns.md#one-participant-at-a-time). This CLI
command is what loops over every matching participant and combines their
rows together into the one file described below. By default it processes
**every** participant found under `input_folder`. To process just one, add
`--subject_id`:

```bash
vrlab_crane_process crane_data crane_data/output --subject_id P00018
```

Add `--verbose` for more detailed log output while it runs:

```bash
vrlab_crane_process crane_data crane_data/output --verbose
```

### What you get out

Two combined files land in `output_folder`:

```text
vrlab_crane_process_batch_data_out.csv
vrlab_crane_process_batch_data_out.sav
```

(`.sav` is an SPSS file.) When `--subject_id` is used, both filenames are
prefixed with that subject's ID instead.

!!! note "Going further"
    See [Code Organization](code-organization.md#how-a-cli-command-receives-input-click)
    for how `input_folder`/`output_folder`/`--subject_id` map onto Python
    function parameters via `click`, and
    [Code Organization](code-organization.md#where-the-actual-steps-live)
    for where the actual per-step processing code lives.

## Other pipelines

The other command-line tools (`mobi_foh_process`, `mobi_foh_batch_process`,
`mobi_check_xdf`, …) take the same rough shape — an input path, an output
folder, and a handful of options — just for a different experiment. See the
project's `README.md` (in the workspace root) for the full, current list of
commands and examples.

---

**Next: [Code Organization](code-organization.md)** — now that you've run
the pipeline, see how the code that just ran is actually laid out.
