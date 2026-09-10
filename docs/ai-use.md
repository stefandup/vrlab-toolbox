# AI Use Guidelines

This project is written to teach and learn (see
[Why This Toolbox Exists](philosophy.md#3-written-to-teach-and-learn)), and
AI coding assistants are common enough now that how you use one here is
part of that. This page states the house rule plainly.

!!! note "The exception: prose docs, the GUI layer, and a few named plumbing modules"
    This page, like the rest of the prose docs, was AI-drafted from the
    author's own rough notes, then checked line by line against what was
    actually meant — draft, verify, correct, not draft-and-paste. The
    crosscheck GUIs get the same exception, for the same underlying
    reason: they're a layer added on top of a human-written pipeline
    foundation (see [Design Patterns](design-patterns.md)), not the
    foundation itself.

    A handful of `processing/` modules join them for the same reason,
    despite living in that directory: BIDS conversion, dummy/sample-data
    generation, and the crosscheck feature's processing-layer backend are
    format/plumbing work, not the analysis logic this project exists to
    teach. The [AI Style Guide](ai-style-guide.md#cleared-for-vibe-coding)
    keeps the maintained, file-level list — that's the canonical record of
    where this line falls, not this page.

    Either way, the test isn't *who typed it* — it's the [four rules of
    vibe coding](#the-four-rules-of-vibe-coding) below. Pass them, and
    AI-authored code is fine. Fail one, and that gap is cognitive debt —
    see below.

## The core rule: AI is a tutor, not a coder

**For the pipeline, processing, and schema code this project exists to
teach: no vibe coding, unless genuinely unavoidable.** "Vibe coding" here
means asking an AI assistant to produce a change and pasting it in without
having worked out and understood the change yourself first. The named
exceptions above — GUI, docs, and the specific plumbing modules listed in
the [AI Style Guide](ai-style-guide.md#cleared-for-vibe-coding) — are
carve-outs from *this* rule, not a loosening of it for everything else.

For that code, use an AI assistant the way you'd use a good tutor:

- Ask it to **explain** a pattern, a bug, or an error message.
- Ask it to **guide** you toward an approach — the shape of a solution, not
  the solution itself.
- Then **write the code yourself**. Type it, don't paste it.

Outside that foundation — the GUI layer built on top of it, or prose docs —
the bar is the [four rules of vibe coding](#the-four-rules-of-vibe-coding)
below. That test is what decides it, not who typed it first.

## The four rules of vibe coding

Before AI-authored code counts as *yours* — cleared list or not — all four
of these have to be true:

1. **You can read through it and understand every step** — not just that
   it runs, but what each part does and why.
2. **You can explain it to someone else** — out loud, from memory, without
   re-reading the file first.
3. **You can fix it manually if it breaks** — debug it yourself, without
   going back to the assistant that wrote it.
4. **You can build on it manually** — extend it or adapt it to a new case
   yourself, without asking the assistant to do that step too.

Fail any one of these and what you have is cognitive debt (see below), not
working code — even if it runs today.

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

The GUI layer, repetitive boilerplate with no learning value, prose docs,
and the named `processing/` plumbing modules (BIDS conversion, dummy/
sample-data generation, the crosscheck backend — see the [AI Style
Guide](ai-style-guide.md#cleared-for-vibe-coding) for the current list)
all clear the bar above. The actual logic of a pipeline, a schema, or a
design pattern doesn't — that's the part this project exists to teach, and
where writing it yourself matters most. Either way, keep it on this
project's existing rails — see the [AI Style Guide](ai-style-guide.md) for
the established stack, patterns, and what *not* to introduce.

In your own AI tool, this maps onto `AGENTS.md`'s **BYPASS** (scoped to
the cleared list) and **OVERRIDE** (for the rest — the "genuinely
unavoidable" case above, not a way around it) commands.

## Setting this up in your own AI tool

This repo's own `AGENTS.md` (repo root) encodes this operating mode for AI
coding assistants that read it: explain before proposing code, one small
step at a time, ask before editing, wait for confirmation. If your
assistant reads a different config file (e.g. `CLAUDE.md`, `.cursorrules`,
`.github/copilot-instructions.md`), it's worth setting up something
similar for yourself, with the same shape: explain first, guide instead of
solve, one step, consent before any edit. It earns its keep most while
you're still building the muscle behind the [four rules of vibe
coding](#the-four-rules-of-vibe-coding) — once you're reliably passing
that test unassisted on the code you're touching, loosen the rails to
match.

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
