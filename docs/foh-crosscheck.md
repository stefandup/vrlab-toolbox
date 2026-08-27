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

### 2. Point it at your raw folder and import

FOH recordings arrive from the recording software already named and laid
out the real BIDS way (`sub-XXX/ses-.../eeg/sub-XXX_ses-..._eeg.xdf`,
possibly with an `_old1`, `_old2`, ... suffix if a session was
restarted) — but that's still **raw** data: nobody's looked at it yet,
duplicates and all, and it hasn't been through the crosscheck decisions
below. To keep that raw data untouched while you work, this tool always
crosschecks a separate **BIDS folder**, and copies new subjects into it
from your **raw folder** on request rather than working on the raw
folder directly.

Click **Browse...** next to **Raw folder** and select the folder your
recordings actually land in, then click **Refresh BIDS**. This copies
every subject not already in your BIDS folder across, whole and
untouched — files already imported are never re-copied, overwritten, or
even looked at again, so a crosscheck decision you've already made (a
pick, a tag, a correction) can never be clobbered by re-running this.
Nothing in the raw folder is ever changed or deleted by this step. The
**Last conversion** panel below the subject details shows exactly what
the last click did — which subjects were added, which were already
there and skipped.

Safe to click any time, including repeatedly (e.g. once more recordings
have come in) — there's no harm in clicking it and finding nothing new.

### 3. Point it at your BIDS folder

If nothing loads automatically, click **Browse...** at the top and select
your FOH BIDS folder — the destination folder from step 2 above, not the
raw one. This is the folder every step from here on actually works with.

The tool also makes sure a `.bidsignore` file at the top of that folder
lists its own files — `crosscheck.json`, `crosscheck_pending.json`,
`crosscheck_junk/`, `crosscheck_review/`, and its cached recording info —
appending to `.bidsignore` if one already exists (without touching
anything else in it) or creating one if not, so a BIDS validator doesn't
flag them as unexpected.

### 4. Read the subject list

Above the list, a summary line gives you the folder's overall state at a
glance — total subject count, how many recordings were found — and, in
**bold red**, how many subjects still need crosschecking (i.e. haven't
been marked ☑ for every scan type). That count disappears once everyone's
been reviewed.

The left-hand panel lists every subject, with a small icon (or icons) next
to each one telling you, at a glance, whether it needs your attention:

| Icon | Meaning |
| --- | --- |
| ● | Fine — exactly one recording found, nothing to do. |
| ○ | Missing — no recording found at all for this subject. |
| ⚠ | Needs a decision — more than one recording was found. |
| ⏳ | You've picked one, but haven't saved that choice yet. |
| ☑ | You've personally reviewed and approved this one. |
| 🏷 | Whichever recording currently counts as "the one" hasn't been tagged foh yet. |
| ❗ | Whichever recording currently counts as "the one" has a flagged issue — a sampling-rate mismatch, or a missing EDA/ECG channel — worth a look before you commit to it. |

That last one matters even for a subject that otherwise looks fine (●) — a
single recording being *found* doesn't mean it was ever confirmed and tagged
as the real foh recording, so it stays flagged until you either tag it or
consciously decide it doesn't need to be. Tick **Issues only** and it'll show
up there too, alongside missing/duplicate subjects.

The **Tag** column shows, at a glance, whether the recording currently
counts as "the one" has been tagged yet — either the tag itself (e.g.
`foh`) once it has, or **not tagged** in orange if it hasn't (the same
thing the 🏷 icon flags, spelled out here so you don't have to hover the
icon legend to remember what it means).

The **Datatype** column shows which BIDS *datatype* folder that
recording's file currently lives in — `eeg` at first, since that's the
name the collection software always uses (see [step
12](#12-tag-files-as-foh) for why that's not accurate for FOH data, and
what it becomes once tagged). "Datatype" is BIDS's own term for this —
the `eeg`/`beh`/`func`/... subfolder a recording sits in, not a filename
thing. Hover a value to see what it means and, if it's about to change,
what it'll change to.

The **Info** column next to it shows a quick summary for whichever
recording currently counts as "the one" — the date and time it was
recorded, how long it ran (in minutes), and how many of the streams the
pipeline needs were actually found, e.g. `Streams: 4/4 ✓` (or ✗ if any are
missing).
Hover over that summary for the full breakdown, stream by stream — so you
don't have to open a file yourself to get a sense of whether it's the
real one.

The tool remembers this per-recording info between launches, so
re-opening a folder you've already looked at is fast rather than
re-reading every recording from scratch. If a recording's actual file has
changed since the tool last read it, click **Refresh** in the **Subject
actions** panel (see below) to make it look again.

Tick **Issues only** above the list to hide every subject that's already
fine, so you only see the ones that need a decision.

### 5. Click a subject to see its details

The right-hand panel shows full detail for whichever subject is selected
on the left. If there's more than one recording, you'll see each one
listed with its own date, length, and stream information side by side, so
you can compare them directly.

(You can also select more than one subject at once — Ctrl-click or
Shift-click in the list — for bulk actions across your selection. See
[Working with several subjects at once](#working-with-several-subjects-at-once)
below.)

### 6. Pick the right recording

Click the button next to the correct recording. This doesn't save
anything yet — it's a preview, marked with the ⏳ icon, so you can change
your mind before committing to it.

### 7. Check the recording detail before saving

Once a recording counts as "the one" for a subject — either it was the
only candidate, or you've picked it with the radio button — a small panel
appears below the buttons with a fuller breakdown than the compact
summary in the subject list:

- Which of the streams the pipeline needs were found in this recording,
  each shown with its own tick or cross.
- For the `OpenSignals` stream specifically: the column names it reports
  (e.g. `nSeq, EDA0, ECG1`), whether the EDA and ECG channels the pipeline
  actually reads were found among them — matched even if the recording
  device added a trailing channel number, like `EDA0` or `ECG1`, rather
  than needing an exact name match — and its sampling rate, shown as
  *effective* (measured from the file's actual timestamps) versus
  *specified* (what the recording said it would be).

If the sampling rate disagrees by more than 10%, or either channel is
missing, that's shown in red, and the subject picks up a ❗ next to its
name in the subject list — worth a second look before you commit to it.

### 8. Save your decision

Once you're confident, click **"Move non-selected to crosscheck_review"**
in the **Subject actions** panel (above the recording detail) — this
moves the other recording(s) aside into a `crosscheck_review` folder
(nothing is ever deleted) and records your decision. It only appears
enabled once you've actually picked something; the button's label counts
your pending picks so you can see at a glance whether there's anything to
save.

!!! note "What's crosscheck_review/, and why not junk?"
    `crosscheck_review/` is a folder this tool creates at the top of your
    BIDS folder to hold recordings that weren't picked. It's deliberately
    a separate concept from **junk**: a duplicate that wasn't picked isn't
    necessarily wrong, just not the recording being used — you might not
    be fully sure it should be ruled out entirely. Putting it in
    `crosscheck_review/` keeps it easy for a second crosschecker to find
    and double-check later, rather than quietly mixed in with data that's
    genuinely disposable (a pilot run, a non-participant). That's what
    **junk** is for instead — see [step 13](#13-send-a-subject-to-junk) —
    and it's a separate, deliberate action, not something committing a
    pick ever does on its own.

    Nothing moves the moment you *pick* a candidate (step 6) — picking is
    just a preview. Files stay exactly where they are until you actually
    click a "...to crosscheck_review" button.

If you've gone through several subjects and picked a recording for each
without saving as you went, you don't have to repeat that per subject —
click **"Move all non-selected to crosscheck_review"** near the top of
the window to save everything you've picked in one go, or select just the
ones you want first and use **"Commit selected to crosscheck_review"** in
the Subject actions panel instead (see [Working with several subjects at
once](#working-with-several-subjects-at-once) below). Because either of
those affects more than one subject at once, both ask you to confirm
before doing anything — the single-subject version above doesn't, since
it's already a deliberate one-at-a-time click.

!!! note "Didn't get to finish?"
    If you close the tool with picks still pending (still showing the ⏳
    icon), that's fine — they aren't lost. The tool remembers them and
    they'll still be there, still pending, next time you open it.

### 9. Mark a subject as reviewed (optional)

Above the recording detail, the **Subject actions** panel holds actions
that apply to the whole subject rather than one specific recording:
marking it reviewed, renaming its ID, re-reading its info from disk if a
recording has changed since the tool last looked (**Refresh**), and
sending it to junk (see [step 13](#13-send-a-subject-to-junk) below). It
stays visible at a fixed spot regardless of what's selected — blank when
nothing is, so there's no jumping around as you click between subjects.

Click **"Mark crosschecked"** there to record that you've personally
looked at this subject and approved it — shown afterwards as a ☑ next to
its name in the subject list. This is a manual note for your own or your
team's reference; it doesn't change anything else. Click the same button
again ("Un-mark crosschecked") to remove the mark.

### 10. Look at the files yourself

Click **"Reveal subject folder"** next to a recording to open that
subject's folder — inside your **BIDS folder**, not the raw one — in
your system's file browser (Explorer on Windows, Finder on macOS) —
useful if you want to check something the tool doesn't show, or just
confirm what's actually sitting on disk.

### 11. Fix an obviously wrong date or ID

If a recording's filename has the wrong date in it, click
**"Correct date..."** next to it and type the right one. If a whole
subject's ID is wrong, use **"Rename subject ID..."** in the **Subject
actions** panel — this renames every file for that subject, plus their
folder, all at once. (This one's single-subject only: it doesn't appear
when several subjects are selected, since renaming several different
subjects to the same new ID wouldn't make sense.)

!!! note "Why don't I see \"Correct date...\" next to every candidate?"
    For a subject with more than one candidate recording, **"Correct
    date..."** (and **"Tag as foh"**, see below) only appears next to
    whichever one you've picked with the radio button — there's nothing to
    correct on a file you haven't confirmed is the right one yet. Pick it
    first (step 6), and the button appears.

### 12. Tag files as foh

Once you're confident a recording is the right one, click **"Tag as
foh"** next to it. This replaces whatever comes after the `run-<NNN>`
part of the filename with `_foh` — so `..._run-001_eeg_philani.xdf`
becomes `..._run-001_foh.xdf`, not `..._run-001_eeg_philani_foh.xdf`. The
collection software often tacks on extra free text there (a device
suffix, a collector's name), which isn't a valid BIDS suffix; tagging
cleans that up at the same time as marking the file, rather than tagging
on top of it. Lowercase, matching BIDS's own suffix convention (`eeg`,
`beh`, ...) — "FOH" the study name stays capitalized everywhere else on
this page; this is just the filename tag.

!!! note "What's the eeg -> beh folder switch about?"
    The folder the file lives in gets renamed too, from `eeg` to `beh` —
    you'll see this reflected immediately in the **Datatype** column
    (step 4). The raw collection software always names this folder `eeg`,
    no matter what's actually recorded in it. For FOH that's simply
    wrong: this is physiology data, sometimes with behavioural data,
    collected over LSL — not brain activity, not EEG. `beh` ("behavioural"
    in BIDS's own vocabulary) is the accurate datatype for that once a
    recording's confirmed, so tagging fixes the folder name at the same
    time it fixes the file name.

    Nothing else in that folder gets left behind: any other file still
    sitting there — an unresolved duplicate you haven't picked yet, say —
    moves along with the folder rather than being separated from it.
    Un-tagging (below) renames the folder back to `eeg`.

Tagged the wrong recording, or tagged one that turns out not to be a real
foh recording after all? The same button turns into **"Un-tag as foh"**
once a file carries the tag — click it to restore the original filename
(the tool remembers what that was when it tagged the file, even though
it's no longer visible in the current name) and strip the tag back off.
The 🏷 icon comes back on that subject until you tag the right one (or
decide none of its candidates should be).

If you'd rather do this for every subject in one pass instead of
file-by-file, click **"Tag all selected as foh"** near the top of the
window (next to "Move all non-selected to crosscheck_review"). It walks
every subject, tags whichever recording currently counts as "the one,"
and skips anything already tagged — and, like "Move all non-selected to
crosscheck_review," it asks you to confirm first since it touches every
subject at once. It only ever adds tags, never removes them, so an
accidental tag still needs undoing by hand with "Un-tag as foh."

Only want to tag the subjects you've currently selected rather than the
whole folder? Select them in the subject list first, then use **"Tag
selected as foh"** in the **Subject actions** panel instead — same
behaviour, just scoped to your selection.

### 13. Send a subject to junk

Sometimes a whole subject doesn't belong in the folder at all — a test
recording that got saved alongside real data, or someone who was never
really a participant. The **Subject actions** panel has two ways to
remove one:

- **"Send to junk..."** moves the subject's entire folder into
  `crosscheck_junk/`, out of this view.
- **"Mark as non-participant / non-foh and junk..."** does the same
  thing, but records *why* first, so anyone looking in the junk folder
  later can see it wasn't just an ordinary duplicate cleanup.

Both ask you to confirm first, and — like everything else this tool
moves — nothing is ever deleted. If you junked the wrong subject, their
folder is still sitting in `crosscheck_junk/`; move it back by hand.

### 14. Restore from junk, restore from review, or revert everything

Made a mistake and want to start over? Four buttons near the top of the
window, next to "Move all non-selected to crosscheck_review," cover the
whole folder at once:

- **"Restore all from junk..."** moves everything currently sitting in
  `crosscheck_junk/` back to where it came from — whole subjects sent
  there with "Send to junk..." (step 13).
- **"Restore all from review..."** does the same thing for
  `crosscheck_review/` (step 8) — its own separate button, so restoring
  one never accidentally pulls back the other.
- **"Permanently delete review..."** — see the warning below. This one's
  different from everything else in this list.
- **"Revert all changes..."** reverses every recorded rename — corrected
  dates, corrected IDs, foh tags — and clears every recorded decision,
  including crosschecked marks.

!!! warning "Bulk only, for this version at least"
    None of the restore/revert buttons let you pick and choose. **"Restore
    all from junk"** and **"Restore all from review"** each bring back
    everything in their own folder, not just one subject's files.
    **"Revert all changes"** reverses everything recorded, not just one
    decision — and only the *most recent* recorded decision for each
    subject/scan-type can be reversed, since each new correction overwrites
    the previous record rather than keeping a history. A recording that
    was, say, date-corrected and *then* tagged foh can only be reverted
    back to its date-corrected state, not all the way back to its very
    first filename.

    Junked and review-folder files aren't touched by "Revert all
    changes" — if you want everything back, restore those first.

!!! danger "\"Permanently delete review\" cannot be undone"
    Every other button on this page moves files somewhere recoverable —
    that's the whole point of junk and review folders, and it's why this
    page keeps saying "nothing is ever deleted." This one button is the
    single exception: it deletes whatever's currently in
    `crosscheck_review/` for good, not moved anywhere, not recoverable by
    hand afterwards. Only use it once a second crosschecker has actually
    gone through the review folder and confirmed there's nothing in it
    worth keeping.

## Working with several subjects at once

Click a subject to select it, or Ctrl-click (or Shift-click for a range)
to select several at once. With more than one selected, the detail panel
switches to a **"Subject actions — N subjects selected"** panel with bulk
versions of the actions above: **Commit selected to crosscheck_review**,
**Refresh**, **Tag selected as foh**, **Mark selected crosschecked** /
**Un-mark selected crosschecked**, and **Send selected to junk...**.

Two things stay single-subject only, on purpose:

- **Renaming a subject's ID** — renaming several different subjects to
  the same new ID wouldn't make sense.
- **Picking which recording is the right one** for a subject with more
  than one candidate — that judgement call always stays in the
  per-subject recording panel, never a bulk action. A subject still
  waiting on that pick is simply skipped by any bulk action that needs an
  actual file to work with (e.g. **Commit selected to crosscheck_review**
  or bulk FOH-tagging).

## A sibling tool for Crane

The Crane experiment has its own equivalent tool, `vrlab_crane_bids_crosscheck`
— same idea, same layout (including its own raw folder + "Refresh BIDS"
step), just checking `physiology`/`behaviour`/`debrief` files instead of a
single FOH recording, and its raw-to-BIDS step does real reshaping rather
than a plain copy (see [BIDS Converter Plan](bids_converter_plan.md) for
what differs). Everything else on this page applies there too.

---

**Also see:** [BIDS Crosscheck Plan](bids_crosscheck_plan.md) for the
original design decisions behind this tool, and [BIDS Crosscheck:
Architecture](bids-crosscheck-architecture.md) if you're looking to change
how it works rather than just use it.
