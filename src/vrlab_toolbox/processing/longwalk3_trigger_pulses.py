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

_PULSE_COLUMNS = ("onset", "instance", "actor_class", "x", "y", "alternatives")
ONSET_ALTERNATIVES_COLUMN = "onset_alternatives"  # see longwalk3_bids.ONSET_ALTERNATIVES_COLUMN


def _alternatives(cell: object) -> tuple[float, ...]:
    """';'-separated onsets -- a single one reads back from the .tsv as a number, not text."""
    if isinstance(cell, int | float) and not isinstance(cell, bool):
        return () if np.isnan(cell) else (float(cell),)
    if not isinstance(cell, str) or not cell.strip():
        return ()
    return tuple(float(part) for part in cell.split(";") if part)


def get_behaviour_pulses(raw_behav_df: pd.DataFrame) -> pd.DataFrame:
    """One row per Biopac pulse the run should have sent, in time order: `onset` (seconds,
    behaviour timeline), `instance` (the actor instance that sent it), `actor_class`, the
    instance's world position `x`/`y` at that moment (NaN if the class logs none), and
    `alternatives` -- other onsets its timestamp could mean, if it was ambiguous."""
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
                    "alternatives": (
                        rows[ONSET_ALTERNATIVES_COLUMN].map(_alternatives)
                        if ONSET_ALTERNATIVES_COLUMN in rows.columns
                        else pd.Series([()] * len(rows), index=rows.index, dtype=object)
                    ),
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
    icon_fonts = icon_font_families() or None
    for color_nr, (actor_class, group) in enumerate(pulses.groupby("actor_class", sort=True)):
        ax.scatter(
            group["x"],
            group["y"],
            s=60,
            color=f"C{color_nr % 10}",
            edgecolor="black",
            linewidth=0.5,
            label=f"{icon_key_text([str(actor_class)]) or actor_class} ({len(group)})",
            zorder=3,
        )
        for instance, x, y in zip(group["instance"], group["x"], group["y"], strict=True):
            ax.annotate(
                instance_icon_label(str(instance), str(actor_class)),
                (float(x), float(y)),
                xytext=(4, 4),
                textcoords="offset points",
                fontsize=9,
                fontfamily=icon_fonts,
                zorder=4,
            )

    ax.set_title(title or "Trigger locations (top-down, world X/Y)")
    ax.set_xlabel("World X (Unreal units)")
    ax.set_ylabel("World Y (Unreal units)")
    ax.set_aspect("equal", adjustable="datalim")
    if ax.get_legend_handles_labels()[0]:
        legend_font = {"size": 8, **({"family": icon_fonts} if icon_fonts else {})}
        ax.legend(loc="upper left", bbox_to_anchor=(1.18, 1.0), prop=legend_font, title="Triggers")
    fig.tight_layout()
    return fig


# Icons for the interval-QC labels: one emoji per actor class, followed by the instance
# number ("BP_PhoneAlerts_C_2" -> "📳2"). Most specific names first ("PhoneAlerts" before
# "Phone").
ACTOR_CLASS_ICONS: dict[str, str] = {
    "BPAudioCueTriggerC": "🔊",
    "BPBirdsFlyingC": "🐦",
    "BPHeatmapManagerC": "🗺",
    "BPNPCC": "🚶",
    "BPPanicAttackManagerC": "💓",
    "BPPanicCooldownTimersManagerC": "⏳",
    "BPPanicTriggerC": "😱",
    "BPPhoneAlertsC": "📳",
    "BPPhoneC": "📱",
    "BPSerialComManagerC": "🔌",
    "ThreatLevelMarkerNewC": "⚠",
}
# Windows ships Segoe UI Emoji; matplotlib falls back per glyph through this list.
ICON_FONT_FAMILIES = ["DejaVu Sans", "Segoe UI Emoji", "Noto Emoji", "Apple Color Emoji"]
_INSTANCE_PATTERN = re.compile(r"^(?P<name>.+?)_(?P<number>\d+)(?:__(?P<repeat>\d+))?$")


def actor_class_of_instance(instance: str) -> str:
    """'BP_NPC_C_3' -> 'BPNPCC' (the trigger column's class name)."""
    match = _INSTANCE_PATTERN.match(instance)
    name = match["name"] if match else instance
    return name.replace("_", "")


# Instance numbers longer than this are engine ids (e.g. "2147481935"), not a useful label.
_MAX_INSTANCE_NUMBER_DIGITS = 3
_REPEAT_SUFFIX = re.compile(r"^(?P<instance>.+?)(?:__(?P<repeat>\d+))?$")
_TRAILING_NUMBER = re.compile(r"(?P<number>\d+)$")


def short_actor_name(actor: str) -> str:
    """'BP_PanicTrigger_C' / 'BPPanicTriggerC' -> 'PanicTrigger'."""
    return re.sub(r"^BP|C$", "", actor.replace("_", ""))


def instance_icon_label(interval_name: str, actor_class: str | None = None) -> str:
    """An interval label (actor instance, maybe with a '__2' repeat suffix) as a short label:
    the class icon (or short class name, if it has no icon) + the instance's own number.

    The class is best given (`actor_class`, from the trigger column the pulse came from) --
    real instance names vary ('ThreatLevelMarkerNew2', 'BP_NPC2', 'BP_Phone_C_2147481935').
    Without it the class is guessed from the name. Engine-id numbers (> 3 digits) are dropped.
    E.g. ('ThreatLevelMarkerNew2', 'ThreatLevelMarkerNewC') -> '⚠2';
    ('BP_PhoneAlerts_C_2__3', None) -> '📳2 #3'."""
    split = _REPEAT_SUFFIX.match(interval_name)
    instance, repeat = (split["instance"], split["repeat"]) if split else (interval_name, None)
    actor_class = actor_class or actor_class_of_instance(instance)
    number_match = _TRAILING_NUMBER.search(instance)
    number = number_match["number"] if number_match else ""
    if len(number) > _MAX_INSTANCE_NUMBER_DIGITS:
        number = ""
    icon = ACTOR_CLASS_ICONS.get(actor_class)
    label = f"{icon}{number}" if icon else f"{short_actor_name(actor_class)}{number}"
    return f"{label} #{repeat}" if repeat else label


def icon_font_families() -> list[str]:
    """ICON_FONT_FAMILIES limited to fonts installed here (avoids findfont warnings)."""
    from matplotlib import font_manager

    installed = {font.name for font in font_manager.fontManager.ttflist}
    return [family for family in ICON_FONT_FAMILIES if family in installed]


def icon_key_text(actor_classes: list[str]) -> str:
    """'🔊 AudioCueTrigger   🚶 NPC ...' for the classes present -- the figure's icon key."""
    parts = []
    for actor_class in dict.fromkeys(actor_classes):
        icon = ACTOR_CLASS_ICONS.get(actor_class)
        if icon is not None:
            short = short_actor_name(actor_class)
            parts.append(f"{icon} {short}")
    return "    ".join(parts)
