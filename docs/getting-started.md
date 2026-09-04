# Getting Started

This page gets a toolbox tool onto your computer — no coding background
needed. Every tool here is a program you launch and point at a folder of
data, either by clicking through an installer or by typing one line into a
terminal window.

If you're setting up a full coding environment to change the toolbox's
code yourself, see [Development Setup](dev-setup.md) in **For
Contributors** instead — this page only covers running the tools as they
already are.

## How this fits together

Working with your data happens in three steps, always in this order:

1. **Prepare your data** — crosscheck your raw recordings and convert them
   into the standard folder layout analysis expects ("BIDS"). See
   [Crosschecking](crosschecking.md), then [FOH
   Crosscheck](foh-crosscheck.md) or [Crane Crosscheck](crane-crosscheck.md).
2. **Process your data** — run the processing tool for your experiment.
   See [Process Your Data](processing.md).
3. **Check your output** — review the QC plots the processing step
   produces before you trust the numbers. See [Check Your
   Output](eda.md).

The rest of this page just covers getting the toolbox installed; each step
above has its own page with the details.

## Installing the toolbox

A versioned installer, plus every tool's standalone `.exe` on its own, is
built automatically and attached to this repo's **GitHub Releases** page
every time a new version is published.

To get it:

1. On GitHub, open this repo's **Releases** page (the "Releases" link in
   the right-hand sidebar of the repo's main page, or `.../releases` at
   the end of the repo URL).
2. Pick the release you want — usually the latest one at the top.
3. Under **Assets**, download the installer (named e.g.
   `MooiToolboxSetup-v1.2.0.exe` — the version number matches the release
   you picked) and run it.

The installer puts every tool's `.exe` in one folder, adds that folder to
your `PATH` automatically (current user only — no admin rights needed), and
adds a desktop shortcut — look for this icon
![Mobi Mooi Toolbox icon](assets/images/vrlab_icon.ico){ width="24" } — to a
launcher with a button for each GUI tool (see [FOH
Crosscheck](foh-crosscheck.md) and [Crane
Crosscheck](crane-crosscheck.md)). Once it's done, open a **new** terminal
window (the `PATH` change only applies to terminals opened after
installing) and run a tool exactly like the commands used on the next
pages, for example:

```bash
vrlab_crane_process --version
```

### Checking it's the right file, and getting help

Two flags work without needing to run a full pipeline:

```bash
vrlab_crane_process --help       # lists every argument and option, with what each does
vrlab_crane_process --version    # confirms which version you downloaded
```

`--help` is the fastest way to check argument order or an option's name
without coming back to this page. `--version` is worth checking against
the release you meant to download, especially if more than one version's
`.exe` is floating around a shared machine.

!!! note "macOS/Linux"
    Only a Windows installer is currently built automatically. On other
    platforms, someone will need to build a standalone copy for you first —
    ask whoever manages the toolbox for your team.

---

**Next: [Crosschecking](crosschecking.md)** — step 1, preparing a raw
recording session before it's processed.
