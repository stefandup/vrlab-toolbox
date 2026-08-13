# FOH Crosscheck

This page is for anyone using the FOH Crosscheck tool to prepare data for
analysis — no coding background needed.

## What is "crosschecking"?

When a raw FOH recording session gets converted into the tidy, standardised
folder layout analysis expects (called "BIDS"), the conversion step doesn't
try to be clever about picking files. If a session was restarted, or there
are two recordings that could both plausibly be "the real one," the
converter just keeps all of them rather than guessing. That's deliberate —
guessing wrong and silently keeping the wrong file would be far worse than
leaving the decision to a person.

**Crosschecking is that person's job**: going through each subject's folder
and confirming — or fixing — which file is the right one, so everything
downstream can trust it without re-checking. It's a filing and bookkeeping
step, not a data-quality step (more on that distinction below). The FOH
Crosscheck tool is a small program built specifically to make that job fast:
it shows you exactly which subjects need a decision, gives you the
information you need to make it, and remembers every decision so it never
has to be redone.

## Why this matters for FOH data specifically

FOH sessions are recorded live, with real participants, real equipment, and
real interruptions — a recording might get restarted after a false start, a
laptop might reconnect mid-session and create a second file, or a test
recording might end up saved in the same folder as the real one. None of
that is unusual, and none of it is something a computer program can safely
sort out on its own — it takes a person who can look at when a recording
happened, how long it ran, and what it actually contains, and make the
call.

Left undone, this kind of ambiguity doesn't cause an obvious error later —
it causes *silent* problems: an analysis quietly running on a test file, or
on an earlier, incomplete attempt, with no error message anywhere to catch
it. Crosschecking front-loads that judgment call once, on purpose, instead
of leaving it to chance.

## How this is different from QC

It's easy to mix these two up, since both involve looking closely at a
recording — but they answer different questions, at different points:

- **Crosschecking** asks: *"Is this the right file, correctly labelled, and
  has someone recorded that this decision was made?"* It happens first,
  before any analysis, and it's what this page covers.
- **Quality control (QC)** asks: *"Is the data inside this file actually
  good?"* — clean signal, sensible trial timing, no equipment glitches.
  That's a separate, later step (see the [Interactive QC
  Plan](crane_interactive_qc_plan.md) for the sibling tool being built for
  Crane's version of this).

Crosschecking always happens first: there's no point quality-checking a
recording that turns out to be the wrong one.

## How to do a crosscheck

!!! tip "Not sure what a button or icon does?"
    Hover your cursor over any icon or button in the tool — a short tooltip
    explains what it does before you click it.

### 1. Open the tool

With your Python environment set up (see [Getting
Started](getting-started.md) if you haven't done this yet), open a terminal
and type:

```bash
mobi_foh_bids_crosscheck
```

The tool remembers the last BIDS folder you had open, so after your first
time using it, it'll usually open straight to where you left off.

### 2. Point it at your BIDS folder

If nothing loads automatically, click **Browse...** at the top and select
your FOH BIDS folder.

### 3. Read the subject list

The left-hand panel lists every subject, with a small icon (or icons) next
to each one telling you, at a glance, whether it needs your attention:

| Icon | Meaning |
| --- | --- |
| ● | Fine — exactly one recording found, nothing to do. |
| ○ | Missing — no recording found at all for this subject. |
| ⚠ | Needs a decision — more than one recording was found. |
| ⏳ | You've picked one, but haven't saved that choice yet. |
| ☑ | You've personally reviewed and approved this one. |
| 🏷 | Whichever recording currently counts as "the one" hasn't been tagged FOH yet. |

That last one matters even for a subject that otherwise looks fine (●) — a
single recording being *found* doesn't mean it was ever confirmed and tagged
as the real FOH recording, so it stays flagged until you either tag it or
consciously decide it doesn't need to be. Tick **Issues only** and it'll show
up there too, alongside missing/duplicate subjects.

The **Info** column next to it shows useful details for whichever
recording currently counts as "the one" — when it was recorded, how long
it ran, and which data streams it actually contains (shown as ticks and
crosses) — so you don't have to open a file yourself to get a sense of
whether it's the real one.

Tick **Issues only** above the list to hide every subject that's already
fine, so you only see the ones that need a decision.

### 4. Click a subject to see its details

The right-hand panel shows full detail for whichever subject is selected
on the left. If there's more than one recording, you'll see each one
listed with its own date, length, and stream information side by side, so
you can compare them directly.

### 5. Pick the right recording

Click the button next to the correct recording. This doesn't save
anything yet — it's a preview, marked with the ⏳ icon, so you can change
your mind before committing to it.

### 6. Check the OpenSignals detail before saving

Once a recording counts as "the one" for a subject — either it was the
only candidate, or you've picked it with the radio button — a small panel
appears below the buttons with extra detail about its `OpenSignals`
stream: the column names it reports (e.g. `nSeq, EDA0, ECG1`) and its
sampling rate, shown as *effective* (measured from the file's actual
timestamps) versus *specified* (what the recording said it would be).

If those two rates disagree by more than 10%, the effective rate is shown
in red — a sign the recording may have dropped samples or had some other
timing problem, worth a second look before you commit to it.

### 7. Save your decision

Once you're confident, click **"Move non-selected to junk"** for that one
subject — this moves the other recording(s) aside into a `crosscheck_junk`
folder (nothing is ever deleted) and records your decision.

If you've gone through several subjects and picked a recording for each
without saving as you went, you don't have to repeat that per subject —
click **"Commit all pending selections"** near the top of the window to
save everything you've picked in one go. Because that affects every
subject with a pending pick at once, it'll ask you to confirm before doing
anything.

!!! note "Didn't get to finish?"
    If you close the tool with picks still pending (still showing the ⏳
    icon), that's fine — they aren't lost. The tool remembers them and
    they'll still be there, still pending, next time you open it.

### 8. Mark a subject as reviewed (optional)

Independent of picking a recording, you can click **"Mark crosschecked"**
on any recording to record that you've personally looked at and approved
it — shown afterwards as a ☑. This is a manual note for your own or your
team's reference; it doesn't change anything else. Click the same button
again to remove the mark.

### 9. Fix an obviously wrong date or ID

If a recording's filename has the wrong date in it, click
**"Correct date..."** next to it and type the right one. If a whole
subject's ID is wrong, use **"Rename subject ID..."** at the bottom of
the detail panel — this renames every file for that subject, plus their
folder, all at once.

### 10. Tag files as FOH

Once you're confident a recording is the right one, click
**"Rename to FOH"** next to it to add the `_FOH` tag to its filename —
a separate, permanent record from crosschecking itself.

Tagged the wrong recording, or tagged one that turns out not to be a real
FOH recording after all? The same button turns into **"Un-mark as FOH"**
once a file carries the tag — click it to strip the tag back off and
restore the original filename. The 🏷 icon comes back on that subject
until you tag the right one (or decide none of its candidates should be).

If you'd rather do this for every subject in one pass instead of
file-by-file, click **"Rename all selected to FOH"** near the top of the
window (next to "Commit all pending selections"). It walks every subject,
tags whichever recording currently counts as "the one," and skips
anything already tagged — and, like "Commit all pending selections," it
asks you to confirm first since it touches every subject at once. It only
ever adds tags, never removes them, so an accidental tag still needs
undoing by hand with "Un-mark as FOH."

## A sibling tool for Crane

The Crane experiment has its own equivalent tool, `vrlab_crane_bids_crosscheck`
— same idea, same layout, just checking `physiology`/`behaviour`/`debrief`
files instead of a single FOH recording. Everything on this page applies
there too, once Crane's raw-to-BIDS conversion exists (see [BIDS Converter
Plan](bids_converter_plan.md) — that part isn't built yet).

---

**Also see:** [BIDS Crosscheck Plan](bids_crosscheck_plan.md) for the
original design decisions behind this tool, and [BIDS Crosscheck:
Architecture](bids-crosscheck-architecture.md) if you're looking to change
how it works rather than just use it.
