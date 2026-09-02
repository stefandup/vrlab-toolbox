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
guidance/examples an assistant gives along the way.

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
