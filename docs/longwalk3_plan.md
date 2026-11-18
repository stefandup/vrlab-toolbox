# LongwalkV3 Build Plan — `BUILD longwalk3 LIKE crane`

**Deadline:** end of Friday 2026-11-20. **Branch:** `pipeline/longwalkv3`.
**Mode:** [BUILD](ai-style-guide.md#build-mode) — AI-authored commits are prefixed `[vibe]`;
`git log --grep "\[vibe\]"` is the review record. Context: item 32 in
[Pipeline Next Steps](pipeline_next_steps.md) (steps 1–2, shape profiler + manifest-driven dummy
data, are done; this plan picks up at step 3).

All verification runs against synthetic data only (`longwalkv3_examples/dummy_data` and its BIDS
conversion) — never the real folders listed in `.ai_restricted`.

## State at start (2026-11-18)

| Area | Crane (example) | LongwalkV3 now |
| --- | --- | --- |
| Dummy data + CLI | done | done (manifest-driven, `--with-errors` scenarios) |
| BIDS conversion + CLI | done | exists — not yet verified against the new layout (`run-00N/` subfolders, new actor logs, `ses_01` spelling, stray `longwalkv3_generateIDs/`) |
| BIDS crosscheck GUI | done | exists; `REQUIRED_PHYSIOLOGY_CHANNEL = "EDA"` misses the real `EDA100C`; item-32 MVP checks missing |
| Behaviour import/process | schema + metrics | stubs: empty schemas, process returns an empty output |
| Debrief | REDCap group file → per-subject | stub; `longwalk3_redcap.py` is empty |
| Trial intervals | trigger matching + fallback | broken (`marker_interval_pairs` undefined), returns empty intervals |
| Physiology (EDA) | SCR per minute per interval | wired, but `eda.py` looks for `"EDA"`, not `"EDA100C"` |
| Participant output schema | built from constants | empty |
| Process CLI (`vrlab_*_process`) | `vrlab_crane_process` | **missing** |
| Process results viewer GUI | `crane_process_results_gui.py` | **missing** |
| Launcher / `pyproject` / `toolbox.spec` | all entries | crosscheck + convert + generate only |
| Tests | dummy-data + pipeline | `test_longwalkv3_pipeline.py`: 5/5 fail (`longwalkv3_examples/bids` not BIDS-like) |
| Docs | crosscheck page + milestones | crosscheck page only |

## Work, in priority order

Phases A–B are the Friday must-haves; C–D are the stretch.

### A. Crosscheck MVP (item 32 step 3) — no human decisions needed

1. Regenerate the synthetic set (clean + `--with-errors`) and convert it to BIDS; fix
   `longwalk3_bids.py` wherever the new layout breaks it (run subfolders, new actor logs,
   session-folder spelling, stray top-level folders).
2. Crosscheck checks: session-folder naming, expected file set per run, CSV headers vs the
   manifest, `.acq` present per session, EDA channel matched as `EDA*` (fixes `EDA100C`),
   `.acq`/CSV timestamp agreement, header-only logs flagged, `datetime` cells shorter than 17
   digits tolerated (ms not zero-padded).
3. Tests: clean dummy data → no problems; each injected `ERROR_TYPES` scenario → flagged.
   **Done =** that test passes.

### B. Pipeline runs end-to-end on dummy data — mechanics only

4. Fix the test fixture folder; get `test_longwalkv3_pipeline.py` green.
5. Raw schemas (events, `behaviour.csv` with `TimeStampHHmm, Nausea, Dizzy, Stressed, Anxious`),
   `datetime` parsing, EDA channel name in `eda.py`.
6. Trial intervals: fix the undefined variable and match Biopac triggers to the behaviour-based
   intervals the Crane way, using the **D2** placeholder below until it's decided.
7. `vrlab_longwalk3_process` CLI (like `vrlab_crane_process`), with a `--session` option.

### C. Results viewer + packaging

8. `longwalk3_process_results_gui.py` (like Crane's), plus launcher, `pyproject.toml` and
   `specs/toolbox.spec` entries; `build.ps1 -Exe` smoke build.

### D. Docs

9. User docs page for processing, `mkdocs.yml` nav, and a `vibe_list.md` update for every
   shared file touched.

## Major decisions

Answered 2026-11-18 unless marked open. Open ones stay placeholder-wired, marked
`# DECISION Dn` in code.

| # | Decision | Answer |
| --- | --- | --- |
| D1 | **Behaviour output metrics** | **Open — later.** For now the goal is *valid and analyzable* data, not metrics: schemas + crosscheck, no metric columns. |
| D2 | **What an interval is** | An interval **starts at the first pulse from an actor instance and ends when a pulse arrives from a different actor instance**; label = the actor instance name. |
| D3 | **Sessions in pipeline output** | **One wide row per subject** (sessions as column prefixes). |
| D4 | **Debrief** | REDCap debrief is **long format: one row per subject per session**. Field details settled once the data JSONs (shape manifests) are updated with a real REDCap profile. |
| D5 | **Rating scale** | **Likert 1–5** (Stress, Nausea, etc.). Generator updated (`LIKERT_RANGE`). |
| D6 | **`datetime` ms padding** | **Open — later**, checked against the student's new example data. Placeholder: treat short values as unpadded ms. |

**Knock-on from D4:** `longwalk3_bids.py` currently writes *one* debrief file per subject
anchored on `ses-01`. It has to split the long REDCap export by session instead (phase A1).
How a REDCap row maps to a session (`redcap_event_name` or `redcap_repeat_instance`) is read off
the profiled manifest once a real one exists.

**Knock-on from D2:** an actor instance's pulses are only identifiable from the behaviour/actor
logs (which instance logged each row), so intervals are built from the CSVs and matched to the
Biopac trigger channel, the same way Crane matches behaviour-based intervals to triggers.

## Progress log

- 2026-11-18 — plan written; BUILD rule committed (`d06bb7b`).
- 2026-11-18 — D1–D6 answered (above). Dummy generator extended for REDCap: `--profile-shape`
  now profiles REDCap exports (found at the data folder's top level, or via `--redcap-export`)
  into the manifest's `redcap_exports` (manifest version 2, structure only), and shape mode
  writes a long-format dummy REDCap export from it. Tests: `tests/test_longwalkv3_dummy_data.py`.
  **Your step:** re-profile the real folder with the REDCap export included, review the JSON,
  and copy it to `longwalkv3_examples/shape/`.
