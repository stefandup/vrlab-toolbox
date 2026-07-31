# Welcome

The Mobi Mooi Toolbox turns raw recordings — physiology signals, VR event
logs, and questionnaire answers — into one clean, per-participant data file
that's ready for analysis, by running every participant's data through the
same fixed sequence of steps: find files, import, process, combine, and
save.

Curious *why* it's built this way before diving in? See
[Why This Toolbox Exists](philosophy.md).

## Who this is for

- **New to Python?** Start with [Getting Started](getting-started.md).
  These pages assume you can already run a Python script, but explain
  everything else as we go.
- **Comfortable with Python already?** Look out for **Going further** boxes
  throughout — they explain *why* the pipeline is built the way it is, not
  just what it does.

## Where to go next

Pages are ordered to be read straight through — each one links to the next
— but here's the map if you want to jump around.

**For everyone:** [Why This Toolbox Exists](philosophy.md) — worth reading
whether you're running the pipeline or changing it.

### For users

Running the pipeline and understanding its output — no code changes needed.

- **Run it:** [Getting Started](getting-started.md)
- **Understand the data:** [Pipeline Rules](pipeline-rules.md), [Interval QC Plot](interval-qc.md), [EDA & SCRs](eda.md), [Lab Streaming (LSL/XDF)](lab-streaming.md)
- **Check it works:** [Testing](testing.md)
- **Look things up:** [API Reference](api-reference.md)

### For contributors

Changing the code and sharing that change back.

- **AI use guidelines:** [AI Use Guidelines](ai-use.md), [AI Style Guide](ai-style-guide.md)
- **Understand the code:** [Code Organization](code-organization.md), [Golden Rules](golden-rules.md)
- **Understand the architecture:** [Pipeline Concepts](pipeline-concepts.md), [Design Patterns](design-patterns.md)
- **GitHub guidelines:** [For Contributors](contributing.md)
- **Build & release:** [Building & Releasing](packaging.md)

!!! note "Going further"
    This site itself is built with [MkDocs](https://www.mkdocs.org/) and the
    Material theme, and editing it is a contribution like any other. It only
    builds locally for now — see
    [Code Organization](code-organization.md#building-and-previewing-this-documentation-site)
    for why, and how to preview it yourself.

Ready? Start with **[Getting Started](getting-started.md)**.
