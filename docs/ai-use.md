# AI Use Guidelines

This project is written to teach and learn (see
[Why This Toolbox Exists](philosophy.md#3-written-to-teach-and-learn)), and
AI coding assistants are common enough now that how you use one here is
part of that. This page states the house rule plainly.

!!! note "The exception: prose docs, and the GUI layer"
    This page, like the rest of the prose docs, was AI-drafted from the
    author's own rough notes, then checked line by line against what was
    actually meant — draft, verify, correct, not draft-and-paste. The
    crosscheck GUIs get the same exception, for the same underlying
    reason: they're a layer added on top of a human-written pipeline
    foundation (see [Design Patterns](design-patterns.md)), not the
    foundation itself.

    Either way, the test isn't *who typed it* — it's **do you understand
    it, could you explain it, could you extend it?** Pass that, and
    AI-authored code is fine. Fail it, and that gap is cognitive debt —
    see below.

## The core rule: AI is a tutor, not a coder

**For the pipeline, processing, and schema code this project exists to
teach: no vibe coding, unless genuinely unavoidable.** "Vibe coding" here
means asking an AI assistant to produce a change and pasting it in without
having worked out and understood the change yourself first.

For that code, use an AI assistant the way you'd use a good tutor:

- Ask it to **explain** a pattern, a bug, or an error message.
- Ask it to **guide** you toward an approach — the shape of a solution, not
  the solution itself.
- Then **write the code yourself**. Type it, don't paste it.

Outside that foundation — the GUI layer built on top of it, or prose docs —
the bar is the test from the note above: understand it, could explain it,
could extend it. That test is what decides it, not who typed it first.

## Why: cognitive debt

Letting an AI write the code *feels* faster, and often is, in the moment.
But this toolbox exists partly to teach design patterns that scientists
don't usually get exposed to (see
[Why This Toolbox Exists](philosophy.md#2-structured-to-be-extended-not-rewritten)) —
and that only works if the person writing the code is the one doing the
thinking. Outsourcing the thinking to an AI assistant produces working code
today at the cost of understanding you'll need later: to debug it, extend
it, or explain it to the next person. That gap is **cognitive debt** — like
technical debt, but the thing left unpaid is your own understanding, not
the code. It's quiet at first and expensive later, exactly when you can
least afford it (mid-debugging, under deadline).

Avoiding that is a stated aim of this project, not an afterthought — so
treat "did I actually understand what I just wrote" as a real check, same
as running the tests.

## One thing at a time

Don't let an AI assistant change things across the codebase in one go, even
if it offers to. This isn't AI-specific — see
[Golden Rules](golden-rules.md#write-code-for-today-not-for-a-hypothetical-future) —
but AI assistants make sweeping changes *easy* to ask for, which is exactly
why the guardrail matters more here, not less:

- One function or file at a time.
- Understand and test that change before moving to the next.
- If an assistant proposes touching several files at once, that's a signal
  to slow down and split the request, not a shortcut worth taking.

## Practical guidelines when working with an assistant here

- Ask **why** before **what** — understand the reasoning before you accept
  a suggestion.
- Ask for **conceptual guidance** (the approach, the pattern to use) rather
  than a finished implementation. If the assistant offers a full solution
  unprompted, ask it to back up and explain instead.
- Keep changes to **one file, one step** at a time — see above.
- Have the assistant **explain code it wrote**, if any ever does land, well
  enough that you could reproduce it yourself without it.
- If you're not sure you could rewrite what you just accepted from memory,
  that's the signal you skipped the learning step — go back and do it
  properly before moving on.

## When AI-authored code is acceptable

The GUI layer, repetitive boilerplate with no learning value, and prose
docs all clear the bar above. The actual logic of a pipeline, a schema, or
a design pattern doesn't — that's the part this project exists to teach,
and where writing it yourself matters most. Either way, keep it on this
project's existing rails — see the [AI Style Guide](ai-style-guide.md) for
the established stack, patterns, and what *not* to introduce.

## Setting this up in your own AI tool

This repo's own `AGENTS.md` (repo root) encodes this operating mode for AI
coding assistants that read it: explain before proposing code, one small
step at a time, ask before editing, wait for confirmation. If your
assistant reads a different config file (e.g. `CLAUDE.md`, `.cursorrules`,
`.github/copilot-instructions.md`), it's worth setting up something
similar for yourself, with the same shape: explain first, guide instead of
solve, one step, consent before any edit. It earns its keep most while
you're still building the understand-it/explain-it/extend-it muscle from
the test above — once you're reliably passing that test unassisted on the
code you're touching, loosen the rails to match.

That covers *behaviour* — how an assistant should interact with you. Pair
it with the [AI Style Guide](ai-style-guide.md), which covers *output* —
the established stack, patterns, and style an assistant should stick to
on the rare occasion code does get proposed. Point your assistant at both:
`AGENTS.md` (or your tool's equivalent) for how to behave, the
[AI Style Guide](ai-style-guide.md) for what "correct" looks like here if
it ever writes anything.

---

**Next: [For Contributors](contributing.md)** — the GitHub workflow for
sharing a change back, once you've written it yourself.
