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
  and copy it to `longwalkv3_examples/shape/`. *(Done — reviewed manifest with REDCap profile
  in place.)*
- 2026-11-18 — D2/D4 refined: heatmap pulses on its first row only, birds don't pulse
  (`_NON_PULSE_SUFFIXES` / `_FIRST_ROW_PULSE_SUFFIXES` in the generator); same clock drift as
  crane is now simulated per session in shape mode. Debrief: one raw REDCap file, sessions as
  rows; BIDS gets one `acq-debrief` file per subject per session.
- 2026-11-18 — **A1 done.** `longwalk3_bids.py` converts the current export layout:
  `sub-` prefix in raw names, session from the raw `ses-NN`/`ses_NN` folder (duplicates kept as
  `-dup2` for the crosscheck), `behaviour.csv`'s `TimeStampHHmm`, repeated headers, ragged rows,
  unpadded-ms datetimes (D6 placeholder), the three new actor classes, and per-session debrief
  with identifying REDCap columns (names, DOB, signatures, survey identifier) dropped. Synthetic
  set (5 clean + 6 error scenarios) converts to 35 events + 33 debrief files.
  Tests: `tests/test_longwalkv3_bids.py`.
- 2026-11-18 — **A2 + A3 done: crosscheck MVP.** New checks in `longwalk3_bids_crosscheck_gui.py`:
  EDA channel matched as `EDA*` (real `EDA100C`), restarted run (same city in >1 run of a
  session), run with no actor triggers (aborted?), run with no behaviour ratings, one REDCap
  debrief per recorded session (missing / extra / duplicate), plus raw-layout problems the
  converter now records in `longwalkv3_raw_audit.json` (session folder spelled `ses_NN`, csv
  name vs folder session, restarted-run subfolders). Existing checks kept (physiology per
  session, mislabeled date, multiple cities, city repeated, sessions > 3, empty/bad-onset
  events). `tests/test_longwalkv3_crosscheck.py` is the definition of done: clean participants
  → no problems; every `SHAPE_ERROR_TYPES` scenario flagged — **passes**. Skipped where the
  (gitignored) shape manifest isn't present.
- 2026-11-18 — Crosscheck GUIs (all of them): visible, remembered splitter between subject
  list and details.
- 2026-11-18 — **Phase B done.** `longwalk3_trial_intervals.py` implements D2 with
  drift-tracking pulse↔edge matching (offset re-anchored every match; unmatched pulses
  interpolated → CORRECTED). `run_pipeline_all_sessions` gives D3's wide row (`sesNN_`
  prefixes, SPSS-safe). `vrlab_longwalk3_process` CLI writes QC plots, CSV and SAV. On the
  synthetic set every clean session is `TrialIntervals=ok`; the aborted-run (error) and
  wrong-city (corrected) scenarios surface in the status columns, as they should until the
  crosscheck resolves them. Output has EDA (SCR/min per actor-instance interval) only —
  behaviour metrics wait for D1.
  **Open for later:** interval QC plot labels get crowded with ~40 intervals; the EDA module
  renumbers instance labels per class (`..._C_SCR_per_min_1..n`) — revisit with D1.
- 2026-11-18 — **Crosscheck rework (your review).** Sessions are numbered by calendar day
  across all of a subject's raw files (raw folder names ignored; the raw audit is gone).
  Sessions (Overview), runs and physiology recordings get a tickbox + **Remove**; what's left
  is renumbered by date (`plan_renumber_by_date` + new shared `files_moved` decision, replayable,
  swap-safe). **Sort sessions & runs by date** after a date correction. **Fix Record IDs in
  Debrief Data**: per REDCap row (study_id + event), corrected id or **Leave out**; debrief is
  rebuilt on every Refresh BIDS and matched to sessions by `session_date_time` (event order when
  undated). Old Remove-by-dialog buttons removed. **⤢ Focus on details** (F11) in every
  crosscheck tool.
