# Data Stores

[Design Patterns](design-patterns.md) covered the *steps* of the pipeline —
find, import, process. This page covers the two small classes that sit
between the import steps and the processing steps: `RawBehaviourDataStore`
and `RawPhysiologyDataStore` (`processing/pipeline.py`).

## The problem they solve

A single participant can have *more than one* kind of behaviour data. Crane,
for instance, imports both the crane-task behaviour and a separate debrief
questionnaire — two different concrete classes, both subclasses of
`RawBehaviourData`:

```python
class RawCraneBehaviourData(RawBehaviourData): ...
class RawDebriefBehaviourData(RawBehaviourData): ...
```

Both get produced during the same "import behaviour" stage, by different
`ImportBehaviourDataStrategyStep` strategies. Something has to hold on to
both of them until the processing steps run — and each processing step
needs to fetch *its own* input back out, without knowing or caring what
else got imported alongside it.

That's the whole job of a data store: hold a **type → instance** mapping,
so anything that knows *which type it wants* can get exactly that back,
regardless of how many other things are sitting in the same store.

## The shape

Both stores are the same three methods, just for a different base type:

```python
@dataclass
class RawBehaviourDataStore:
    items: dict[type[RawBehaviourData], RawBehaviourData] = field(default_factory=dict)

    def add(self, item: RawBehaviourData) -> None:
        self.items[type(item)] = item

    def get(self, item_type: type[BehaviourDataType]) -> BehaviourDataType:
        try:
            return cast(BehaviourDataType, self.items[item_type])
        except KeyError as e:
            raise ValueError(f"Store has no behaviour of type {item_type.__name__}") from e

    def has(self, item_type: type[RawBehaviourData]) -> bool:
        return item_type in self.items
```

- **`add(item)`** — keys the dict by `type(item)`, not by any name you
  choose. You never call `store.add(item, key="crane")`; the class *is*
  the key.
- **`get(item_type)`** — pass the *class itself* (`RawCraneBehaviourData`,
  not an instance), get the matching instance back. Raises `ValueError`
  (not `KeyError`) if nothing of that type was ever added — a deliberate
  translation, so every caller in `pipeline.py` can catch the same
  `(ValueError, FileNotFoundError)` pair regardless of *which* store or
  step failed.
- **`has(item_type)`** — a non-raising check, used where a missing type
  is expected rather than an error (see [Pipeline Rules](pipeline-rules.md)
  for import-side context).

### Try it yourself: `has()`, `get()`, and the `ValueError`

```python
from vrlab_toolbox.processing.pipeline import RawBehaviourDataStore
from vrlab_toolbox.processing.crane_behaviour import RawCraneBehaviourData

store = RawBehaviourDataStore()
print(store.has(RawCraneBehaviourData))   # False — nothing added yet

try:
    store.get(RawCraneBehaviourData)      # nothing of this type was ever added
except ValueError as e:
    print(e)   # "Store has no behaviour of type RawCraneBehaviourData"
```

## Why keyed by type, not by name or position

Every strategy step declares which type it produces or consumes as a class
attribute — `behaviour_output_type`, `input_data_type`, and so on — instead
of a string label. That's what lets the `Sequential*Steps` loops in
`pipeline.py` be completely generic:

```python
for step in self.steps:
    in_data_type = step.input_data_type
    raw_behav_data = data_store_in.get(in_data_type)
    ...
```

This line doesn't know or care whether `in_data_type` is
`RawCraneBehaviourData`, `RawDebriefBehaviourData`, or something from an
experiment that doesn't exist yet. Swap in a new strategy step with a new
`input_data_type`, and the exact same loop keeps working — no `if`/`elif`
chain checking names anywhere.

!!! note "Restaurant analogy"
    Picture a kitchen's **pass** — the shelf where finished dishes wait to
    be carried to a table. It doesn't file dishes by which cook made them
    or what order they came in; it slots each one under *what it is*
    (`SaladDish`, `MainCourseDish`, ...). A waiter who needs to serve the
    salad for table 4 doesn't scan every dish on the pass — they ask for
    "the `SaladDish`" and get it directly. If cooking produced two salads
    for the same order, the second one *replaces* the first at that slot —
    exactly the pitfall below.

### Try it yourself: add two different types, fetch each back independently

```python
from vrlab_toolbox.processing.crane_debrief_behaviour import RawDebriefBehaviourData

# (using real, already-imported data — see design-patterns.md's
#  "run a single strategy directly" section for how to produce these)
store.add(crane_data)    # a RawCraneBehaviourData instance
store.add(debrief_data)  # a RawDebriefBehaviourData instance

crane_back = store.get(RawCraneBehaviourData)
debrief_back = store.get(RawDebriefBehaviourData)
# each call returns exactly the matching instance, independent of the other
```

## A sharp edge: `add()` overwrites same-type items

Because the key is `type(item)`, adding two instances of the *same*
concrete type silently overwrites the first with the second — there's no
list, no error, just replacement:

```python
store = RawBehaviourDataStore()
store.add(RawCraneBehaviourData(...))  # slot filled
store.add(RawCraneBehaviourData(...))  # same slot, first one is gone
```

This is fine as long as each `ImportBehaviourDataStrategyStep` in a given
`SequentialBehaviourImportSteps.steps` list produces a *different*
concrete type (Crane's two importers do: `RawCraneBehaviourData` and
`RawDebriefBehaviourData`). It becomes a real bug only if two steps in the
same list ever declared the same `behaviour_output_type` — worth knowing
before adding a second import step to any experiment.

### Try it yourself: trigger the overwrite

Call `store.add()` twice with two *separate* `RawCraneBehaviourData(...)`
instances, then `store.get(RawCraneBehaviourData)` — confirm you get the
second one back, not the first:

```python
store.add(RawCraneBehaviourData(...))   # first instance
store.add(RawCraneBehaviourData(...))   # second instance, same type
store.get(RawCraneBehaviourData)        # which one comes back?
```

---

**See also:** [Design Patterns](design-patterns.md#strategy) for how a
step's `input_data_type` / `behaviour_output_type` attribute gets set in
the first place, and [Pipeline Rules](pipeline-rules.md) for how missing
data (a `has()` check that comes back `False`) is handled at the pipeline
level.
