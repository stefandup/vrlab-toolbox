"""Standalone PySide6 tool: human-in-the-loop crosscheck for the crane BIDS folder.

See docs/bids_crosscheck_plan.md. Glob patterns are extension-based (`*.mat`/`*.csv`/
`*.tsv`), matching `cli/crane_convert_to_bids.py`'s real output -- deliberately *not*
keyword-based (e.g. `*physiology*`) because tagging (`task_correction_available` below)
renames a file to `..._run-<NNN>_<label><ext>`, discarding any keyword in the stem. Only
the extension survives a tag rename, so it's the one thing all three scan types can still
be told apart by afterwards. Debrief is `.tsv` (not `.csv`, same as behaviour) specifically
so it stays distinguishable from behaviour by extension alone.

`CraneCandidateExtras` below is the crane analog of `FohCandidateExtras`
(`foh_bids_crosscheck_gui.py`) -- deferred until now per
docs/bids_crosscheck_plan.md#crane-parity-with-foh-s-gui-improvements. Its content
parsing is best-effort against the *raw* data formats crane actually produces today
(Biopac `.mat` physiology, per-subject behaviour `.csv`, one shared REDCAP `.csv`
group debrief export -- see `processing/biopac.py`, `processing/crane_behaviour.py`,
`processing/crane_debrief_behaviour.py`), since there's no real crane BIDS output yet
to confirm the post-conversion format/columns against (examples/crane_bids_dummy is a
filename/folder-structure mockup only -- its files are empty). Every parser below
fails soft (logs a warning, reports "couldn't read") rather than raising, so a format
mismatch once real BIDS output exists shows up as an info gap, not a crash.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import scipy.io as sio
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mooi_toolbox.cli.crane_convert_to_bids import (
    CraneConversionSummary,
    convert_crane_to_bids,
    discover_raw_subject_ids,
    existing_subject_ids,
    guess_corrected_subject_id,
    load_debrief_export,
    load_debrief_id_corrections,
    save_debrief_id_corrections,
)
from mooi_toolbox.gui.bids_crosscheck_common import CandidateExtras, run_bids_crosscheck_app
from mooi_toolbox.processing.bids_crosscheck import DatasetConfig, ScanTypeConfig
from mooi_toolbox.processing.biodata import ACCEPTED_LABEL_PATTERN, CANONICAL_LABEL_SPELLING
from mooi_toolbox.processing.biopac import clean_biopac_labels
from mooi_toolbox.processing.crane_behaviour import build_crane_raw_behav_file_schema
from mooi_toolbox.processing.crane_debrief_behaviour import crane_raw_debrief_file_schema

logger = logging.getLogger(__name__)

CRANE_DATASET_CONFIG = DatasetConfig(
    dataset_name="crane",
    scan_types=(
        ScanTypeConfig(name="physiology", glob_patterns=("*.mat",)),
        ScanTypeConfig(name="behaviour", glob_patterns=("*.csv",)),
        ScanTypeConfig(name="debrief", glob_patterns=("*.tsv",)),
    ),
    # Every scan type is taggable here (unlike FOH, where only "recording" is) -- see
    # CraneCandidateExtras.task_correction_available. task_correction_folder_name="beh"
    # matches crane_convert_to_bids.py's own sub-XXX/beh/ layout, so the folder-rename
    # record_task_correction does on tagging is a same-name no-op, not an actual move.
    task_correction_label="crane",
    task_correction_folder_name="beh",
)

PHYSIOLOGY_SCAN_TYPE = "physiology"
BEHAVIOUR_SCAN_TYPE = "behaviour"
DEBRIEF_SCAN_TYPE = "debrief"

# The crane pipeline only ever processes EDA out of a Biopac recording (see
# processing/crane_pipeline.py's SequentialPhysiologyProcessingSteps, which only lists
# ProcessEdaPhysiologyDataStrategyStep) -- unlike FOH, which needs both EDA and ECG.
EXPECTED_PHYSIO_CHANNELS = ("EDA",)
# The column sets the raw behaviour/debrief data is validated against once it reaches the
# pipeline (processing/crane_behaviour.py, processing/crane_debrief_behaviour.py) -- reused
# here as an advisory "does this look complete" check, not full pandera validation, since a
# stricter check (value ranges, balanced conditions, ...) belongs to the pipeline, not a
# glance-level crosscheck. The debrief schema describes the shared REDCAP group export's
# columns (record_id plus wide crane_<emotion>_rb/_gb columns); a per-subject BIDS debrief
# file keeps the same columns since `crane_convert_to_bids.load_debrief_export` filters
# against this same schema before writing it.
BEHAVIOUR_EXPECTED_COLUMNS = tuple(build_crane_raw_behav_file_schema().columns.keys())
DEBRIEF_EXPECTED_COLUMNS = tuple(crane_raw_debrief_file_schema.columns.keys())

CHECK = "✓"
CROSS = "✗"
WARNING = "❗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
WARNING_COLOR = "#f39c12"
INFO_CACHE_FILENAME = "crosscheck_info_cache.json"
# Bumped whenever a parser's output shape or derivation changes, so a cached entry that still
# matches the file's mtime/size (nothing to re-read) but was computed by older logic gets
# reparsed anyway instead of silently serving stale info forever.
INFO_SCHEMA_VERSION = 1


@dataclass
class CranePhysiologyInfo:
    channels: dict[str, bool]
    duration_minutes: float | None
    all_labels: list[str] | None


@dataclass
class CraneBehaviourInfo:
    n_rows: int | None
    columns: list[str] | None
    missing_columns: list[str]


@dataclass
class CraneDebriefInfo:
    n_rows: int | None
    columns: list[str] | None
    missing_columns: list[str]


def _present_physio_channels(labels: list[str]) -> dict[str, bool]:
    """Which of EXPECTED_PHYSIO_CHANNELS appear in `labels`, matched the same way
    `biodata.normalize_data_labels` matches them for the actual pipeline (case-insensitive,
    optional trailing digit) -- so this reports exactly what the pipeline would accept.
    """
    canonical_found = set()
    for label in labels:
        match = ACCEPTED_LABEL_PATTERN.match(label)
        if match is not None:
            canonical_found.add(CANONICAL_LABEL_SPELLING[match.group("base").lower()])
    return {channel: channel in canonical_found for channel in EXPECTED_PHYSIO_CHANNELS}


def _parse_physiology_info(file: Path) -> CranePhysiologyInfo:
    try:
        imported_data = sio.loadmat(str(file))
        labels = clean_biopac_labels(imported_data["labels"])
        isi_seconds = float(imported_data["isi"].squeeze()) / 1000
        n_samples = imported_data["data"].shape[0]
    except Exception:
        logger.warning("Could not read physiology data from %s", file, exc_info=True)
        return CranePhysiologyInfo(
            channels=dict.fromkeys(EXPECTED_PHYSIO_CHANNELS, False),
            duration_minutes=None,
            all_labels=None,
        )

    return CranePhysiologyInfo(
        channels=_present_physio_channels(labels),
        duration_minutes=(n_samples * isi_seconds) / 60,
        all_labels=labels,
    )


def _parse_behaviour_info(file: Path) -> CraneBehaviourInfo:
    try:
        df = pd.read_csv(file)
    except Exception:
        logger.warning("Could not read behaviour data from %s", file, exc_info=True)
        return CraneBehaviourInfo(
            n_rows=None, columns=None, missing_columns=list(BEHAVIOUR_EXPECTED_COLUMNS)
        )

    columns = list(df.columns)
    missing = [column for column in BEHAVIOUR_EXPECTED_COLUMNS if column not in columns]
    return CraneBehaviourInfo(n_rows=len(df), columns=columns, missing_columns=missing)


def _parse_debrief_info(file: Path) -> CraneDebriefInfo:
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception:
        logger.warning("Could not read debrief data from %s", file, exc_info=True)
        return CraneDebriefInfo(
            n_rows=None, columns=None, missing_columns=list(DEBRIEF_EXPECTED_COLUMNS)
        )

    columns = list(df.columns)
    missing = [column for column in DEBRIEF_EXPECTED_COLUMNS if column not in columns]
    return CraneDebriefInfo(n_rows=len(df), columns=columns, missing_columns=missing)


def _info_cache_path(bids_folder: Path) -> Path:
    return bids_folder / INFO_CACHE_FILENAME


def _load_info_cache(bids_folder: Path) -> dict[str, dict]:
    path = _info_cache_path(bids_folder)
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as cache_file:
            return json.load(cache_file)
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read info cache at %s -- starting fresh", path)
        return {}


def _save_info_cache(bids_folder: Path, cache: dict[str, dict]) -> None:
    path = _info_cache_path(bids_folder)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as tmp_file:
        json.dump(cache, tmp_file, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


class CraneCandidateExtras(CandidateExtras):
    """Advisory crane physiology/behaviour/debrief info; never gates renaming.

    Every parse result is cached on disk (see INFO_CACHE_FILENAME), keyed by the file's
    path relative to the BIDS folder plus its mtime/size, so a fresh launch or re-Browse
    doesn't have to re-parse every "ok" candidate again -- only files that are new or have
    actually changed. Mirrors FohCandidateExtras's cache, generalized across crane's three
    scan types instead of FOH's one.
    """

    def __init__(self) -> None:
        self._bids_folder: Path | None = None
        self._disk_cache: dict[str, dict] = {}
        self._dirty = False

    def on_bids_folder_changed(self, bids_folder: Path) -> None:
        self._bids_folder = bids_folder
        self._disk_cache = _load_info_cache(bids_folder)
        self._dirty = False

    def bidsignore_patterns(self) -> tuple[str, ...]:
        return (INFO_CACHE_FILENAME,)

    def flush(self) -> None:
        if self._dirty and self._bids_folder is not None:
            _save_info_cache(self._bids_folder, self._disk_cache)
        self._dirty = False

    def describe(self, scan_type: str, file: Path) -> str | None:
        """Compact per-candidate info shown inline in the subject list.

        The visible tick is labelled by scan type ("Physiology"/"Behaviour"/"Debrief"), not
        by what it's actually checking underneath (expected channels for physiology,
        expected columns for behaviour/debrief) -- that detail still drives whether it's
        green or red, it's just not spelled out in the compact label. See
        `describe_tooltip`/`detail` for the underlying channel/column breakdown.
        """
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            complete = info.all_labels is not None and all(info.channels.values())
            channels_text = (
                f'<span style="color:{CHECK_COLOR if complete else CROSS_COLOR}">'
                f"Physiology {CHECK if complete else CROSS}</span>"
            )
            parts = []
            if info.duration_minutes is not None:
                parts.append(f"{round(info.duration_minutes)} min")
            parts.append(channels_text)
            return " &nbsp;&nbsp; ".join(parts)

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            complete = info.columns is not None and not info.missing_columns
            label = "Behaviour" if scan_type == BEHAVIOUR_SCAN_TYPE else "Debrief"
            if complete:
                icon, color = CHECK, CHECK_COLOR
            elif scan_type == DEBRIEF_SCAN_TYPE and info.columns is not None:
                # The file exists and is readable but is missing expected columns -- a
                # narrower problem than a completely absent debrief file (which
                # bids_crosscheck_common.py's "missing" status shows as a plain X for
                # instead), so a distinct warning glyph here keeps the two failure modes
                # visually distinguishable at a glance.
                icon, color = WARNING, WARNING_COLOR
            else:
                icon, color = CROSS, CROSS_COLOR
            columns_text = f'<span style="color:{color}">{label} {icon}</span>'
            parts = []
            if info.n_rows is not None:
                row_word = "trials" if scan_type == BEHAVIOUR_SCAN_TYPE else "row(s)"
                parts.append(f"{info.n_rows} {row_word}")
            parts.append(columns_text)
            return " &nbsp;&nbsp; ".join(parts)

        return None

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            lines = ["Channels the crane pipeline needs:"]
            lines.extend(
                f"{CHECK if present else CROSS} {label}" for label, present in info.channels.items()
            )
            return "\n".join(lines)

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            if info.columns is None:
                return "Could not read this file"
            if not info.missing_columns:
                return "All expected columns present"
            return "Missing columns:\n" + "\n".join(f"{CROSS} {column}" for column in info.missing_columns)

        return None

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            channels_text = " ".join(
                f'{label}<span style="color:{CHECK_COLOR if present else CROSS_COLOR}">'
                f"{CHECK if present else CROSS}</span>"
                for label, present in info.channels.items()
            )
            channels_line = f"<b>Channels</b> &nbsp; {channels_text}"
            if info.all_labels is None:
                return f"{channels_line}<br>Could not read this physiology file"
            labels_text = ", ".join(info.all_labels)
            duration_text = (
                f"{info.duration_minutes:.1f} min"
                if info.duration_minutes is not None
                else "duration unavailable"
            )
            return f"{channels_line}<br><b>Labels</b> &nbsp; {labels_text} &nbsp;&nbsp; {duration_text}"

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            if info.columns is None:
                return "Could not read this file"
            row_word = "trials" if scan_type == BEHAVIOUR_SCAN_TYPE else "row(s)"
            rows_text = f"{info.n_rows} {row_word}" if info.n_rows is not None else "row count unavailable"
            if not info.missing_columns:
                return f"{rows_text} &nbsp;&nbsp; all expected columns present"
            missing_text = ", ".join(info.missing_columns)
            return (
                f"{rows_text} &nbsp;&nbsp; "
                f'<span style="color:{CROSS_COLOR}">missing columns: {missing_text}</span>'
            )

        return None

    def task_correction_available(self, scan_type: str) -> bool:
        """All three scan types are taggable, unlike FOH's single "recording" type -- see
        CRANE_DATASET_CONFIG and the module docstring for the run-token/extension-based-glob
        requirements this relies on."""
        return scan_type in (PHYSIOLOGY_SCAN_TYPE, BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE)

    def refreshable(self, scan_type: str) -> bool:
        return scan_type in (PHYSIOLOGY_SCAN_TYPE, BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE)

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force a reparse for one candidate. Caller batches the disk write via `flush()`."""
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            self._physiology_info(file, force=True)
        elif scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            self._behaviour_or_debrief_info(scan_type, file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            return info.all_labels is not None and not all(info.channels.values())

        if scan_type in (BEHAVIOUR_SCAN_TYPE, DEBRIEF_SCAN_TYPE):
            info = self._behaviour_or_debrief_info(scan_type, file)
            return info.columns is not None and bool(info.missing_columns)

        return False

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _cached(self, kind: str, file: Path, parser, info_cls, force: bool = False):
        key = self._cache_key(file)
        stat = file.stat()
        cached = self._disk_cache.get(key)
        if not force and cached is not None:
            if (
                cached.get("mtime") == stat.st_mtime
                and cached.get("size") == stat.st_size
                and cached.get("info_version") == INFO_SCHEMA_VERSION
                and cached.get("kind") == kind
            ):
                try:
                    return info_cls(**cached["info"])
                except (TypeError, KeyError):
                    logger.warning("Stale info-cache entry for %s -- reparsing", file)

        info = parser(file)
        self._disk_cache[key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "info_version": INFO_SCHEMA_VERSION,
            "kind": kind,
            "info": asdict(info),
        }
        self._dirty = True
        return info

    def _physiology_info(self, file: Path, force: bool = False) -> CranePhysiologyInfo:
        return self._cached(
            PHYSIOLOGY_SCAN_TYPE, file, _parse_physiology_info, CranePhysiologyInfo, force
        )

    def _behaviour_or_debrief_info(self, scan_type: str, file: Path, force: bool = False):
        if scan_type == BEHAVIOUR_SCAN_TYPE:
            return self._cached(scan_type, file, _parse_behaviour_info, CraneBehaviourInfo, force)
        return self._cached(scan_type, file, _parse_debrief_info, CraneDebriefInfo, force)


class _ListLogHandler(logging.Handler):
    """Captures formatted log records into a list instead of printing them -- used to relay
    `convert_crane_to_bids`'s `logger.info`/`logger.warning` calls into the crosscheck GUI's
    status dialog, since that function reports progress/problems via the standard logger
    rather than a GUI-specific callback (see its own docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {self.format(record)}")


def _format_conversion_summary(summary: CraneConversionSummary) -> str:
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        return "No new subjects found -- everything in the raw folder is already converted."

    lines = []
    if summary.new_subject_ids:
        lines += [f"Added {len(summary.new_subject_ids)} new subject(s):", ""]
        for subject_id in summary.new_subject_ids:
            physiology = ", ".join(p.name for p in summary.subject_physiology.get(subject_id, []))
            behaviour = ", ".join(p.name for p in summary.subject_behaviour.get(subject_id, []))
            debrief = summary.subject_debrief.get(subject_id)
            lines.append(f"sub-{subject_id}")
            lines.append(f"    physiology: {physiology or '(missing)'}")
            lines.append(f"    behaviour:  {behaviour or '(missing)'}")
            lines.append(f"    debrief:    {debrief.name if debrief else '(missing)'}")

    if summary.backfilled_debrief_ids:
        if lines:
            lines.append("")
        lines.append(
            f"Backfilled debrief for {len(summary.backfilled_debrief_ids)} already-converted "
            "subject(s) that didn't have one yet:"
        )
        lines.append("")
        for subject_id in summary.backfilled_debrief_ids:
            debrief = summary.subject_debrief.get(subject_id)
            lines.append(f"sub-{subject_id}")
            lines.append(f"    debrief: {debrief.name if debrief else '(missing)'}")

    return "\n".join(lines)


class DebriefRecordIdCorrectionDialog(QDialog):
    """Lets a human declare "this messy debrief record_id really means this subject",
    without ever touching the raw REDCAP export -- corrections are saved to their own JSON
    (`crane_convert_to_bids.save_debrief_id_corrections`, in the BIDS folder) and applied the
    next time "Refresh BIDS" runs (`crane_convert_to_bids.convert_crane_to_bids`). A plain
    editable table with freeform text, not a dropdown-matched picker -- same correction style
    as `bids_crosscheck_common.py`'s existing "Correct date..."/"Rename subject ID..."
    `QInputDialog.getText` dialogs, just extended to handle more than one row at a time.
    """

    def __init__(self, raw_folder: Path, bids_folder: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.bids_folder = bids_folder
        self.setWindowTitle("Fix debrief record IDs")
        self.resize(640, 420)

        layout = QVBoxLayout(self)
        self._unmatched_record_ids: list[str] = []
        self._unmatched_subject_ids: list[str] = []

        existing_corrections = load_debrief_id_corrections(bids_folder)
        debrief_df = load_debrief_export(raw_folder)
        if debrief_df is None:
            layout.addWidget(QLabel("No debrief export found in the raw folder."))
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        known_ids = discover_raw_subject_ids(raw_folder) | existing_subject_ids(bids_folder)
        record_ids = debrief_df["record_id"].astype(str)
        corrected_ids = record_ids.replace(existing_corrections)
        self._unmatched_record_ids = sorted(record_ids[~corrected_ids.isin(known_ids)].unique())
        # What a guess is actually checked against: subjects still missing a debrief, not
        # every known id -- a guess landing on a subject that already has one would just
        # create a second, wrong debrief for them, not fix anything.
        self._unmatched_subject_ids = sorted(known_ids - set(corrected_ids))

        layout.addWidget(
            QLabel(
                "These record_id values in the debrief export don't match any known subject "
                "id. Each row is pre-filled with a best-effort guess (stray whitespace/PID-dash "
                "fixes) -- edit any that are still wrong, or clear the box to skip. This never "
                'changes the raw export; corrections are saved separately and applied the next '
                'time you click "Refresh BIDS".'
            )
        )

        self.table = QTableWidget(len(self._unmatched_record_ids), 3)
        self.table.setHorizontalHeaderLabels(
            ["record_id (from export)", "Matched", "Corrected subject id"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeaderItem(1).setToolTip(
            f"{CHECK} matches a subject still missing a debrief file\n"
            f"{CROSS} doesn't match any subject still missing a debrief file -- double-check "
            "it, or this subject may genuinely have no debrief data (e.g. never completed it)"
        )
        self.table.verticalHeader().setVisible(False)
        for row, record_id in enumerate(self._unmatched_record_ids):
            record_item = QTableWidgetItem(record_id)
            record_item.setFlags(record_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, record_item)
            match_item = QTableWidgetItem("")
            match_item.setFlags(match_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, match_item)
            guess = existing_corrections.get(record_id) or guess_corrected_subject_id(record_id)
            self.table.setItem(row, 2, QTableWidgetItem(guess))
            self._update_match_icon(row)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table, 1)

        if self._unmatched_subject_ids:
            reference_label = QLabel(
                "Subject ids still without a debrief match: "
                + ", ".join(self._unmatched_subject_ids)
            )
            reference_label.setWordWrap(True)
            layout.addWidget(reference_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_match_icon(self, row: int) -> None:
        item = self.table.item(row, 2)
        text = item.text().strip() if item is not None else ""
        if not text:
            icon, tooltip = "", ""
        elif text in self._unmatched_subject_ids:
            icon, tooltip = CHECK, "Matches a subject still missing a debrief file"
        else:
            icon, tooltip = (
                CROSS,
                "Doesn't match any subject still missing a debrief file -- double-check it, "
                "or this subject may genuinely have no debrief data",
            )
        match_item = self.table.item(row, 1)
        if match_item is not None:
            match_item.setText(icon)
            match_item.setToolTip(tooltip)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 2:
            self._update_match_icon(item.row())

    def _on_save(self) -> None:
        corrections = load_debrief_id_corrections(self.bids_folder)
        for row, record_id in enumerate(self._unmatched_record_ids):
            item = self.table.item(row, 2)
            corrected_id = item.text().strip() if item is not None else ""
            if corrected_id:
                corrections[record_id] = corrected_id
            else:
                corrections.pop(record_id, None)
        save_debrief_id_corrections(self.bids_folder, corrections)
        self.accept()


def _on_fix_debrief_record_ids(raw_folder: Path, bids_folder: Path, parent: QWidget) -> None:
    """The crane-specific `extra_raw_action` callback for the "Fix debrief record IDs..."
    button -- see `DebriefRecordIdCorrectionDialog`.
    """
    DebriefRecordIdCorrectionDialog(raw_folder, bids_folder, parent).exec()


def _run_crane_conversion(
    raw_folder: Path, bids_folder: Path, debrief_export: Path | None
) -> list[str]:
    """The crane-specific `raw_converter` callback `BidsCrosscheckWindow` calls when the
    "Refresh BIDS" button is clicked. Captures `convert_crane_to_bids`'s own log output
    (info/warning messages about skipped subjects, unmatched debrief rows, ...) alongside
    the final summary, so both show up together in the status panel. `debrief_export` comes
    straight from the window's optional override-file picker -- None unless the user has
    explicitly picked one, in which case it overrides this function's own auto-detection of
    the shared REDCAP group export.
    """
    handler = _ListLogHandler()
    converter_logger = logging.getLogger("mooi_toolbox.cli.crane_convert_to_bids")
    converter_logger.addHandler(handler)
    try:
        summary = convert_crane_to_bids(raw_folder, bids_folder, debrief_export)
    finally:
        converter_logger.removeHandler(handler)

    return [*handler.lines, "", _format_conversion_summary(summary)]


def main() -> None:
    run_bids_crosscheck_app(
        CRANE_DATASET_CONFIG,
        "Crane BIDS Crosscheck",
        CraneCandidateExtras(),
        settings_app_name="CraneBidsCrosscheck",
        raw_converter=_run_crane_conversion,
        override_file_label="Debrief export",
        override_file_filter="CSV files (*.csv)",
        extra_raw_action=(
            "Fix debrief record IDs...",
            "Declare corrected subject ids for debrief record_id values that don't match "
            "any known subject. Saved separately -- never edits the raw debrief export.",
            _on_fix_debrief_record_ids,
        ),
    )


if __name__ == "__main__":
    main()
