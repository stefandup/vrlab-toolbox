# AI Style Guide

A single reference to hand an AI coding assistant — paste it in, or point
the assistant at this page — before it touches this codebase. Its job is
narrow: keep contributions consistent no matter which human, or which AI
tool, produced them, so the codebase doesn't slowly accumulate several
different styles and several different toolboxes for the same job.

This complements [AI Use Guidelines](ai-use.md): that page is the
*whether* — pipeline/processing/schema code stays human-typed, GUI and
docs can clear the bar for AI authorship (see [AI Use
Guidelines](ai-use.md#the-core-rule-ai-is-a-tutor-not-a-coder)). This page
is the *what*, for whenever code does get proposed, and for
guidance/examples an assistant gives along the way. It also renders
exactly where that *whether* line falls today — see [Cleared for Vibe
Coding](#cleared-for-vibe-coding) below — since `AGENTS.md`'s
BYPASS/OVERRIDE commands need one canonical list to point at rather than
a description duplicated across pages. That canonical list is
[`vibe_list.md`](https://github.com/stefandup/mobi-mooi-toolbox/blob/master/vibe_list.md)
at the repo root, a plain file in the
`.gitignore`/`CODEOWNERS` mold; this page transcludes its table rather
than keeping a second copy.

## The rule this page exists to enforce

Don't introduce a second way of doing something this codebase already does
one way. That's [Golden Rules](golden-rules.md#write-pythonic-code--dont-fight-the-language)'s
"Pythonic, boring, stock-standard Python" rule, applied specifically to
AI-suggested tools, patterns, and dependencies — the place an inconsistent
new style is most likely to sneak in unnoticed.

## Established stack — use what's already here

| Job | What this project already uses | Not: |
| --- | --- | --- |
| CLI commands | [`click`](https://click.palletsprojects.com/) | `argparse`, `typer`, hand-rolled `sys.argv` parsing |
| Dataframe validation | [`pandera`](https://pandera.readthedocs.io/) | `pydantic` for dataframes, hand-written column checks |
| Structured data | `dataclasses`, `typing.Protocol` contracts | plain dicts as pseudo-objects, custom base-class hierarchies |
| Error handling | EAFP, specific `except` tuples | broad `except Exception`, error-code return values |
| Testing | `pytest` | `unittest` as the *primary* style for new tests, custom test runners |
| Logging | stdlib `logging` | `print()`, a new logging library |
| CLI progress/output | `rich` | a second progress-bar or console-formatting library |
| Packaging/versioning | `setuptools_scm` (git tags), PyInstaller | hand-maintained version strings, a different bundler |

Before adding a new dependency, check `requirements.txt` first — if
something already does the job, use that. See
[Code Organization](code-organization.md#the-workspace-at-a-glance) for
where these are configured.

## Style specifics

- **Formatting/linting**: `ruff` — 100-character lines, double-quote
  strings. Let it format on save; don't hand-format around it (see
  [Code Organization](code-organization.md#code-style)).
- **Type hints** on every function signature — this is what makes
  `pyright`/Pylance catch mistakes at edit time (same page, above).
- **Naming**: `snake_case` for functions/variables, `PascalCase` for
  classes, `UPPER_SNAKE_CASE` for module-level constants.
- **f-strings** for string formatting, not `.format()` or `%`.
- **Minimal docstrings** — a line or two at most, only where the *why*
  isn't obvious from the code itself. Well-named functions and classes do
  most of the explaining; don't add a docstring that just restates the
  function name.

## Patterns to reuse, not reinvent

- **EAFP** for error handling, with specific exception types named in the
  `except` clause — [Golden Rules](golden-rules.md#ask-forgiveness-not-permission-eafp).
- **`Protocol`-based strategy steps** for pipeline stages, not a new
  inheritance hierarchy or a new plugin system —
  [Design Patterns](design-patterns.md).
- **Pandera schemas at dataframe boundaries** — validate on the way in and
  the way out, don't trust an untyped dataframe implicitly —
  [Design Patterns](design-patterns.md#input-and-output-contracts).
- **`dataclasses`**, frozen where the object shouldn't mutate after
  construction.
- **Thin CLI, fat `processing/`** — CLI files read input and call into
  `processing/`; the actual logic doesn't live in the CLI file —
  [Code Organization](code-organization.md#the-command-line-tools).

## No flashy new patterns

Specifically avoid, unless there's no working alternative and it's been
discussed first: metaclasses, monkey-patching, deeply nested
comprehensions or clever one-liners that trade readability for brevity,
new decorator-based magic (`@deprecated` is the one established exception
— [Golden Rules](golden-rules.md#mark-old-code-deprecated--dont-just-delete-it-or-leave-it-silently)),
and speculative abstractions or config options for a use case that doesn't
exist yet — [Golden Rules](golden-rules.md#write-code-for-today-not-for-a-hypothetical-future).

If a genuinely better pattern seems worth introducing, propose it
explicitly, as its own step, with the tradeoff stated — never slip it in
as a side effect of an unrelated change.

## One file, one step

Same rule as [AI Use Guidelines](ai-use.md#one-thing-at-a-time): don't let
an assistant touch multiple files, or introduce multiple new patterns, in
one proposed change.

## Teaching examples

If an assistant is asked for example code to explain a concept rather than
to solve the actual task, keep examples in a clearly separate, obviously
fictional domain unrelated to this project's own work (this repo's
`AGENTS.md`, at the workspace root, illustrates this with an everyday
domain like library checkouts, bus schedules, or a small inventory — pick
whatever fits the concept, but stay in one domain per explanation) — so an
example never gets mistaken for, or pasted in as, real production code.

## Cleared for vibe coding

[AI Use Guidelines](ai-use.md#the-core-rule-ai-is-a-tutor-not-a-coder)
draws its *whether* line at "pipeline, processing, and schema code," with
the GUI layer and prose docs as the named exceptions. In practice that
line runs through the middle of `processing/`: most of it is the analysis
logic this project exists to teach, but a handful of modules are
format/plumbing work — BIDS conversion, dummy-data generation, the
crosscheck feature — with the same low-teaching-value shape as the GUI
layer, not the pipeline foundation itself. The table below — transcluded
from [`vibe_list.md`](https://github.com/stefandup/mobi-mooi-toolbox/blob/master/vibe_list.md)
at the repo root, the single place it's actually maintained — is the file-level record of where that line
falls today. In `AGENTS.md`, this list is what **BYPASS** is scoped to;
everything *not* on it is default-deny (see [Verboten without
OVERRIDE](#verboten-without-override) below), so a new area only ever
needs adding to `vibe_list.md` itself to become BYPASS-eligible.

"Cleared" doesn't mean unsupervised, though. AI-authored code here still
has to pass the [four rules of vibe
coding](ai-use.md#the-four-rules-of-vibe-coding) — read it and understand
every step, explain it to someone else, fix it manually if it breaks,
build on it manually — and it still has to land on this page's
established stack and style rules above. Cleared for authorship isn't
cleared to invent a new pattern. The **Human-checked** column is that
sign-off, made concrete: tick it once
[@stefandup](https://github.com/stefandup) has actually read through
that area's current AI-authored state against the four rules. An
unticked box means it hasn't had that pass yet, not that something's
wrong.

--8<-- "vibe_list.md:table"

## Execution exception: dummy-data generation

Everything above this section is about *authorship* — `AGENTS.md`'s
guardrails otherwise stop an assistant from ever running code itself, even
in areas cleared for vibe coding, requiring every command to be handed to
a human to run instead. `vrlab_crane_generate_sample_data` (and the
equivalent `longwalk`/`foh` sample-data generators) is the one exception:
because it only ever writes synthetic data into `*_examples/` folders and
never touches real subject data, an AI assistant may run it directly —
including the `--bids-folder` conversion step it can trigger in the same
call — rather than just proposing the command.

That doesn't skip the human step, it moves it: whatever the tool
generates still needs a human to look at the result (`git diff`/`git
status` on the `*_examples/` output, and the printed generation summary
table) before it's trusted for pipeline testing. This exception is scoped
to dummy-data generation specifically — it doesn't extend to running the
BIDS-conversion CLIs standalone, the crosscheck tool, or the
pipeline/processing CLIs (e.g. `vrlab_crane_process`) on that data, which
all stay under `AGENTS.md`'s ordinary "only suggest commands" rule.

## Execution exception: code-checking tools

A second exception to the same run-nothing-yourself default (see above):
an AI assistant may run the project's configured checkers — `ruff check`,
`ruff format`/`--check`, `pyright`/Pylance — directly, and apply the fixes
they suggest, against any file listed in
[`vibe_list.md`](https://github.com/stefandup/mobi-mooi-toolbox/blob/master/vibe_list.md).
That's not a new authorship permission; it's the same one BYPASS already
grants for those files, just applied to catching what a first pass
missed, so there's no extra approval step beyond the one the file's
presence on `vibe_list.md` already implies. Running a checker against, or
fixing what it flags in, any file *not* on `vibe_list.md` still means
only suggesting the command — same as every other command against an
OVERRIDE-only file.

## Execution exception: build scripts

A third exception to the same run-nothing-yourself default (see above):
an AI assistant may run `build.ps1` (Windows) or `build_mac.sh` (macOS)
directly, in any of their modes (`-Exe`, `-Full`, `-Inno` for `build.ps1`).
Unlike the other execution exceptions, this one isn't gated on
`vibe_list.md` membership — it's the *build scripts themselves* that are
scoped, not the files they happen to touch: `-Exe`/`-Full` write only into
the gitignored `build_output/` folder (plus a local editable-install of
this same package into the active venv, via `pip install -e .`) and `-Full`/
`-Inno` additionally compile the installer with Inno Setup's `ISCC.exe`,
also writing only under `build_output/`. None of that touches git, a
remote system, or any credential. Running `toolbox_installer.iss` /
`ISCC.exe` on its own, outside of `build.ps1` invoking it, is not covered
by this exception and still means only suggesting the command.

## Verboten without OVERRIDE

![Stop sign](assets/images/stop-sign.png){ width="80" }

This isn't a second list to maintain — it's **everything not named** in
[`vibe_list.md`](https://github.com/stefandup/mobi-mooi-toolbox/blob/master/vibe_list.md)'s
[Cleared for vibe coding](#cleared-for-vibe-coding) table above, anywhere in the repo, not
just `src/vrlab_toolbox/processing/`. Default-deny: a file doesn't need
adding to a table here to become off-limits for AI authorship under
`AGENTS.md`'s ordinary BYPASS command — it's off-limits the moment it's
absent from `vibe_list.md`. Reaching for **OVERRIDE** instead doesn't
relax the standard; it's for the "genuinely unavoidable" cases that page
already allows for, and the same [four rules of vibe
coding](ai-use.md#the-four-rules-of-vibe-coding) still apply to whatever
lands.

In practice, today, that's almost entirely `src/vrlab_toolbox/processing/`'s
pipeline orchestration (`crane_pipeline.py`, `foh_pipeline.py`,
`longwalk_pipeline.py`, `mobi_core_pipeline.py`, `graphomotor_pipeline.py`,
`pipeline.py`), signal processing (`biopac.py`, `ecg.py`, `eda.py`,
`eeg.py`, `lsl.py`, `opensignals.py`, `spiral.py`), behaviour/trial-interval
extraction (`behaviour.py`, `biodata.py`, `crane_behaviour.py`,
`crane_debrief_behaviour.py`, `crane_trial_intervals.py`,
`foh_behaviour.py`, `foh_target_behaviour.py`, `foh_trial_intervals.py`,
`longwalk_behaviour.py`, `longwalk_trial_intervals.py`,
`trial_intervals.py`), REDCap/config/IO (`crane_redcap.py`, `redcap.py`,
`foh_config.py`, `input_data.py`, `output_data.py`,
`processing_status.py`), schemas/shared utilities (`pandera_defaults.py`,
`plot_utils.py`), and graphomotor (`graphomotor_qc.py`,
`graphomotor_task.py`, `graphomotor_xdf.py`) — the actual analysis logic
[AI Use Guidelines](ai-use.md#the-core-rule-ai-is-a-tutor-not-a-coder)'s
core rule is about. That's a description of where OVERRIDE tends to come
up, though, not the mechanism itself: it's whatever's left over once
`vibe_list.md` is subtracted, so this paragraph can go stale without
breaking anything, unlike a maintained deny-list would.

## Restricted folders

Separate from authorship style: [`.ai_restricted`](https://github.com/stefandup/mobi-mooi-toolbox/blob/master/.ai_restricted)
(repo root) is a human-maintained, `.gitignore`-style list of folders no AI
assistant may read or write — typically example/sample data the user doesn't
want an AI touching. Absolute, and not affected by BYPASS or OVERRIDE — see
`AGENTS.md`'s restricted-folders guardrail.

## Using this page

Point any AI assistant here before it looks at anything else in this
repo — as a pasted-in reference, or via whatever project config file your
tool reads (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`,
`.github/copilot-instructions.md`, …). This repo's own `AGENTS.md` already
does the equivalent for its interaction style; this page is the equivalent
for code style and toolbox choices.

This page is also meant to be reusable beyond this one repo: the same
shape — an established-stack table, mechanical style rules, patterns to
reuse, an explicit avoid-list — travels to any future lab codebase, so
different projects (and different people's AI assistants) don't drift
into incompatible styles from each other, either.
