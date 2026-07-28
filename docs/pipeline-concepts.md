# Pipeline Concepts

[Pipeline Rules](pipeline-rules.md), the [Interval QC Plot](interval-qc.md),
[EDA & SCRs](eda.md), and [Lab Streaming](lab-streaming.md) covered *what*
the pipeline checks, matches, and computes, for two different experiments.
This page covers *why* the pipeline itself is structured the way it is —
the short version. For the full explanation with real code from this
repository, see [Design Patterns](design-patterns.md).

The pipeline's shape rests on two ideas, best explained with a toy example
first (a restaurant order, not this project's actual domain — see
[Design Patterns](design-patterns.md) for the real thing).

## Template Method: a fixed sequence of steps

A **template** fixes the *order* of steps, while letting each individual
step's behaviour vary. Every restaurant order goes *queued → prepared →
served*, no matter what's actually being cooked:

```python
def process_order(order, cook_step, serve_step):
    order = cook_step.run(order)
    order = serve_step.run(order)
    return order
```

`process_order` never changes. What `cook_step` and `serve_step` actually
*do* can be swapped out freely — that's the next pattern.

## Strategy: swappable steps

A **strategy** is a small, interchangeable piece of behaviour that follows a
shared contract (usually: "has a `run()` method"), so it can be swapped in
without changing the code that calls it:

```python
class GrillStation:
    def run(self, order):
        ...  # cook a grilled dish
        return order

class SaladStation:
    def run(self, order):
        ...  # prepare a salad
        return order
```

`process_order` doesn't need to know or care whether `cook_step` is a
`GrillStation` or a `SaladStation` — only that it has `.run()`.

## Why bother?

- **Reuse** — every experiment (`crane_pipeline.py`, `foh_pipeline.py`,
  `long_walk_pipeline.py`) reuses the same fixed find→import→process→save
  sequence instead of writing its own from scratch.
- **Testability** — each strategy step can be tested on its own, without
  running the whole pipeline.
- **Change in one place** — adding a new experiment means writing new
  strategy steps, not editing the template itself.

See [Design Patterns](design-patterns.md) for how these two ideas actually
show up in `pipeline.py` and `crane_pipeline.py`, plus a third pattern
(Composite) this codebase also uses, and
[Code Organization](code-organization.md#where-the-actual-steps-live) for
where each concrete strategy step lives.

---

**Next: [Design Patterns](design-patterns.md)** — the same two ideas, plus
a third, shown with real code from this repository instead of the toy
example above.
