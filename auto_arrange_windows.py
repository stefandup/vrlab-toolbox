"""
auto_arrange_windows.py

Two modes:
  - save:  capture current window positions/sizes (for known window titles) into JSON
  - apply: load JSON and rearrange the matching windows accordingly

Uses helpers from `python_window_management.py`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from python_window_management import (
    bring_window_to_front,
    find_windows_by_title,
    load_layout,
    save_layout,
)


WINDOW_SEARCH_TITLES: list[str] = [
    "Example Python Window 1",
    "Example Python Window 2",
    "Example Python Window 3",
    "python.exe",
]


def _resolve_hwnds_by_titles(titles: list[str]) -> list[int]:
    """
    Resolve window handles in the same order as `titles`.
    - If a title matches multiple windows, the first match is used (same pattern as the example).
    - Missing titles are skipped (and warned), so your JSON may have fewer windows.
    """
    hwnds: list[int] = []
    for title in titles:
        matches = find_windows_by_title(title)
        if not matches:
            print(f"[WARN] No window found matching title: '{title}'")
            continue
        hwnd = int(matches[0])
        hwnds.append(hwnd)
    return hwnds


def save_mode(config_path: Path) -> None:
    hwnds = _resolve_hwnds_by_titles(WINDOW_SEARCH_TITLES)
    if not hwnds:
        raise SystemExit("No windows found; nothing to save.")
    save_layout(hwnds, config_path)
    print(f"[OK] Saved layout for {len(hwnds)} window(s) to: {config_path}")


def apply_mode(config_path: Path) -> None:
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")

    hwnds = _resolve_hwnds_by_titles(WINDOW_SEARCH_TITLES)
    if not hwnds:
        raise SystemExit("No windows found; nothing to apply.")

    # Restore/foreground first; some windows ignore MoveWindow while minimized.
    for hwnd in hwnds:
        bring_window_to_front(hwnd)

    load_layout(hwnds, config_path)
    print(f"[OK] Applied layout from: {config_path} to {len(hwnds)} window(s)")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Save and apply a simple window layout based on a fixed title list."
    )
    sub = p.add_subparsers(dest="mode", required=True)

    save_p = sub.add_parser("save", help="Capture window positions/sizes to JSON")
    save_p.add_argument(
        "--config",
        type=Path,
        default=Path("window_layout.json"),
        help="Path to layout JSON file (default: window_layout.json)",
    )

    apply_p = sub.add_parser("apply", help="Load JSON and rearrange windows")
    apply_p.add_argument(
        "--config",
        type=Path,
        default=Path("window_layout.json"),
        help="Path to layout JSON file (default: window_layout.json)",
    )

    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    if args.mode == "save":
        save_mode(args.config)
    elif args.mode == "apply":
        apply_mode(args.config)
    else:
        raise SystemExit(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()
