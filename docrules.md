# Doc Rules

Rules for writing the project docs. Read this before writing any page in `docs/`.

## What we're building

- Tool: [MkDocs](https://www.mkdocs.org/) with the `mkdocs-material` theme.
- Source: plain Markdown files in `docs/`.
- For now: **local only** (`mkdocs serve` to preview, `mkdocs build` for a static site).
  We can't publish to GitHub Pages until the repo is public or on a paid GitHub plan.
- Planned sections (nav), sketched before writing content:
  1. **Getting Started** — install, run the pipeline, see output.
  2. **Pipeline Concepts** — how the pipeline is built (Template + Strategy pattern).
  3. **API Reference** — what each function/class does.

(Full backlog for this work: see item 20 in `docs/pipeline_next_steps.md`.)

## Writing rules

1. **Simple and succinct.** Short sentences. Short pages. One idea per section.
2. **Write for a Python beginner first.** Assume the reader is a student who just
   started learning Python. Explain things a first-year wouldn't already know.
   Add short "**Going further**" boxes for advanced students who want to understand
   *why* a strategy/pattern was used, not just *what* it does.
3. **Plain English.** Short, everyday words. Short sentences.
4. **Avoid jargon.** If a technical term is needed (e.g. "strategy pattern"), define
   it in one line the first time it's used.
