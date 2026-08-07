# Crane Pipeline Milestones

Running log of architectural/skill milestones in this repo, for REVIEW mode
(see `AGENTS.md`) to compare current work against. Not a full changelog —
only entries that mark a real shift in approach (new pattern, new tooling,
new discipline), so progress over months is visible at a glance.

| Date | Commit | Milestone | Why it matters |
|---|---|---|---|
| 2026-03-11 | `70e2d40` | First EDA/XDF processing script (`check_plux_data.py`) | Flat exploratory script: hardcoded paths, `print()` diagnostics, no tests, no modules. The baseline to measure everything else against. |
| 2026-04-14 | `a6a8d52` | Refactor check_plux_data into focused processing modules | First split from one script into separate processing modules. |
| 2026-04-16 | `fa18788` / `c55501b` | Added basic logging, then improved it | `print()` → `logging` module. Diagnostics become structured and filterable. |
| 2026-06-10 | `fa5e52d` | Added basic unit test to crane pipeline | First test in the crane path — testing becomes part of the workflow, not an afterthought. |
| 2026-06-19 | `d444a5c` | Implemented status class | Processing outcomes become a typed `Status`/`PipelineStatus` object instead of ad-hoc bools/strings. |
| 2026-07-01 | `189389a` | Added template and strategy base classes. Refactored key data types | Strategy/Template pattern introduced — the architectural turning point from "pipeline as a sequence of function calls" to "pipeline as composable, typed steps." |
| 2026-07-06 | `1b700df` / `11177da` | Added Ruff settings, initial ruff reformat | Static analysis and consistent formatting adopted project-wide. |
| 2026-07-17 | `032d3dd` | First implementation of `pipeline.py` for crane. Tests passed | First green run of the new pipeline architecture end-to-end. |
| 2026-07-22 | `2d91140` | Tidied up a bit. Added deprecation warnings | `@deprecated` used to retire flawed logic explicitly instead of silently deleting or leaving it live — keeps the migration honest. |
| 2026-07-24 | `4ca8143` (WIP tip at last REVIEW) | Logging added; pipeline runs through alignment; edge-case tests in place but 3 still failing | Most recent REVIEW checkpoint. Trigger/behaviour alignment refactored to return real `PipelineStatus` (was previously a stub); remaining gaps are documented edge cases (`PID4572`, `PID16230`, `PID9188`), not silent failures. |
| 2026-07-24 | `cc639d9` (WIP tip) | Placeholder `pass` tests replaced with real assertions; `align_biopac_trigger_drift_from_behav_file` stopped discarding its own result | The 6 edge-case tests that were silent `pass` stubs now assert and fail loudly where the algorithm genuinely can't yet handle the subject's data — test red is now signal, not a gap in coverage. Also added a `remove_crane_delayed_start` heuristic and switched `fill_in_gaps` to return a new sorted `TrialIntervals` instead of mutating in place. |
| 2026-07-28 | `669645e` | `PipelineStatus` rewritten to type-keyed tracking; two `UnboundLocalError` classes of bug root-caused and fixed via captured-output-type-before-`try`; `None`-input guard added instead of widening an `except` tuple; dead code (`CraneDebriefOutputData`) deleted rather than left to rot | The two `SequentialBehaviourImportSteps`/`SequentialPhysiolgyImportSteps` bugs and the `AttributeError`-swallowing fix show a specific, reusable diagnostic move — noticing that catching a broad exception type is "working by luck," not by design — and choosing the narrower, more correct fix over the shortcut, even after the shortcut already made tests pass. All three previously-`@unittest.skip`ped tests are unskipped and green. |

| 2026-07-30 | `af1d483` (WIP tip) | LSL/FOH begins moving onto shared raw-data contracts | `LslPhysiologyDataImportStrategy` now returns `RawBioData`, and raw physiology labels are normalized at the contract boundary; this shows the pipeline architecture starting to become reusable toolbox infrastructure rather than Crane-only structure. |
| 2026-08-07 | `f720a47` (WIP tip) | Batch CLI (`mobi_FOH_process_batch.py`) migrated from deprecated `run_lsl_pipeline` to `run_pipeline`/`PipelineTemplate`; `test_basic_foh_pipeline` strengthened from a single truthiness check to per-datatype status + figure assertions | First real entry point proving the FOH `PipelineTemplate` end-to-end through an actual CLI, not just direct unit tests. `mobi_FOH_process.py` (the single-file CLI) was deliberately left on the deprecated path rather than migrated in the same commit — matches this project's own "one structural issue at a time" working rule, not an oversight. |

## How this file grows

After each REVIEW, append one new row: date, commit hash (or "WIP tip" if
uncommitted), a short milestone label, and a one-line note on what it
demonstrates skill-wise. Keep entries to real shifts in approach, not every
commit — this file is meant to stay short enough to read in one pass years
from now.
