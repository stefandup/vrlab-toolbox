# FOH Output Checks

This is the extra check specific to FOH, on top of [EDA & SCRs](eda.md)
(read that first if you haven't already — it applies here too).

## No separate timing check needed

Crane has an extra step here — the [Interval QC Plot](interval-qc.md) —
because its physiology and behaviour data come from two independent
clocks that need to be matched up after the fact. FOH doesn't have that
problem: every stream in an FOH recording is already time-aligned to one
shared clock at recording time, so there's nothing extra to check for
timing. Once you've looked at the EDA QC plot, FOH's physiology side is
covered.

## Reviewing target-task performance

FOH also records how participants performed on a target task, alongside
the physiology signal. To review both side by side, per participant, run:

```bash
vrlab_plot_target_data --input-csv <path to your FOH_process_batch_out.csv> --output-dir <folder for the plots>
```

This reads the combined CSV [Process Your Data](processing.md#fohs-output-files)
produced, and saves one image per subject into the output folder, named
`<Subject_ID>_target_scr_paired_bars.png`.

Each image has two parts:

- **Top row** — three panels, one per target duration (Short, Medium,
  Long), each a bar chart of how quickly the participant hit the target
  (in seconds) during Training, Baseline, Stress, and Recovery.
- **Bottom row** — a bar chart of SCRs per minute (see [EDA &
  SCRs](eda.md)) during Baseline, Stress, and Recovery, so you can glance
  at target performance and physiological arousal for the same
  participant together.

A blank "SCR / min" panel with a note that no data was found means the
SCR columns weren't present for that subject in the CSV — worth checking
that subject's row in the CSV directly.

---

**Next: [Crane Output Checks](interval-qc.md)** — the extra thing to check
if your data is from Crane.
