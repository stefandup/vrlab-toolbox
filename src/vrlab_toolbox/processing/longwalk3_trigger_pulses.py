"""Which rows of a LongwalkV3 combined events.tsv sent a Biopac pulse, and where in the world
they happened -- shared by the interval step (longwalk3_trial_intervals.py, timing) and the
behaviour step (longwalk3_behaviour.py, the trigger-location QC map). No dependency on the
other longwalk3 processing modules, so both can import it.

Every filled `trigger_<class>` cell is one pulse sent by the instance it names -- except the
classes in NON_PULSE_ACTOR_CLASSES (never pulse) and FIRST_ROW_PULSE_ACTOR_CLASSES (only their
first row pulses). Confirmed by the Unreal side 2026-11-18: every class sends triggers except
the heatmap manager. The birds do send triggers, but hundreds in a few seconds, so on the
Biopac they merge into one long pulse: they're kept for *matching* (so later pulses stay in
line) but never start an interval (MATCH_ONLY_ACTOR_CLASSES). The generator mirrors this in
longwalk3_dummy_data.py (`_NON_PULSE_SUFFIXES`/`_FIRST_ROW_PULSE_SUFFIXES`).
"""

import re
from typing import cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from matplotlib.patches import Polygon

TRIGGER_COLUMN_PREFIX = "trigger_"
NON_PULSE_ACTOR_CLASSES: tuple[str, ...] = ("BPHeatmapManagerC",)
FIRST_ROW_PULSE_ACTOR_CLASSES: tuple[str, ...] = ()
# Pulse, but are ignored as interval boundaries (see module docstring).
MATCH_ONLY_ACTOR_CLASSES: tuple[str, ...] = ("BPBirdsFlyingC",)
# Biopac pulses last ~0.1 s, so pulses sent closer together than this show up as a single
# rising edge -- behaviour pulses within this gap are merged before matching.
MIN_PULSE_GAP_SECONDS = 0.15

HEATMAP_ACTOR_CLASS = "BPHeatmapManagerC"
# The heatmap actor logs the corners of the mapped play area on its first row.
HEATMAP_CORNER_COLUMNS = tuple(
    f"{corner}Vector_{HEATMAP_ACTOR_CLASS}"
    for corner in ("topLeft", "topRight", "bottomRight", "bottomLeft")
)
_FVECTOR_PATTERN = re.compile(r"X=(?P<x>[-\d.]+)\s+Y=(?P<y>[-\d.]+)")

_PULSE_COLUMNS = ("onset", "instance", "actor_class", "x", "y")


def get_behaviour_pulses(raw_behav_df: pd.DataFrame) -> pd.DataFrame:
    """One row per Biopac pulse the run should have sent, in time order: `onset` (seconds,
    behaviour timeline), `instance` (the actor instance that sent it), `actor_class`, and the
    instance's world position `x`/`y` at that moment (NaN if the class logs none)."""
    pulses = []
    for column in raw_behav_df.columns:
        if not str(column).startswith(TRIGGER_COLUMN_PREFIX):
            continue
        actor_class = str(column)[len(TRIGGER_COLUMN_PREFIX) :]
        if actor_class in NON_PULSE_ACTOR_CLASSES:
            continue
        rows = raw_behav_df.loc[raw_behav_df[column].notna()]
        rows = rows.dropna(subset=["onset"]).sort_values("onset")
        if actor_class in FIRST_ROW_PULSE_ACTOR_CLASSES:
            rows = rows.head(1)
        pulses.append(
            pd.DataFrame(
                {
                    "onset": rows["onset"].astype(float),
                    "instance": rows[column].astype(str),
                    "actor_class": actor_class,
                    "x": _location_column(rows, actor_class, "x"),
                    "y": _location_column(rows, actor_class, "y"),
                }
            )
        )
    if not pulses:
        return pd.DataFrame({name: pd.Series(dtype=object) for name in _PULSE_COLUMNS}).astype(
            {"onset": float, "x": float, "y": float}
        )
    all_pulses = pd.concat(pulses, ignore_index=True).sort_values("onset", kind="stable")
    keep = all_pulses["onset"].diff().fillna(np.inf) >= MIN_PULSE_GAP_SECONDS
    return cast(pd.DataFrame, all_pulses[keep].reset_index(drop=True))


def _location_column(rows: pd.DataFrame, actor_class: str, axis: str) -> pd.Series:
    column = f"worldLocation_{actor_class}_{axis}"
    if column not in rows.columns:
        return pd.Series(np.nan, index=rows.index)
    return pd.Series(pd.to_numeric(rows[column], errors="coerce"), index=rows.index)


def _all_logged_positions(raw_behav_df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Every logged actor position in the run (all classes, all rows) -- where things were."""
    xs, ys = [], []
    for x_column in [c for c in raw_behav_df.columns if re.match(r"^worldLocation_.+_x$", str(c))]:
        y_column = str(x_column)[:-1] + "y"
        if y_column not in raw_behav_df.columns:
            continue
        x = pd.Series(pd.to_numeric(raw_behav_df[x_column], errors="coerce"))
        y = pd.Series(pd.to_numeric(raw_behav_df[y_column], errors="coerce"))
        both = x.notna() & y.notna()
        xs.append(x.to_numpy(dtype=float)[both.to_numpy()])
        ys.append(y.to_numpy(dtype=float)[both.to_numpy()])
    if not xs:
        return np.array([]), np.array([])
    return np.concatenate(xs), np.concatenate(ys)


def heatmap_area_corners(raw_behav_df: pd.DataFrame) -> list[tuple[float, float]] | None:
    """The heatmap actor's play-area corners (top-left, top-right, bottom-right, bottom-left),
    from the first row that has all four -- None if the run doesn't log them."""
    if not all(column in raw_behav_df.columns for column in HEATMAP_CORNER_COLUMNS):
        return None
    for _, row in raw_behav_df[list(HEATMAP_CORNER_COLUMNS)].dropna().iterrows():
        matches = [_FVECTOR_PATTERN.search(str(row[c])) for c in HEATMAP_CORNER_COLUMNS]
        if all(matches):
            return [(float(m.group("x")), float(m.group("y"))) for m in matches if m]
    return None


def plot_trigger_locations(raw_behav_df: pd.DataFrame, title: str = "") -> Figure:
    """Top-down QC map of where the run's triggers happened: a grey density of every logged
    actor position (where things were), the heatmap's play-area outline, and each trigger
    pulse at its sender's position -- coloured by actor class, labelled by instance."""
    fig, ax = plt.subplots(figsize=(12, 10), dpi=150)

    xs, ys = _all_logged_positions(raw_behav_df)
    if xs.size:
        density = ax.hexbin(xs, ys, gridsize=40, cmap="Greys", mincnt=1, alpha=0.7, zorder=1)
        fig.colorbar(density, ax=ax, label="Logged actor positions (count)", shrink=0.7)

    corners = heatmap_area_corners(raw_behav_df)
    if corners is not None:
        ax.add_patch(
            Polygon(
                corners,
                closed=True,
                fill=False,
                linestyle="--",
                edgecolor="tab:blue",
                linewidth=1.5,
                label="Heatmap area",
                zorder=2,
            )
        )

    pulses = get_behaviour_pulses(raw_behav_df).dropna(subset=["x", "y"])
    for color_nr, (actor_class, group) in enumerate(pulses.groupby("actor_class", sort=True)):
        ax.scatter(
            group["x"],
            group["y"],
            s=60,
            color=f"C{color_nr % 10}",
            edgecolor="black",
            linewidth=0.5,
            label=f"{actor_class} ({len(group)})",
            zorder=3,
        )
        for instance, x, y in zip(group["instance"], group["x"], group["y"], strict=True):
            ax.annotate(
                str(instance),
                (float(x), float(y)),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=6,
                zorder=4,
            )

    ax.set_title(title or "Trigger locations (top-down, world X/Y)")
    ax.set_xlabel("World X (Unreal units)")
    ax.set_ylabel("World Y (Unreal units)")
    ax.set_aspect("equal", adjustable="datalim")
    if ax.get_legend_handles_labels()[0]:
        ax.legend(loc="upper left", bbox_to_anchor=(1.18, 1.0), fontsize=7, title="Triggers")
    fig.tight_layout()
    return fig
