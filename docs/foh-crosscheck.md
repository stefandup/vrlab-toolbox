# FOH Crosscheck

This is step 1: before your data can be [processed](processing.md), your
raw recordings need to be converted into BIDS and crosschecked. This page
is for anyone using the FOH Crosscheck tool to do that — no coding
background needed. If you haven't already, read
[Crosschecking](crosschecking.md) first — it covers what crosschecking
means and why it matters in general; this page picks up from there with
what's specific to FOH and the actual walkthrough.

!!! info "The raw folder is never changed — not once, not ever"
    Worth repeating here: nothing on this page ever writes to, renames, or
    deletes anything in your **raw folder**. See
    [Crosschecking](crosschecking.md#what-is-crosschecking) for the full
    explanation of why that's safe.

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

## How to do a crosscheck

!!! tip "Not sure what a button or icon does?"
    Hover your cursor over any icon or button in the tool — a short tooltip
    explains what it does before you click it.

### 1. Open the tool

With the toolbox installed (see [Getting
Started](getting-started.md) if you haven't done this yet), open a terminal
and type:

```bash
vrlab_foh_bids_crosscheck
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

Once a raw folder is picked, **Reveal Raw Folder** next to it opens that
folder in your system's file browser (Explorer on Windows, Finder on
macOS) — handy if you want to look at what's actually in there yourself.

### 3. Point it at your BIDS folder

If nothing loads automatically, click **Browse...** at the top and select
your FOH BIDS folder — the destination folder from step 2 above, not the
raw one. This is the folder every step from here on actually works with.
**Reveal BIDS Folder** next to it opens that folder in your system's file
browser, the same as **Reveal Raw Folder** does for the raw one.

The tool also makes sure a `.bidsignore` file at the top of that folder
lists its own files — `crosscheck.json`, `crosscheck_pending.json`,
`excluded_subjects.json`, and its cached recording info — appending to
`.bidsignore` if one already exists (without touching anything else in
it) or creating one if not, so a BIDS validator doesn't flag them as
unexpected.

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
12](#12-tag-files-with-real-bids-tags) for why that's not accurate for FOH data, and
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

Once you're confident, click **"Remove non-selected files from BIDS"**
in the **Subject actions** panel (above the recording detail) — this
deletes the other recording(s) from your BIDS folder and records your
decision. Nothing is lost: the raw folder (step 2) is never touched by
this tool, so a removed recording is always still sitting there if you
ever need it back — see [step 14](#14-restore-a-subjects-duplicate-pick) to
bring it back into BIDS. It only appears enabled once you've actually
picked something; the button's label counts your pending picks so you
can see at a glance whether there's anything to save.

!!! note "Why delete instead of moving it aside?"
    Earlier versions of this tool moved a non-picked duplicate into a
    `crosscheck_review/` folder inside BIDS instead of deleting it. That
    turned out to be redundant: the raw folder is never touched by this
    tool either way, so it was already the recoverable copy. Deleting the
    BIDS-side copy keeps things simpler — there's just your raw folder and
    your BIDS folder, nothing in between.

    Nothing moves the moment you *pick* a candidate (step 6) — picking is
    just a preview. Files stay exactly where they are until you actually
    click a "Remove non-selected..." button.

If you've gone through several subjects and picked a recording for each
without saving as you went, you don't have to repeat that per subject —
click **"Remove non selected files from BIDS"** near the top of
the window to save everything you've picked in one go, or select just the
ones you want first and use **"Remove non-selected files from BIDS for
selected"** in the Subject actions panel instead (see [Working with
several subjects at once](#working-with-several-subjects-at-once) below).
Because either of those affects more than one subject at once, both ask
you to confirm before doing anything — the single-subject version above
doesn't, since it's already a deliberate one-at-a-time click.

!!! note "Didn't get to finish?"
    If you close the tool with picks still pending (still showing the ⏳
    icon), that's fine — they aren't lost. The tool remembers them and
    they'll still be there, still pending, next time you open it.

### 9. Mark a subject as reviewed (optional)

Above the recording detail, the **Subject actions** panel holds actions
that apply to the whole subject rather than one specific recording:
marking it reviewed, renaming its ID, re-reading its info from disk if a
recording has changed since the tool last looked (**Refresh**), undoing a
duplicate pick already committed (**Restore from raw...**, see [step
14](#14-restore-a-subjects-duplicate-pick)), and removing it from BIDS
entirely (see [step 13](#13-remove-a-subject-from-bids) below). It
stays visible at a fixed spot regardless of what's selected — blank when
nothing is selected, and titled with the subject's ID when exactly one
is, so there's no jumping around or losing track of who it applies to as
you click between subjects.

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
    date..."** (and **"Tag with foh BIDS tags"**, see below) only appears
    next to whichever one you've picked with the radio button — there's
    nothing to correct on a file you haven't confirmed is the right one
    yet. Pick it first (step 6), and the button appears.

### 12. Tag files with real BIDS tags

Once you're confident a recording is the right one, click **"Tag with
foh BIDS tags"** next to it. This inserts a `task-foh` entity (and an
`acq-lsl` entity, since this was collected over Lab Streaming Layer) just
before the `run-<NNN>` part of the filename, and replaces whatever comes
after it with the real BIDS suffix `beh` — so
`..._run-001_eeg_philani.xdf` becomes
`..._task-foh_acq-lsl_run-001_beh.xdf`, not
`..._run-001_eeg_philani_foh.xdf`. The collection software often tacks on
extra free text after the run number (a device suffix, a collector's
name), which isn't valid BIDS; tagging cleans that up at the same time as
marking the file, rather than tagging on top of it.

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
    Removing the tag (below) renames the folder back to `eeg`.

Tagged the wrong recording, or tagged one that turns out not to be a real
foh recording after all? The same button turns into **"Remove foh BIDS
tags"** once a file carries the tag — click it to restore the original
filename (the tool remembers what that was when it tagged the file, even
though it's no longer visible in the current name) and strip the tags
back off. The 🏷 icon comes back on that subject until you tag the right
one (or decide none of its candidates should be).

If you'd rather do this for every subject in one pass instead of
file-by-file, click **"Tag all selected with foh BIDS tags"** near the
top of the window (next to "Remove non selected files from BIDS"). It
walks every subject, tags whichever recording currently counts as "the
one," and skips anything already tagged — and, like "Remove non selected
files from BIDS," it asks you to confirm first since it touches every
subject at once. It only ever adds tags, never removes them, so an
accidental tag still needs undoing by hand with "Remove foh BIDS tags."

Only want to tag the subjects you've currently selected rather than the
whole folder? Select them in the subject list first, then use **"Tag
selected with foh BIDS tags"** in the **Subject actions** panel instead —
same behaviour, just scoped to your selection.

### 13. Remove a subject from BIDS

Sometimes a whole subject doesn't belong in the folder at all — a test
recording that got saved alongside real data, or someone who was never
really a participant. Click **"Remove Subject Folder from BIDS..."** in
the **Subject actions** panel — this deletes the subject's entire folder
from BIDS (their raw recording is untouched, and still sitting in the raw
folder from step 2) and asks you for an optional reason first, so it's
clear later why they were removed. Leave the reason blank and click OK if
you don't need to record one, or Cancel to back out without removing
anything.

Removing a subject this way has no in-app undo — if you removed the wrong
one, see the warning box in [step
14](#14-restore-a-subjects-duplicate-pick) below for how to bring them
back.

### 14. Restore a subject's duplicate pick

Only one kind of undo is built into the tool: select a subject (or a few,
with Ctrl-click) and click **"Restore from raw..."** (or **"Restore
selected from raw..."** for more than one) in the **Subject actions**
panel. This only works for a subject who's still visible in the list with
a duplicate already resolved (step 8) — it clears the bookkeeping for just
them, leaving every other subject's decisions untouched, so click
**Refresh BIDS** (step 2) afterward to bring their full record back in
fresh. Because it re-derives their *whole* folder, not just the one file
that was removed, any other decision already made for them (a corrected
date, a crosschecked mark, another scan type's pick) goes with it and
needs redoing too.

!!! warning "Nothing else is undoable in-app"
    A whole subject removed entirely (step 13), or files removed by
    **"Remove non-selected files from BIDS"** (step 8), have no in-app
    undo — treat both as permanent. Your raw folder is still completely
    untouched either way (that's the guarantee at the top of this page),
    so nothing is actually lost — but bringing that data back into BIDS
    means re-running the raw-to-BIDS setup by hand: point the tool at a
    fresh, empty BIDS folder (or delete the old one) and click **Refresh
    BIDS** to rebuild from raw. See [Backing up, and rebuilding after a
    lost BIDS folder](#backing-up-and-rebuilding-after-a-lost-bids-folder)
    below for restoring your crosscheck *decisions* into that fresh
    rebuild too, so you don't have to redo them by hand.

### Backing up, and rebuilding after a lost BIDS folder

This is the payoff of the rule at the top of this page — **the raw folder
is never touched** — spelled out concretely: everything in your BIDS
folder is either raw data (already safe, and reproducible any time by
re-running "Refresh BIDS") or bookkeeping this tool writes as you work.
Only that bookkeeping is unique and worth backing up on its own: click
**"Save Crosscheck Data"** in the **General Actions** panel near the top
of the window — no folder to pick, it copies the small set of files that
record every decision you've made into the app's own local data folder,
identified by the **Study ID** you've set for this BIDS folder. Tick
**Auto-save** next to it to do this automatically on an interval instead
of remembering to click it yourself.

If the BIDS folder itself is ever lost or corrupted, point the tool at a
fresh, empty BIDS folder with the *same* Study ID and click **"Restore
Saved Crosscheck Data"**. This re-imports fresh from your raw folder, then
automatically replays every past pick, tag, and correction from your saved
data — you don't redo any of it by hand. It's only meant for a BIDS folder
that's empty or was just freshly created, not for merging saved data into
one that already has its own, different state.

!!! note "Want a completely fresh start instead?"
    There's no single "clear everything and start over" button in this
    tool, on purpose. Restoring and reverting (above) only ever undo
    *decisions* — they always leave your raw folder as the source of
    truth and re-derive from it, which is safe by design. A full wipe is
    a different, much blunter kind of action: it would throw away
    perfectly good, already-checked work for subjects who were never a
    problem in the first place, just to fix a handful that were. Building
    that safely (so a room full of people can't wipe real results with
    one stray click) is more machinery than it's worth for something you
    can already do yourself, just as safely, outside the tool: **point it
    at a brand-new, empty BIDS folder** (create one anywhere and click
    **Browse...** to it), or **delete the old BIDS folder yourself** and
    let **Refresh BIDS** rebuild it from scratch. Either way, your raw
    folder is never touched, so nothing is actually at risk — you're just
    choosing to throw away the BIDS-side bookkeeping and start over. This
    is especially handy for a test/practice BIDS folder while you're
    still learning the tool — delete it and start fresh as often as you
    like.

## Working with several subjects at once

Click a subject to select it, or Ctrl-click (or Shift-click for a range)
to select several at once. With one subject selected, the panel's title
shows their ID, so you always know who the buttons below it apply to;
with more than one, it switches to a **"Subject actions — N subjects
selected"** panel with bulk versions of the actions above: **Remove
non-selected files from BIDS for selected**, **Refresh**, **Tag selected
with foh BIDS tags**, **Mark selected crosschecked** / **Un-mark selected
crosschecked**, **Restore selected from raw...**, and **Remove selected
from BIDS...**.

Two things stay single-subject only, on purpose:

- **Renaming a subject's ID** — renaming several different subjects to
  the same new ID wouldn't make sense.
- **Picking which recording is the right one** for a subject with more
  than one candidate — that judgement call always stays in the
  per-subject recording panel, never a bulk action. A subject still
  waiting on that pick is simply skipped by any bulk action that needs an
  actual file to work with (e.g. **Remove non-selected files from BIDS
  for selected** or bulk FOH-tagging).

## Crane has its own version of this tool

The Crane experiment has its own crosscheck tool, covered on its own page:
[Crane Crosscheck](crane-crosscheck.md). It's built the same way and works
the same way — same idea, same layout, same "raw folder is never touched"
guarantee — just checking `physiology`/`behaviour`/`debrief` files instead
of a single FOH recording. You may use FOH Crosscheck, Crane Crosscheck, or
both, depending on which experiment(s) your data comes from; neither tool
depends on the other.

---

**Next: [Crane Crosscheck](crane-crosscheck.md)** — the equivalent tool
for Crane data.

**Also see:** [BIDS Crosscheck Plan](bids_crosscheck_plan.md) for the
original design decisions behind this tool, and [BIDS Crosscheck:
Architecture](bids-crosscheck-architecture.md) if you're looking to change
how it works rather than just use it.
