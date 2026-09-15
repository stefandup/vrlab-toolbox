# Vibe-Coding Allow-List

The canonical, plain-text record of which parts of this codebase an AI assistant may
author without **OVERRIDE** — see `AGENTS.md`'s BYPASS/OVERRIDE commands and
[AI Style Guide](docs/ai-style-guide.md#cleared-for-vibe-coding). Lives at the repo root,
not under `docs/`, the same way `.gitignore`/`CODEOWNERS` do — one plain file to edit, not
a table kept in sync with a second copy elsewhere; `docs/ai-style-guide.md` transcludes
the table below verbatim (via MkDocs' `pymdownx.snippets`) rather than duplicating it.

**Default-deny**: anything *not* listed below needs OVERRIDE, not BYPASS — whether or not
it's ever been explicitly called out as off-limits. A new file only ever needs adding
*here* to become BYPASS-eligible; it never needs adding anywhere else to stay
OVERRIDE-only, since silence is already the default. See
[AI Style Guide](docs/ai-style-guide.md#verboten-without-override).

"Cleared" doesn't mean unsupervised — see
[AI Style Guide](docs/ai-style-guide.md#cleared-for-vibe-coding) for the four rules of
vibe coding and the established stack/style every AI-authored change here still has to
land on. The **Human-checked** column is [@stefandup](https://github.com/stefandup)'s
sign-off that an area's current AI-authored state has actually been read against those
four rules; an unticked box means that pass hasn't happened yet, not that something's
wrong.

<!-- --8<-- [start:table] -->
| Area | Files | Human-checked ([@stefandup](https://github.com/stefandup)) |
| --- | --- | --- |
| BIDS conversion | `src/mooi_toolbox/processing/bids.py`, `crane_bids.py`, `longwalk_bids.py` | [ ] |
| Dummy/sample data | `src/mooi_toolbox/processing/crane_dummy_data.py` | [ ] |
| CLIs | every file in `src/mooi_toolbox/cli/` — already thin by design, see [Thin CLI, fat `processing/`](docs/ai-style-guide.md#patterns-to-reuse-not-reinvent) | [ ] |
| Crosscheck (backend + GUI) | `src/mooi_toolbox/processing/bids_crosscheck.py`; `src/mooi_toolbox/gui/bids_crosscheck_common.py`, `crane_bids_crosscheck_gui.py`, `foh_bids_crosscheck_gui.py`, `longwalk_bids_crosscheck_gui.py` | [ ] |
| Process results viewer (GUI) | `src/mooi_toolbox/gui/qt_common.py`, `process_results_common.py`, `crane_process_results_gui.py`, `longwalk_process_results_gui.py` — read-only viewer over a `vrlab_*_process` output folder, same GUI-layer shape as crosscheck | [ ] |
| Toolbox launcher (GUI) | `src/mooi_toolbox/gui/toolbox_launcher.py` | [ ] |
| Build/packaging scripts | `build.ps1`, `build_mac.sh`, `toolbox_installer.iss`, `specs/*.spec` | [ ] |
| Docs | everything under `docs/`, plus `mkdocs.yml` — already covered by [AI Use Guidelines](docs/ai-use.md)'s docs exception | [ ] |
<!-- --8<-- [end:table] -->
