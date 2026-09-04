# For Contributors

The rest of this site is about *running* and *understanding* the pipeline.
This page is for anyone going one step further: **changing** the code and
sharing that change back. If you're only running the pipeline, you can
skip this page.

If you haven't set up a coding environment for this project yet, start with
[Development Setup](dev-setup.md) first. Before you write any code, also
read [AI Use Guidelines](ai-use.md) — this project has a specific stance on
how (and how little) AI coding assistants should be involved in writing
that code.

## What is "origin"?

When you clone this repo, git automatically gives the place you cloned it
*from* (the shared copy, e.g. on GitHub) a nickname: **`origin`**. You can
see it yourself:

```bash
git remote -v
```

`git push`/`git pull` talk to `origin` by default. It's just a label — you
could rename it — but in practice almost every repo calls its main remote
`origin`, so you can treat the two as synonyms.

## Branch before a risky change

[Golden Rules](golden-rules.md#write-code-for-today-not-for-a-hypothetical-future)
already covers *why* to change one thing at a time. This is the *how*, for
a change big enough that the codebase might not work halfway through it —
a refactor that touches several files, say.

**Don't do risky work directly on `master`.** Branch first, so `master`
stays in a working state for everyone else the whole time you're mid-change:

```bash
git checkout -b refactor/my-change
```

(`refactor/...` is just a naming convention — it signals "this branch might
be broken partway through" to anyone who sees it. Use whatever prefix this
project already uses if one exists, e.g. `fix/...` for a bug fix.)

Work and commit normally on that branch. Push it to `origin` early, so it's
backed up and visible, even before it's finished:

```bash
git push -u origin refactor/my-change
```

(`-u` links your local branch to `origin/refactor/my-change`, so plain
`git push`/`git pull` work without extra arguments afterwards.)

### Keeping your branch up to date with `master`

If `master` moves on while you're working, pull those changes into your
branch periodically — don't wait until the end and face one huge conflict:

```bash
git checkout refactor/my-change
git pull origin master
```

This merges `master`'s latest commits into your branch. Resolve any
conflicts there, on your branch, while the change is still fresh in your
head — not weeks later when you finally try to merge back.

### Merging back to `master`

Once your branch is working again, don't merge it back with a raw
`git merge` on your own machine — open a **pull request** instead (next
section), so someone else can look at the change before it lands on
`master`.

## Pull requests

A **pull request (PR)** is a request to merge one branch into another —
almost always your branch into `master` here — reviewed by someone before
it's merged. It's the standard way changes reach `master` on GitHub.

Using [`gh`](testing.md#installing-github-cli-gh) (installed on the
[Testing](testing.md) page):

```bash
git push -u origin refactor/my-change   # if you haven't already
gh pr create
```

`gh pr create` walks you through a title and description, then opens the
PR on GitHub. From there:

1. Wait for review (and CI, if configured) — someone reads your diff and
   leaves comments or approves it.
2. Address any feedback with more commits on the same branch — they're
   added to the same PR automatically.
3. Once approved, merge it (via the GitHub web UI, or `gh pr merge`).

You can also open a PR straight from the browser after pushing a branch —
GitHub usually shows a prompt for it — `gh pr create` is just the
terminal-only route.

---

**Next: [Building & Releasing](packaging.md)** — how a merged change
actually turns into a distributable `.exe`.
