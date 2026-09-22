| Area | Files | Human-checked ([@stefandup](https://github.com/stefandup)) |
| --- | --- | --- |
| BIDS conversion | `src/vrlab_toolbox/processing/bids.py`, `crane_bids.py`, `longwalk_bids.py`, `longwalk3_bids.py` | [ ] |
| Dummy/sample data | `src/vrlab_toolbox/processing/crane_dummy_data.py` | [ ] |
| CLIs | every file in `src/vrlab_toolbox/cli/` — already thin by design, see [Thin CLI, fat `processing/`](docs/ai-style-guide.md#patterns-to-reuse-not-reinvent) | [ ] |
| Crosscheck (backend + GUI) | `src/vrlab_toolbox/processing/bids_crosscheck.py`; `src/vrlab_toolbox/gui/bids_crosscheck_common.py`, `crane_bids_crosscheck_gui.py`, `foh_bids_crosscheck_gui.py`, `longwalk_bids_crosscheck_gui.py`, `longwalk3_bids_crosscheck_gui.py` | [ ] |
| Process results viewer (GUI) | `src/vrlab_toolbox/gui/qt_common.py`, `process_results_common.py`, `crane_process_results_gui.py`, `longwalk_process_results_gui.py` — read-only viewer over a `vrlab_*_process` output folder, same GUI-layer shape as crosscheck | [ ] |
| Toolbox launcher (GUI) | `src/vrlab_toolbox/gui/toolbox_launcher.py` | [ ] |
| Build/packaging scripts | `build.ps1`, `build_mac.sh`, `toolbox_installer.iss`, `specs/*.spec` | [ ] |
| Docs | everything under `docs/`, plus `mkdocs.yml` — already covered by [AI Use Guidelines](docs/ai-use.md)'s docs exception | [ ] |
| Root README | `README.md` | [ ] |
| CI workflows | `.github/workflows/*.yml` | [ ] |
