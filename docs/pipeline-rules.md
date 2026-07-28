# Pipeline Rules

Following on from [Golden Rules](golden-rules.md) and
[Code Organization](code-organization.md#where-the-actual-steps-live): now
that you know *where* the file-finding step lives, here's *what rules* it
actually follows. These are the rules the pipeline follows when it finds and matches each
participant's files — mostly enforced in
`ParticipantConfig.from_physiology_data` (`processing/input_data.py`). They
matter most if you're building tooling *around* the pipeline (for example,
the planned GUI): the pipeline currently enforces these rules quietly (a log
warning), not loudly (an error), so anything that reads results back out
needs to know they exist.

## Participant IDs must be alphanumeric

A participant ID containing anything other than letters and digits (spaces,
punctuation, etc.) triggers a warning, because filename matching depends on
the ID appearing cleanly inside filenames. Today this only *warns* — it
doesn't stop processing.

## Behaviour files must "date-match" the physiology file

Each participant's behaviour/debrief filenames are expected to share the
same date prefix as their physiology file. If a behaviour file's date
doesn't match, that's logged as a mismatch warning.

!!! note "Going further"
    This specific check has a known bug — see item 13 in
    [Next Steps](pipeline_next_steps.md#13-date-string-extraction-in-from_physiology_data-breaks-on-the-data-folders-path-separator).
    The rule (dates should match) is correct; today's implementation of the
    check isn't fully reliable yet.

## More than one matching file is treated as ambiguous

If a glob pattern matches more than one file for a participant, the
*first* match is used, and the rest are logged as a warning — nothing
prompts a human to pick. A GUI built on top of this should probably surface
that ambiguity directly, rather than silently trusting the first match.

## Missing files don't stop the pipeline

A missing physiology file or a missing behaviour file also only logs a
warning. The pipeline still returns a `ParticipantConfig`, and processing
continues with whatever partial data is available (see item 10 in
[Next Steps](pipeline_next_steps.md#10-document-intentional-behaviour-change-partial-data-now-survives-biopac-import-failure)
for what that means for the rest of the pipeline).

## Raw files are never changed

This one isn't in the code — it's a hard rule for anything built on top of
the pipeline: **raw participant data files are read-only.** Nothing in this
project should rename, edit, move, or delete a participant's original data
file. All output goes to `output_folder`, never back into the input data.

This matters directly for planned tooling like the file-rename helper in
[Next Steps item 14](pipeline_next_steps.md#14-write-a-rename-script-for-participant-files-with-label-mismatches):
even a script whose whole job is "fix mismatched filenames" must write
renamed *copies* elsewhere (or keep a mapping file), not rename files
in place.

!!! note "Going further"
    Right now these rules only produce log messages — there's no structured
    way for a caller (like a future GUI) to ask "did this participant's
    file-matching succeed, and if not, which rule was broken?" That's
    tracked as still-open work — see item 12 in
    [Next Steps](pipeline_next_steps.md#12-participantconfig-file-discovery-make-failures-report-status-instead-of-raising).

---

**Next: [Interval QC Plot](interval-qc.md)** — a second kind of matching,
lining up *time* instead of *files*, and the QC image the pipeline can
produce to check it.
