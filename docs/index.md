# Welcome

![Mobi Mooi Toolbox icon](assets/images/vrlab_icon.ico){ width="96" }

The Mobi Mooi Toolbox turns raw recordings — physiology signals, VR event
logs, and questionnaire answers — into one clean, per-participant data file
that's ready for analysis, by running every participant's data through the
same fixed sequence of steps: find files, import, process, combine, and
save.

Curious *why* it's built this way before diving in? See
[Why This Toolbox Exists](philosophy.md).

## Who this is for

- **Just here to run a tool or check some data?** Start with [Getting
  Started](getting-started.md) — no coding background needed. **For
  Users** below covers everything from there.
- **Changing the code itself?** **For Contributors** below is for you.
  Look out for **Going further** boxes throughout those pages — they
  explain *why* the pipeline is built the way it is, not just what it
  does.

## Where to go next

Pages are ordered to be read straight through — each one links to the next
— but here's the map if you want to jump around.

**For everyone:** [Why This Toolbox Exists](philosophy.md) — worth reading
whether you're running the pipeline or changing it.

### For users

Running the tools and understanding what they show you — no code changes,
no coding background needed.

- **1. Get set up:** [Getting Started](getting-started.md)
- **2. Prepare your data:** [Crosschecking](crosschecking.md), [FOH Crosscheck](foh-crosscheck.md), [Crane Crosscheck](crane-crosscheck.md)
- **3. Process your data:** [Process Your Data](processing.md)
- **4. Check your output:** [EDA & SCRs](eda.md), [FOH Output Checks](foh-output.md), [Crane Output Checks](interval-qc.md)

### For contributors

Changing the code and sharing that change back.

- **AI use guidelines:** [AI Use Guidelines](ai-use.md), [AI Style Guide](ai-style-guide.md)
- **Set up a dev environment:** [Development Setup](dev-setup.md)
- **Understand the code:** [Code Organization](code-organization.md), [Golden Rules](golden-rules.md)
- **Understand the architecture:** [Pipeline Concepts](pipeline-concepts.md), [Design Patterns](design-patterns.md)
- **File matching & LSL internals:** [Pipeline Rules](pipeline-rules.md), [Lab Streaming (LSL/XDF)](lab-streaming.md)
- **Data classes:** [Data Stores](data-stores.md), [Core Data Classes](core-classes.md)
- **BIDS crosscheck internals:** [BIDS Crosscheck Architecture](bids-crosscheck-architecture.md)
- **GitHub guidelines:** [For Contributors](contributing.md)
- **Check it works:** [Testing](testing.md)
- **Look things up:** [API Reference](api-reference.md)
- **Build & release:** [Building & Releasing](packaging.md)

!!! note "Going further"
    This site itself is built with [MkDocs](https://www.mkdocs.org/) and the
    Material theme, and editing it is a contribution like any other. It only
    builds locally for now — see
    [Code Organization](code-organization.md#building-and-previewing-this-documentation-site)
    for why, and how to preview it yourself.

Ready? Start with **[Getting Started](getting-started.md)**.
