# Crosschecking

This is step 1: before your data can be [processed](processing.md), your
raw recordings need to be converted into the standard folder layout
analysis expects (called "BIDS") and crosschecked. This page explains what
that means and why it matters — it applies whether your data is from FOH,
Crane, or LongwalkV3. Once you've read this, go to [FOH
Crosscheck](foh-crosscheck.md), [Crane Crosscheck](crane-crosscheck.md),
or [LongwalkV3 Crosscheck](longwalkv3-crosscheck.md) for the
tool-specific walkthrough. You may use whichever ones match your data —
none of these tools depend on each other.

## What is "crosschecking"?

When a raw recording session gets converted into BIDS, the conversion step
doesn't try to be clever about picking files. If a session was restarted,
a filename is ambiguous, or there are two recordings that could both
plausibly be "the real one," the converter just keeps all of them rather
than guessing. That's deliberate — guessing wrong and silently keeping the
wrong file would be far worse than leaving the decision to a person.

**Crosschecking is that person's job**: going through each subject's folder
and confirming — or fixing — which file is the right one, so everything
downstream can trust it without re-checking. It's a filing and bookkeeping
step, not a data-quality step (more on that distinction below). Critically,
it is a *bookkeeping* step in a very literal sense: the point of these
tools is never to change your raw data — it's to build up a written record
of every decision made about it, a record kept entirely separate from the
raw files themselves, so that record can always be checked, corrected, or
replayed from scratch. The FOH and Crane Crosscheck tools are small
programs built specifically to make that job fast: they show you exactly
which subjects need a decision, give you the information you need to make
it, and remember every decision so it never has to be redone.

!!! info "The raw folder is never changed — not once, not ever"
    Everything either tool does — picking a recording, tagging it,
    correcting a date or filename, even removing a subject from BIDS —
    happens only in the **BIDS folder** and its own bookkeeping files. Your
    **raw folder** is opened for reading only: nothing either tool does
    ever writes to it, renames anything in it, or deletes anything from it.
    That's true of every correction button, however it's worded — it only
    corrects how a name or date gets *read* when building BIDS from raw,
    never edits anything on disk in the raw folder itself.

    That one rule is what makes everything else these tools do safe.
    Because every decision is *recorded* — never irreversibly baked into a
    renamed or deleted raw file — the entire BIDS folder, crosscheck
    decisions and all, can always be rebuilt from nothing but the raw
    folder plus those records. If the BIDS folder is ever lost, corrupted,
    or deleted by accident, nothing about your actual work is lost with it
    — see each tool's "Backing up, and rebuilding after a lost BIDS folder"
    section for how.

## How this is different from QC

It's easy to mix these two up, since both involve looking closely at a
recording — but they answer different questions, at different points:

- **Crosschecking** asks: *"Is this the right file, correctly labelled, and
  has someone recorded that this decision was made?"* It happens first,
  before any analysis.
- **Quality control (QC)** asks: *"Is the data inside this file actually
  good?"* — clean signal, sensible trial timing, no equipment glitches.
  That's a separate, later step: see [EDA & SCRs](eda.md), [FOH Output
  Checks](foh-output.md), and [Crane Output Checks](interval-qc.md) for
  the checks that happen once your data's actually processed.

Crosschecking always happens first: there's no point quality-checking a
recording that turns out to be the wrong one.

---

**Next: [FOH Crosscheck](foh-crosscheck.md)**, **[Crane
Crosscheck](crane-crosscheck.md)**, or **[LongwalkV3
Crosscheck](longwalkv3-crosscheck.md)** — whichever matches your data.
