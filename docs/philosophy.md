# Why This Toolbox Exists

This page is about *why* the toolbox is built the way it is, not *how* —
for the how, see [Design Patterns](design-patterns.md) and
[Pipeline Concepts](pipeline-concepts.md).

## 1. Built for an active lab, not a demo

This toolbox supports live, ongoing research, not a one-off project — so
getting from raw data to usable data quickly is a real constraint, not a
nice-to-have. Good research depends on good data. Perfect data doesn't
exist, and complex physiological/behavioural streams need real handling
before they're usable — but we try to keep human correction of that data
to a minimum, because manual correction is inconsistent and is itself a
source of bias, not just labour. Machines make "mistakes" too, so some
human oversight stays necessary — the goal is to bound it, not remove it.

Part of bounding it is processing data as close to collection as
possible. This toolbox compiles into standalone executables for data
collectors, which does two separate jobs:

- **Catches errors early**, while the person who ran the session still
  remembers the context and can actually explain or fix an anomaly.
- **Removes the need for a Python environment** at the point of
  collection — the person collecting data doesn't need to be a
  programmer to run a validated pipeline.

## 2. Structured to be extended, not rewritten

Experience taught us that students often rewrite code from scratch even
when a working version already exists — not out of carelessness, but
because they don't know it exists, or it's written in a way that's
genuinely hard to build on. That's a discoverability and extensibility
problem, and it has two parts:

- **Discoverability**: code passed around as emailed scripts or one-off
  attachments has no shared history, no single source of truth, and no
  way to see what changed or why. Keeping the toolbox in version control
  (GitHub) fixes this directly — one canonical place to find it, a
  visible history of changes, and compiled executables distributed as
  tracked releases rather than an email attachment nobody can trace back
  to a version.
- **Extensibility**: even found code is only reusable if it's *built* to
  be reused. None of the design patterns used here are novel — they're
  the standard patterns from Gamma, Helm, Johnson & Vlissides'
  [*Design Patterns: Elements of Reusable Object-Oriented Software*](https://en.wikipedia.org/wiki/Design_Patterns)
  (1994) — but they're rarely applied in scientific code, because most
  scientists learn to code informally as postgrads and are never exposed
  to them. Structuring the toolbox around these patterns means a student
  can add a new pipeline with minimal new code, and what they write stays
  usable by the next person.

## 3. Written to teach and learn

The audience is scientists, not computer scientists, often without
formal training in software design — so this toolbox explains itself
more explicitly than a typical engineering codebase would, on purpose,
as a teaching tool. That cuts both ways: the authors aren't computer
scientists either, so this is as much us learning and writing down good
practice as it is us teaching it.

That teaching aim is also why this project takes a firm stance on AI
coding assistants — see [AI Use Guidelines](ai-use.md): an assistant that
writes the code *for* you undercuts the whole point of this section.

## Trade-offs worth naming

- **Teaching-first vs lean-first**: explicit, spelled-out code is easier
  to learn from but more verbose than a codebase optimized purely for
  production. We're choosing the former on purpose, not getting both for
  free.
- **Patterns add indirection**: structure that makes code extensible
  (protocols, contracts, strategy steps) also means more files and more
  abstraction than a quick script — a cost paid up front for a cost
  avoided later (rewrite-from-scratch).
- **Minimizing human intervention isn't eliminating it**: some judgment
  calls stay manual by necessity; the aim is fewer, better-placed
  interventions, not a fully hands-off pipeline.
