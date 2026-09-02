# Golden Rules

A handful of rules of thumb this codebase actually follows — not abstract
advice, but things you can point at in the code and in this project's own
history. Worth knowing before you write new code here.

If you're using an AI assistant, also see the [AI Style Guide](ai-style-guide.md) —
it turns these rules into a concrete established-stack/avoid-list an
assistant can be pointed at directly.

## Write Pythonic code — don't fight the language

**Pythonic** means writing code the way Python itself is designed to be
written — using the language's own idioms and standard library, instead
of patterns carried over wholesale from another language you happen to
know better (C-style index loops, Java-style getters/setters). Python has
a short, semi-official statement of this philosophy — run `import this`
in any Python shell to see it ("The Zen of Python"). A few lines from it
that matter most here: *"Readability counts."* *"Explicit is better than
implicit."* *"There should be one — and preferably only one — obvious way
to do it."*

Concrete examples, contrasted with the non-Pythonic version scientists
coming from another language often reach for first:

```python
# Not Pythonic — manual index loop, a C/Java habit
squared_totals = []
for i in range(len(orders)):
    squared_totals.append(orders[i]["total"] ** 2)

# Pythonic — list comprehension
squared_totals = [order["total"] ** 2 for order in orders]
```

```python
# Not Pythonic — manual index tracking
i = 0
for order in orders:
    print(i, order)
    i += 1

# Pythonic — enumerate()
for i, order in enumerate(orders):
    print(i, order)
```

```python
# Not Pythonic — length check standing in for truthiness
if len(kitchen_queue) > 0:
    ...

# Pythonic — empty containers are already falsy
if kitchen_queue:
    ...
```

```python
# Not Pythonic — manual string building
message = "Order " + str(order_id) + " is " + status

# Pythonic — f-string
message = f"Order {order_id} is {status}"
```

This project's own [EAFP rule](#ask-forgiveness-not-permission-eafp)
below is itself a Pythonic-vs-not example, not a separate idea — `try`/
`except` over manual precondition checks is this same principle applied
to error handling.

### Why this matters *more*, not less, for non-programmers

It's tempting to assume idiomatic Python is a "once you already know
Python" nicety, and that someone new to coding is better off writing
whatever gets the job done, however verbose. We think the opposite:

- **Every beginner-facing Python resource teaches the idiomatic way.**
  Tutorials, official docs, and Stack Overflow answers all model list
  comprehensions, `with` blocks, f-strings, and so on. Code that goes
  against the grain cuts you off from being able to look up your way
  through a problem — the answer you find won't look like the code in
  front of you.
- **Non-Pythonic code carried over from another language brings that
  language's bugs with it.** Manual index loops are exactly where
  off-by-one errors live; `if len(x) > 0` and `if x` quietly diverge the
  moment `x` turns out to be `None` instead of just empty.
- **It's what the rest of this codebase already looks like.** Reading
  Pythonic code elsewhere in this project and then writing non-Pythonic
  code yourself doubles the number of styles you have to hold in your
  head at once — code that reads like what you write is part of what
  makes a codebase learnable in the first place.

### Prefer boring, stock-standard Python

Related but distinct: even within idiomatic Python, prefer the plain,
well-known feature over the clever or exotic one. Standard library over a
dependency that reinvents it; a straightforward function over a
metaclass or decorator trick doing the same job less legibly;
`pathlib.Path` over hand-rolled string path-joining.

Reasons this earns its place as a rule, not just a stylistic preference:

- **Boring code fails predictably.** When something breaks in a script
  built from stock `for` loops and `if` statements, the error is usually
  exactly where it looks like it is. Clever code — deeply nested
  comprehensions, `__getattr__` magic, monkey-patching — can make the
  actual failure point invisible.
- **Debuggable by more people.** Someone a few months into Python can
  step through boring code and understand every line. That's not true of
  code leaning on rarely-used corners of the language — which, in a lab
  where people rotate through every few years, is exactly the code most
  likely to get quietly abandoned rather than fixed.
- **It ages well.** Flashy patterns tend to be trend-driven; basic
  control flow and the standard library have stayed the same for two
  decades and will likely outlast whichever clever technique looked good
  this year.

## Always use `Path`, never strings, for files and folders

Every folder or file passed through this codebase — a CLI argument, a
`data_folder_in`/`output_folder_in` on a strategy step, a filename handed
between functions — should be a `pathlib.Path`, never a bare `str`. This is
narrower than the general "prefer `pathlib.Path`" point above: it's a hard
rule for this specific case, not just a style preference.

```python
# Not this — string in, string out, joined by hand
def find_participant_file(data_folder: str, participant_id: str) -> str:
    return os.path.join(data_folder, f"{participant_id}.csv")

# This — Path in, Path out
def find_participant_file(data_folder: Path, participant_id: str) -> Path:
    return data_folder / f"{participant_id}.csv"
```

Why this earns its own rule, not just "prefer Path where convenient":

- **String path-building is exactly where the platform-separator bug in
  item 13 of [Next Steps](pipeline_next_steps.md#13-date-string-extraction-in-from_physiology_data-breaks-on-the-data-folders-path-separator)
  came from** — `str(a_path).split("_")` silently breaks on Windows because
  `str()` renders backslashes that a string-oriented split doesn't expect.
  `Path` objects sidestep this entirely: use `.name`, `.stem`, `.parts`, or
  `/` instead of manual string splitting/joining, and the platform's
  separator is never something your code has to reason about.
- **CLI entry points should hand back `Path` from the start**, via
  `click.Path(..., path_type=Path)`, rather than a plain string that gets
  wrapped in `Path(...)` partway through the function — see
  [Getting Started](getting-started.md#3-run-the-crane-pipeline) and
  [Lab Streaming](lab-streaming.md) for real examples of this at the click
  layer.
- **It matters more, not less, as folder-based conventions (like the BIDS
  direction in [Next Steps item 22](pipeline_next_steps.md#22-direction-import-assumptions-should-move-toward-bids-one-dataset-per-timepoint-per-input-folder))
  take over from filename-string parsing** — once "which timepoint" is
  answered by which folder a file lives in rather than by a substring of its
  name, folders need to be handled as structured `Path` objects throughout,
  not as strings that happen to look right.

## Ask forgiveness, not permission (EAFP)

Python has a strong, named idiom for how to handle things that might go
wrong: **EAFP** — "Easier to Ask Forgiveness than Permission." The idea:
just *try* the thing, and handle the specific exception if it fails, rather
than checking every precondition first and only proceeding if they all
pass (that alternative style has its own name too: **LBYL**, "Look Before
You Leap").

```python
# LBYL — check permission first
if item_type in self.items:
    return self.items[item_type]
else:
    raise ValueError(f"Store has no behaviour of type {item_type.__name__}")

# EAFP — ask forgiveness instead — real code, RawBehaviourDataStore.get()
try:
    return cast(BehaviourDataType, self.items[item_type])
except KeyError as e:
    raise ValueError(f"Store has no behaviour of type {item_type.__name__}") from e
```

Both versions do the same thing here, but EAFP is the more idiomatic —
and often faster — Python style: the "normal" path stays uncluttered by
precondition checks, and the failure handling lives in one place (the
`except` block) instead of being scattered through `if`/`else` branches.

This codebase leans on EAFP throughout — it's *why* `pipeline.py` is full
of `try`/`except` blocks around each strategy step's `run()` call, instead
of checking "does this file exist, is this data the right shape" before
calling it:

```python
try:
    pipeline_raw_behav_data = step.run(config_in=config_in)
    self.raw_behaviour_data_Store.add(pipeline_raw_behav_data)
    pipeline_status.set(step.behaviour_output_type, ProcessingStatus.OK)
except (ValueError, FileNotFoundError) as e:
    ...
```

That only works well combined with the next rule, though — EAFP still
needs the `except` to name *specific* exceptions, not swallow everything.

## Catch specific exceptions, not broad ones

Every `except` block in `pipeline.py` names exact exception types, e.g.:

```python
except (ValueError, FileNotFoundError) as e:
    ...
```

never a bare `except:` or `except Exception:`. The reason isn't just style —
this project hit a real bug from breaking this rule. `PipelineTemplate.run()`
once had `AttributeError` added to a broad `except` tuple to silence a
crash. That "worked," but only because it also *quietly* swallowed the real
bug: a `None` value was being passed into a strategy step that didn't
expect one. Widening the `except` tuple didn't fix anything — it just hid
the symptom, and would have swallowed any *other* unrelated
`AttributeError` too.

**The rule this produced:** if you're tempted to widen an `except` tuple to
make an error go away, that's usually a sign you need an explicit guard
(`if x is None: ...`) instead — not a broader `except`. See item 17 in
[Next Steps](pipeline_next_steps.md#17-pipelinetemplaterun-interval-step-none-inputs-surfacing-as-attributeerror-papered-over-by-widening-the-except-tuple)
for the full story, including the fix.

## Write code for today, not for a hypothetical future

From this project's own [Next Steps](pipeline_next_steps.md#working-rule)
doc, verbatim:

> Do not rewrite everything at once. Preserve working behaviour and improve
> one structural issue at a time.

In practice: don't add configuration options, abstractions, or flexibility
for a use case that doesn't exist yet. `PipelineTemplate`'s six-argument
constructor looks like a lot of ceremony, but every argument is used by the
one real pipeline (Crane) that exists today — it wasn't built out further
"in case" a hypothetical future pipeline needs more. If a genuine second
use case shows up later, that's when the abstraction earns its keep.

## Fix data problems as close to the source as you can

Data pulled in from an external system (REDCap, a paper form, an experiment
log) should ideally already arrive correct and consistent — every
correction added downstream is a chance to introduce a *new*
inconsistency, not just fix an old one. Rule of thumb, in order of
preference:

1. **Fix it at the source**, if that's realistic (correct the field in
   REDCap itself, fix the form).
2. If the source can't practically be fixed (e.g. a column header typo
   that's painful to change in REDCap), fix it **right where the data
   enters the pipeline** — the import/pull step — not scattered through
   later processing.
3. Anything else genuinely messy in the recorded data itself belongs
   **downstream**, and ideally somewhere a human already reviews the
   result — like a crosscheck GUI — rather than buried inside a CLI
   script or general processing logic.

This is the same reasoning behind keeping CLIs thin
([Code Organization](code-organization.md#the-command-line-tools)): the
CLI's job is to read, call, save — not to silently rewrite data as it
passes through. Every extra cleaning step is untested surface area, and a
correction buried deep in `processing/` is invisible the next time someone
reads that code. Keeping corrections at the boundary (import) or at the
point of human review (crosscheck) means there's exactly one obvious place
to look for "why does this value look different from the source."

## Respect input/output contracts

Every strategy step accepts and returns a fixed, typed shape of data —
`ParticipantConfig` in, `RawBioData`/`RawBehaviourData` in the middle,
`PipelineOutputData` out — so steps can be swapped and combined without
knowing about each other's internals. See
[Design Patterns](design-patterns.md#input-and-output-contracts) for the
full explanation with code. The short version: if you're writing a new
strategy step, match the existing contract rather than inventing a new
shape — that's what lets `PipelineTemplate` stay generic.

## Mark old code `@deprecated` — don't just delete it or leave it silently

When code is superseded but not yet safe to delete (e.g. other code still
calls it, or you want a record of why it was replaced), mark it with
`typing_extensions.deprecated` instead of quietly leaving it in place or
removing it outright:

```python
from typing_extensions import deprecated

@deprecated("Flawed matching algorithm specific to crane. Replace with a more general one")
def align_crane_behav_intervals_with_trigger_intervals(...):
    ...
```

This is real code from `crane_trial_intervals.py` — see
[Clock Drift Notes](clock_drift_error.md#update-this-approach-is-now-deprecated)
for the story behind it. The decorator doesn't stop the function from
running; it makes type checkers (like `pyright`) flag any call site with a
warning, showing your message as the reason. That gives anyone still
calling it — including future-you — an explicit, visible reason to migrate,
instead of the function just quietly rotting or vanishing without a trace.

---

**Next: [Pipeline Rules](pipeline-rules.md)** — one concrete set of rules
this codebase enforces, for matching each participant's files.
