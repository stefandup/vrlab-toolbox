"""Standalone PySide6 tool: human-in-the-loop crosscheck for the longwalkV3 BIDS folder.

See docs/bids_crosscheck_plan.md and docs/bids_converter_plan.md. LongwalkV3 differs from
crane/longwalk (and FOH) in one important way: it has *no* single canonical file per scan
type per subject. A subject can have up to 3 real sessions, each with its own physiology
`.acq` recording, and each session can have several real events.tsv files (one per
city/run) -- see `processing/longwalk3_bids.py`'s module docstring. Both scan types below
are configured with `ScanTypeConfig.allow_multiple=True` (see
`processing/bids_crosscheck.py`) so the shared framework treats several matching files per
subject as normal, not a "duplicate" needing one to be picked and the rest deleted.

A third scan type, the REDCap debrief (`acq-debrief`/`_beh.tsv`, one per subject in ses-01
for now), is crosschecked alongside physiology/events.

`LongwalkV3CandidateExtras` reads each physiology `.acq`'s *headers* only (via bioread --
channel names, sample counts, rate; never the signal itself) to check there's a non-empty EDA
channel and a plausible recording length. Events (post-conversion `.tsv`) content is read with
plain pandas -- rows present and every `onset` a number, not a per-column schema validation,
since `longwalk3_bids.combine_events_df_files` suffixes almost every column with its source
`bp_id`, which varies per raw file and isn't something this GUI tries to predict. On top of
those per-file checks, `subject_issues` checks each subject's session layout as a whole (one
physiology recording and one city per session, no city repeated across sessions, debrief in
ses-01) -- see the shared `CandidateExtras.subject_issues` hook.
"""

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import cast

import bioread
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from vrlab_toolbox.gui.bids_crosscheck_common import (
    DEFAULT_CONVERT_BUTTON_TOOLTIP,
    EXTRA_RAW_ACTION_GROUP_RAW,
    CandidateExtras,
    run_bids_crosscheck_app,
)
from vrlab_toolbox.processing.bids_crosscheck import (
    BidsCrosscheckError,
    DatasetConfig,
    ScanTypeConfig,
    SubjectScan,
    parse_scans_tsv_date,
    read_scans_tsv_date,
    record_files_removed,
)
from vrlab_toolbox.processing.biopac import clean_biopac_acq_label
from vrlab_toolbox.processing.longwalk3_bids import (
    DEBRIEF_SESSION_NR,
    RAW_FILENAME_ID_CORRECTIONS_FILENAME,
    REDCAP_CROSSCHECK_ID,
    LongWalkV3ConversionSummary,
    convert_longwalkv3_to_bids,
    discover_raw_files_for_review,
    explain_unparseable_filename,
    find_debrief_export,
    load_raw_filename_id_corrections,
    resolve_subject_id,
    save_raw_filename_id_corrections,
)

logger = logging.getLogger(__name__)

PHYSIOLOGY_SCAN_TYPE = "physiology"
EVENTS_SCAN_TYPE = "events"
DEBRIEF_SCAN_TYPE = "debrief"

LONGWALKV3_DATASET_CONFIG = DatasetConfig(
    # Also the REDCap crosscheck id: the shared GUI's "Pull REDCap Data" saves to
    # redcap_{study_id}_{dataset_name}.csv, which longwalk3_bids.find_debrief_export looks for.
    dataset_name=REDCAP_CROSSCHECK_ID,
    scan_types=(
        ScanTypeConfig(name=PHYSIOLOGY_SCAN_TYPE, glob_patterns=("*.acq",), allow_multiple=True),
        ScanTypeConfig(name=EVENTS_SCAN_TYPE, glob_patterns=("*_events.tsv",), allow_multiple=True),
        # One REDCap debrief per subject for now, anchored on ses-01 (see longwalk3_bids.py's
        # DEBRIEF_SESSION_NR). Will become one per session once the per-session REDCap forms
        # exist -- at that point this needs allow_multiple=True and a per-session check in
        # `LongwalkV3CandidateExtras.subject_issues` instead of the ses-01-only one.
        ScanTypeConfig(name=DEBRIEF_SCAN_TYPE, glob_patterns=("*_acq-debrief_*_beh.tsv",)),
    ),
    # No task_tag_task/task_tag_folder_name -- like crane/longwalk, longwalkV3 has no tagging
    # step: `processing/longwalk3_bids.py` already writes real BIDS suffixes (_physio/_events)
    # itself, so there's no raw collection-software junk left to clean up.
    # longwalkV3's converter records each file's date as a scans.tsv row instead of a filename
    # prefix (see docs/bids_converter_plan.md) -- routes the crosscheck GUI's "Correct
    # date..." button to edit that row instead of renaming the file.
    dates_in_scans_tsv=True,
    # A session's physiology recording starts a few minutes before its first events export,
    # and later runs start later still -- all legitimately on the same real-world day, but
    # never the exact same minute. Day-level agreement (rather than the exact-minute default)
    # is what actually matches longwalkV3's real layout -- see bids_crosscheck.py's
    # scans_tsv_dates_agree.
    scans_tsv_date_granularity="day",
)

# The study design: up to this many real-world sessions per participant, each walking exactly
# one city, with the city order randomized per participant (so any city can turn up in any
# session, but never the same city twice).
PLANNED_SESSION_COUNT = 3
KNOWN_CITY_LABELS = ("city1", "city2", "city3")
# The only physiology channel the longwalkV3 pipeline processes (see longwalk3_pipeline.py's
# ProcessEdaPhysiologyDataStrategyStep), matched after the same label cleaning the pipeline's
# own .acq import uses (biopac.clean_biopac_acq_label, e.g. "EDA - EDA100C" -> "EDA").
REQUIRED_PHYSIOLOGY_CHANNEL = "EDA"
# Shorter than this is flagged as a likely aborted/truncated recording. The two real test
# recordings in longwalkv3_examples/ run ~10.6 and ~12.9 minutes.
MIN_PHYSIOLOGY_MINUTES = 5.0

_BIDS_ENTITY_PATTERN = re.compile(r"(?:^|_)(?P<key>ses|acq|run)-(?P<value>[A-Za-z0-9]+)")
_NO_SESSION_LABEL = "(no session)"

CHECK = "✓"
CROSS = "✗"
CHECK_COLOR = "#2ecc71"
CROSS_COLOR = "#e74c3c"
MUTED_COLOR = "#7f8c8d"
INFO_CACHE_FILENAME = "crosscheck_info_cache.json"
# Bumped whenever a parser's output shape or derivation changes, so a cached entry that still
# matches the file's mtime/size (nothing to re-read) but was computed by older logic gets
# reparsed anyway instead of silently serving stale info forever.
INFO_SCHEMA_VERSION = 2


def _bids_entities(file: Path) -> dict[str, str]:
    """The `ses`/`acq`/`run` entity values in a BIDS filename, e.g.
    `sub-01_ses-02_task-longwalkv3_acq-city3_run-001_events.tsv` ->
    `{"ses": "02", "acq": "city3", "run": "001"}`."""
    return {m.group("key"): m.group("value") for m in _BIDS_ENTITY_PATTERN.finditer(file.name)}


def _session_label(file: Path) -> str:
    session = _bids_entities(file).get("ses")
    return f"ses-{session}" if session else _NO_SESSION_LABEL


def _run_sort_key(file: Path) -> str:
    return _bids_entities(file).get("run", "")


def _date_span(ok: bool | None, text: str) -> str:
    """`text` in green (matches), red (doesn't), or muted (nothing to compare against)."""
    color = MUTED_COLOR if ok is None else CHECK_COLOR if ok else CROSS_COLOR
    return f'<span style="color:{color}">{text}</span>'


@dataclass
class LongwalkV3PhysiologyInfo:
    readable: bool
    duration_minutes: float | None = None
    sample_rate_hz: float | None = None
    channel_labels: list[str] = field(default_factory=list)
    # None if there's no REQUIRED_PHYSIOLOGY_CHANNEL at all -- 0 if there is one, but empty.
    eda_point_count: int | None = None

    def problems(self) -> list[str]:
        if not self.readable:
            return ["Could not read this .acq file"]
        problems = []
        if self.eda_point_count is None:
            found = ", ".join(self.channel_labels) or "none"
            problems.append(f"No {REQUIRED_PHYSIOLOGY_CHANNEL} channel (channels found: {found})")
        elif self.eda_point_count == 0:
            problems.append(f"{REQUIRED_PHYSIOLOGY_CHANNEL} channel has no samples")
        if self.duration_minutes is not None and self.duration_minutes < MIN_PHYSIOLOGY_MINUTES:
            problems.append(
                f"Only {self.duration_minutes:.1f} min recorded (expected at least "
                f"{MIN_PHYSIOLOGY_MINUTES:g} min) -- aborted or truncated recording?"
            )
        return problems


@dataclass
class LongwalkV3EventsInfo:
    n_rows: int | None
    n_columns: int | None
    has_onset: bool
    # Rows whose onset is missing or not a number -- e.g. what the Unreal-side export's
    # always-0.0 behaviour.csv TimeStamp turns into (see docs/pipeline_next_steps.md item 31).
    n_bad_onsets: int = 0

    def problems(self) -> list[str]:
        if self.n_rows is None:
            return ["Could not read this events file"]
        problems = []
        if self.n_rows == 0:
            problems.append("No events -- header only")
        if not self.has_onset:
            problems.append("Missing the expected 'onset' column")
        elif self.n_bad_onsets:
            problems.append(
                f"{self.n_bad_onsets} of {self.n_rows} onset(s) missing or not a number"
            )
        return problems


@dataclass
class LongwalkV3DebriefInfo:
    n_rows: int | None

    def problems(self) -> list[str]:
        if self.n_rows is None:
            return ["Could not read this debrief file"]
        if self.n_rows == 0:
            return ["Debrief file has no rows -- header only"]
        return []


LongwalkV3FileInfo = LongwalkV3PhysiologyInfo | LongwalkV3EventsInfo | LongwalkV3DebriefInfo
_INFO_CLASSES: dict[str, type[LongwalkV3FileInfo]] = {
    PHYSIOLOGY_SCAN_TYPE: LongwalkV3PhysiologyInfo,
    EVENTS_SCAN_TYPE: LongwalkV3EventsInfo,
    DEBRIEF_SCAN_TYPE: LongwalkV3DebriefInfo,
}


def _parse_physiology_info(file: Path) -> LongwalkV3PhysiologyInfo:
    """Reads only the .acq headers (channel names, sample counts, rates) via bioread -- never
    the signal data itself, so this stays fast even for long recordings."""
    try:
        headers = bioread.read_headers(str(file))
    except Exception:
        logger.warning("Could not read physiology headers from %s", file, exc_info=True)
        return LongwalkV3PhysiologyInfo(readable=False)
    # bioread hands back None rather than raising for some non-.acq/corrupt files.
    if headers is None:
        logger.warning("Could not read physiology headers from %s", file)
        return LongwalkV3PhysiologyInfo(readable=False)

    base_rate = float(headers.samples_per_second)
    labels = [clean_biopac_acq_label(channel.name or "") for channel in headers.channels]
    durations = [
        (channel.point_count or 0) / (base_rate / channel.frequency_divider)
        for channel in headers.channels
        if base_rate and channel.frequency_divider
    ]
    eda_point_count = next(
        (
            int(channel.point_count or 0)
            for channel, label in zip(headers.channels, labels, strict=True)
            if label == REQUIRED_PHYSIOLOGY_CHANNEL
        ),
        None,
    )
    return LongwalkV3PhysiologyInfo(
        readable=True,
        duration_minutes=max(durations) / 60 if durations else None,
        sample_rate_hz=base_rate or None,
        channel_labels=labels,
        eda_point_count=eda_point_count,
    )


def _parse_events_info(file: Path) -> LongwalkV3EventsInfo:
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception:
        logger.warning("Could not read events data from %s", file, exc_info=True)
        return LongwalkV3EventsInfo(n_rows=None, n_columns=None, has_onset=False)

    has_onset = "onset" in df.columns
    n_bad_onsets = (
        int(pd.Series(pd.to_numeric(df["onset"], errors="coerce")).isna().sum()) if has_onset else 0
    )
    return LongwalkV3EventsInfo(
        n_rows=len(df), n_columns=len(df.columns), has_onset=has_onset, n_bad_onsets=n_bad_onsets
    )


def _parse_debrief_info(file: Path) -> LongwalkV3DebriefInfo:
    try:
        df = pd.read_csv(file, sep="\t")
    except Exception:
        logger.warning("Could not read debrief data from %s", file, exc_info=True)
        return LongwalkV3DebriefInfo(n_rows=None)
    return LongwalkV3DebriefInfo(n_rows=len(df))


_PARSERS = {
    PHYSIOLOGY_SCAN_TYPE: _parse_physiology_info,
    EVENTS_SCAN_TYPE: _parse_events_info,
    DEBRIEF_SCAN_TYPE: _parse_debrief_info,
}


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


def _status_span(ok: bool, text: str) -> str:
    color = CHECK_COLOR if ok else CROSS_COLOR
    return f'<span style="color:{color}">{text} {CHECK if ok else CROSS}</span>'


def _problems_html(problems: list[str]) -> str:
    return "<br>".join(f'<span style="color:{CROSS_COLOR}">{CROSS} {p}</span>' for p in problems)


class LongwalkV3CandidateExtras(CandidateExtras):
    """Advisory longwalkV3 file and session checks; never gates renaming.

    Per file: physiology `.acq` headers (EDA channel present and non-empty, recording long
    enough), events `.tsv` content (readable, has rows, every onset a number) and city label,
    debrief `.tsv` readable with at least one row. Per subject (see `subject_issues`): each
    session has exactly one physiology recording and events for exactly one city, no city is
    repeated across sessions, and the debrief sits in ses-01.

    Every file parse result is cached on disk (see INFO_CACHE_FILENAME), keyed by the file's
    path relative to the BIDS folder plus its mtime/size, same shape as crane's/longwalk's own
    cache (`crane_bids_crosscheck_gui.py`/`longwalk_bids_crosscheck_gui.py`).
    """

    subject_issue_legend = (
        "a session-level problem across this subject's files (e.g. a session missing its "
        "physiology, or two cities in one session) -- see the Overview in the detail pane"
    )

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

    def problems(self, scan_type: str, file: Path) -> list[str]:
        """Everything wrong with one file on its own -- content (cached) plus, for events,
        whether its filename's city label is one of KNOWN_CITY_LABELS."""
        if scan_type not in _PARSERS:
            return []
        problems = self._file_info(scan_type, file).problems()
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            date_problem = self._physiology_date_problem(file)
            if date_problem:
                problems.append(date_problem)
        if scan_type == EVENTS_SCAN_TYPE:
            city = _bids_entities(file).get("acq")
            if city not in KNOWN_CITY_LABELS:
                problems.append(
                    f"Unexpected city label {city!r} in the filename (expected one of "
                    f"{', '.join(KNOWN_CITY_LABELS)})"
                )
        return problems

    def describe(self, scan_type: str, file: Path) -> str | None:
        if scan_type not in _PARSERS:
            return None
        ok = not self.problems(scan_type, file)
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            minutes = f"{info.duration_minutes:.1f} min " if info.duration_minutes else ""
            status = _status_span(
                ok, f"{_session_label(file)} {minutes}{REQUIRED_PHYSIOLOGY_CHANNEL}"
            )
            return f"{status} &nbsp;{self._physiology_date_html(file)}"
        if scan_type == EVENTS_SCAN_TYPE:
            info = self._events_info(file)
            city = _bids_entities(file).get("acq", "?")
            rows = f" <b>{info.n_rows}</b> rows" if info.n_rows is not None else ""
            return _status_span(ok, f"{_session_label(file)} {city}{rows}")
        return _status_span(ok, "Debrief")

    def describe_tooltip(self, scan_type: str, file: Path) -> str | None:
        if scan_type not in _PARSERS:
            return None
        problems = self.problems(scan_type, file)
        return "\n".join(problems) if problems else "All checks passed"

    def detail(self, scan_type: str, file: Path) -> str | None:
        if scan_type not in _PARSERS:
            return None
        lines = [f"<b>{file.name}</b>"]
        if scan_type == PHYSIOLOGY_SCAN_TYPE:
            info = self._physiology_info(file)
            if info.readable:
                if info.duration_minutes is not None:
                    lines.append(f"Duration: {info.duration_minutes:.1f} min")
                if info.sample_rate_hz:
                    lines.append(f"Sample rate: {info.sample_rate_hz:g} Hz")
                lines.append(f"Channels: {', '.join(info.channel_labels) or 'none'}")
            lines.append(f"Date (scans.tsv): {self._physiology_date_html(file)}")
        elif scan_type == EVENTS_SCAN_TYPE:
            info = self._events_info(file)
            if info.n_rows is not None:
                lines.append(f"{info.n_rows} row(s), {info.n_columns} column(s)")
        else:
            info = self._debrief_info(file)
            if info.n_rows is not None:
                lines.append(f"{info.n_rows} row(s)")

        problems = self.problems(scan_type, file)
        lines.append(
            _problems_html(problems)
            if problems
            else f'<span style="color:{CHECK_COLOR}">{CHECK} All checks passed</span>'
        )
        return "<br>".join(lines)

    def date_correction_available(self, scan_type: str) -> bool:
        """Only physiology: its date comes from the raw .acq filename, typed/set on the
        recording PC, so it can genuinely be mislabeled (see `_physiology_date_problem`).
        Events/debrief dates are derived by the converter itself, not worth hand-editing."""
        return scan_type == PHYSIOLOGY_SCAN_TYPE

    def scans_tsv_row_actions_available(self) -> bool:
        # Read-only scans.tsv pane for now -- physiology's "Correct date..." above is the one
        # date fix longwalkV3 needs; wrong runs/files are removed via Subject Actions instead.
        return False

    # No task_tag_available/filename_correction_available overrides -- falls back to
    # CandidateExtras' own defaults (False for both). See LONGWALKV3_DATASET_CONFIG's comment:
    # there's no raw collection-software junk left to tag/clean up here, and no duplicate
    # marker to strip either -- physiology/events both allow_multiple, so nothing here ever
    # goes through the "duplicate -> pick one -> commit" flow that free-text filename
    # correction and duplicate-marker stripping exist for.

    def refreshable(self, scan_type: str) -> bool:
        return scan_type in _PARSERS

    def refresh(self, scan_type: str, file: Path) -> None:
        """Force a reparse for one candidate. Caller batches the disk write via `flush()`."""
        if scan_type in _PARSERS:
            self._file_info(scan_type, file, force=True)

    def has_warning(self, scan_type: str, file: Path) -> bool:
        return bool(self.problems(scan_type, file))

    def subject_issues(self, subject_id: str, subject_scans: dict[str, SubjectScan]) -> list[str]:
        sessions = self._files_by_session(subject_scans)
        issues = []
        city_sessions: dict[str, list[str]] = {}
        for session, files in sessions.items():
            physiology = files[PHYSIOLOGY_SCAN_TYPE]
            events = files[EVENTS_SCAN_TYPE]
            if not physiology:
                issues.append(f"{session}: no physiology recording")
            elif len(physiology) > 1:
                issues.append(
                    f"{session}: {len(physiology)} physiology recordings (expected one per session)"
                )
            if not events:
                issues.append(f"{session}: no events files")
            for physiology_file in physiology:
                date_problem = self._physiology_date_problem(physiology_file)
                if date_problem:
                    issues.append(f"{session}: {date_problem}")

            cities = self._session_cities(events)
            for city in cities:
                city_sessions.setdefault(city, []).append(session)
            if len(cities) > 1:
                runs = ", ".join(
                    f"{_bids_entities(f).get('acq', '?')} run-{_bids_entities(f).get('run', '?')}"
                    for f in events
                )
                issues.append(
                    f"{session}: more than one city ({runs}) -- a wrong-city start that was "
                    "restarted? Only one city belongs in a session; remove the wrong run."
                )

        for city, city_session_list in sorted(city_sessions.items()):
            if len(city_session_list) > 1:
                issues.append(
                    f"{city} was walked in more than one session ({', '.join(city_session_list)})"
                    " -- each session should be a different city"
                )

        real_sessions = [s for s in sessions if s != _NO_SESSION_LABEL]
        if len(real_sessions) > PLANNED_SESSION_COUNT:
            issues.append(
                f"{len(real_sessions)} sessions found, but only {PLANNED_SESSION_COUNT} are planned"
            )
        if _NO_SESSION_LABEL in sessions:
            issues.append("Some files have no ses-NN entity in their filename")

        debrief_session = f"ses-{DEBRIEF_SESSION_NR:02d}"
        for file in subject_scans[DEBRIEF_SCAN_TYPE].files:
            if _session_label(file) != debrief_session:
                issues.append(
                    f"Debrief file is in {_session_label(file)}, expected {debrief_session}"
                )
        return issues

    def subject_summary(self, subject_id: str, subject_scans: dict[str, SubjectScan]) -> str | None:
        sessions = self._files_by_session(subject_scans)
        real_sessions = [s for s in sessions if s != _NO_SESSION_LABEL]
        lines = [f"<b>{len(real_sessions)} of {PLANNED_SESSION_COUNT} planned sessions found</b>"]
        planned = [f"ses-{nr:02d}" for nr in range(1, PLANNED_SESSION_COUNT + 1)]
        for session in sorted(set(planned) | set(sessions)):
            files = sessions.get(session)
            if files is None:
                lines.append(
                    f'<span style="color:{MUTED_COLOR}">{session}: not recorded yet</span>'
                )
                continue
            cities = self._session_cities(files[EVENTS_SCAN_TYPE]) or ["no city"]
            physiology = [
                f"{info.duration_minutes:.1f} min"
                if (info := self._physiology_info(f)).duration_minutes is not None
                else "unreadable"
                for f in files[PHYSIOLOGY_SCAN_TYPE]
            ]
            lines.append(
                f"{session}: <b>{', '.join(cities)}</b> &nbsp;·&nbsp; physiology "
                f"{', '.join(physiology) or 'missing'}"
            )

        debrief_files = subject_scans[DEBRIEF_SCAN_TYPE].files
        lines.append(
            _status_span(True, f"Debrief ({_session_label(debrief_files[0])})")
            if debrief_files
            else _status_span(False, "Debrief missing")
        )
        return "<br>".join(lines)

    def _files_by_session(
        self, subject_scans: dict[str, SubjectScan]
    ) -> dict[str, dict[str, list[Path]]]:
        """`{session_label: {PHYSIOLOGY_SCAN_TYPE: [...], EVENTS_SCAN_TYPE: [...]}}` -- only
        sessions that actually have physiology or events files, each list in run order."""
        sessions: dict[str, dict[str, list[Path]]] = {}
        for scan_type in (PHYSIOLOGY_SCAN_TYPE, EVENTS_SCAN_TYPE):
            for file in subject_scans[scan_type].files:
                session_files = sessions.setdefault(
                    _session_label(file), {PHYSIOLOGY_SCAN_TYPE: [], EVENTS_SCAN_TYPE: []}
                )
                session_files[scan_type].append(file)
        for session_files in sessions.values():
            for files in session_files.values():
                files.sort(key=_run_sort_key)
        return dict(sorted(sessions.items()))

    def _scans_tsv_datetime(self, file: Path) -> datetime | None:
        if self._bids_folder is None:
            return None
        return parse_scans_tsv_date(read_scans_tsv_date(self._bids_folder, file))

    def _session_events_dates(self, physiology_file: Path) -> list[datetime]:
        """scans.tsv dates of every events file in the same session as `physiology_file` --
        physiology and events share one `ses-NN/beh/` folder (see longwalk3_bids.py)."""
        session = _session_label(physiology_file)
        return [
            date
            for events_file in sorted(physiology_file.parent.glob("*_events.tsv"))
            if _session_label(events_file) == session
            and (date := self._scans_tsv_datetime(events_file)) is not None
        ]

    def _physiology_date_matches(self, file: Path) -> bool | None:
        """Whether a physiology file's scans.tsv date falls on the same day as its session's
        events -- None if either side has no parseable date to compare. The physiology date
        comes from the raw .acq filename (set on the recording PC), the events dates from
        inside the Unreal export itself, so a mismatch points at a mislabeled physiology date.
        """
        physiology_date = self._scans_tsv_datetime(file)
        events_dates = self._session_events_dates(file)
        if physiology_date is None or not events_dates:
            return None
        return any(date.date() == physiology_date.date() for date in events_dates)

    def _physiology_date_problem(self, file: Path) -> str | None:
        if self._physiology_date_matches(file) is not False:
            return None
        physiology_date = self._scans_tsv_datetime(file)
        assert physiology_date is not None
        events_days = sorted({f"{date:%Y-%m-%d}" for date in self._session_events_dates(file)})
        return (
            f"Physiology dated {physiology_date:%Y-%m-%d}, but this session's events are dated "
            f'{", ".join(events_days)} -- mislabeled physiology date? Fix with "Correct date...".'
        )

    def _physiology_date_html(self, file: Path) -> str:
        raw_date = (
            read_scans_tsv_date(self._bids_folder, file) if self._bids_folder is not None else None
        )
        parsed = parse_scans_tsv_date(raw_date)
        text = f"{parsed:%Y-%m-%d %H:%M}" if parsed is not None else (raw_date or "no date")
        return _date_span(self._physiology_date_matches(file), text)

    @staticmethod
    def _session_cities(events: list[Path]) -> list[str]:
        """Distinct city labels among a session's events files, in run order."""
        cities: list[str] = []
        for file in events:
            city = _bids_entities(file).get("acq", "?")
            if city not in cities:
                cities.append(city)
        return cities

    def _cache_key(self, file: Path) -> str:
        if self._bids_folder is None:
            return file.name
        try:
            return file.relative_to(self._bids_folder).as_posix()
        except ValueError:
            return file.name

    def _physiology_info(self, file: Path) -> LongwalkV3PhysiologyInfo:
        return cast(LongwalkV3PhysiologyInfo, self._file_info(PHYSIOLOGY_SCAN_TYPE, file))

    def _events_info(self, file: Path) -> LongwalkV3EventsInfo:
        return cast(LongwalkV3EventsInfo, self._file_info(EVENTS_SCAN_TYPE, file))

    def _debrief_info(self, file: Path) -> LongwalkV3DebriefInfo:
        return cast(LongwalkV3DebriefInfo, self._file_info(DEBRIEF_SCAN_TYPE, file))

    def _file_info(self, scan_type: str, file: Path, force: bool = False) -> LongwalkV3FileInfo:
        key = self._cache_key(file)
        stat = file.stat()
        cached = self._disk_cache.get(key)
        if not force and cached is not None:
            if (
                cached.get("mtime") == stat.st_mtime
                and cached.get("size") == stat.st_size
                and cached.get("info_version") == INFO_SCHEMA_VERSION
                and cached.get("scan_type") == scan_type
            ):
                try:
                    return _INFO_CLASSES[scan_type](**cached["info"])
                except (TypeError, KeyError):
                    logger.warning("Stale info-cache entry for %s -- reparsing", file)

        info = _PARSERS[scan_type](file)
        self._disk_cache[key] = {
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "info_version": INFO_SCHEMA_VERSION,
            "scan_type": scan_type,
            "info": asdict(info),
        }
        self._dirty = True
        return info


class _ListLogHandler(logging.Handler):
    """Captures formatted log records into a list instead of printing them -- used to relay
    `convert_longwalkv3_to_bids`'s `logger.info`/`logger.warning` calls into the crosscheck
    GUI's status panel, since that function reports progress/problems via the standard logger
    rather than a GUI-specific callback (see its own docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(f"[{record.levelname}] {self.format(record)}")


def _format_conversion_summary(summary: LongWalkV3ConversionSummary) -> str:
    if not summary.new_subject_ids and not summary.backfilled_debrief_ids:
        return "No new subjects found -- everything in the raw folder is already converted."

    lines = [f"Added {len(summary.new_subject_ids)} new subject(s):", ""]
    for subject_id in summary.new_subject_ids:
        physiology = ", ".join(p.name for p in summary.subject_physiology.get(subject_id, []))
        events = ", ".join(p.name for p in summary.subject_events.get(subject_id, []))
        debrief = summary.subject_debrief.get(subject_id)
        lines.append(f"sub-{subject_id}")
        lines.append(f"    physiology: {physiology or '(missing)'}")
        lines.append(f"    events:     {events or '(missing)'}")
        lines.append(f"    debrief:    {debrief.name if debrief else '(missing)'}")

    if summary.backfilled_debrief_ids:
        lines.append("")
        lines.append(
            f"Backfilled debrief for {len(summary.backfilled_debrief_ids)} already-converted "
            f"subject(s): {', '.join(summary.backfilled_debrief_ids)}"
        )

    if summary.unparseable_files:
        lines.append("")
        lines.append(f"Could not parse {len(summary.unparseable_files)} raw filename(s):")
        lines.extend(f"    {file.name}" for file in summary.unparseable_files)

    return "\n".join(lines)


class RawFilenameCorrectionDialog(QDialog):
    """Lets a human declare "this raw filename really belongs to this subject" for *any* raw
    physiology/behaviour/actor-log file, not just ones that fail to parse a subject id at all.
    Corrections are saved to their own JSON
    (`longwalk3_bids.save_raw_filename_id_corrections`, in the BIDS folder) and applied the
    next time "Refresh BIDS" runs (`longwalk3_bids.resolve_subject_id`). Same shape as
    crane's/longwalk's `RawFilenameCorrectionDialog`, scoped to longwalkV3's raw physiology
    `.acq` plus every raw csv (behaviour.csv and its sibling actor-location logs).

    The bottom pane explains why the selected filename failed to parse, or what it currently
    resolves to if it didn't (`explain_unparseable_filename`/`resolve_subject_id`), and shows
    any matching line from the last "Refresh BIDS" run's captured log output
    (`parent.last_conversion_log_lines`) -- both reuse existing machinery rather than building
    a new diagnostic path.
    """

    def __init__(self, raw_folder: Path, bids_folder: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.raw_folder = raw_folder
        self.bids_folder = bids_folder
        self._log_lines: list[str] = getattr(parent, "last_conversion_log_lines", [])
        self.setWindowTitle("Fix raw filenames")
        self.resize(760, 560)

        layout = QVBoxLayout(self)
        self._existing_corrections = load_raw_filename_id_corrections(bids_folder)
        self._files = discover_raw_files_for_review(raw_folder)

        if not self._files:
            layout.addWidget(
                QLabel("No physiology/behaviour/actor-log raw files found in the raw folder.")
            )
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)
            return

        info_label = QLabel(
            "Every raw physiology (.acq) and behaviour/actor-log (.csv) file, with the "
            "subject id it currently resolves to. Type a corrected subject id for any row "
            "that's wrong -- whether the filename didn't parse at all, or parsed fine but to "
            "the wrong id. Leave blank to make no change. This never renames the raw file; "
            'corrections are saved separately and applied the next time you click "Refresh '
            'BIDS".'
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.table = QTableWidget(len(self._files), 3)
        self.table.setHorizontalHeaderLabels(
            ["Filename", "Currently resolves to", "Corrected subject id"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 180)
        self.table.verticalHeader().setVisible(False)
        for row, file in enumerate(self._files):
            key = self._key(file)
            name_item = QTableWidgetItem(key)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            resolved = resolve_subject_id(file, raw_folder, self._existing_corrections)
            resolved_item = QTableWidgetItem(resolved if resolved else "(unparseable)")
            resolved_item.setFlags(resolved_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if resolved is None:
                resolved_item.setForeground(QBrush(QColor(CROSS_COLOR)))
            self.table.setItem(row, 1, resolved_item)

            self.table.setItem(row, 2, QTableWidgetItem(self._existing_corrections.get(key, "")))
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        # Persistent bottom pane -- always visible below the table, updated for whichever row
        # is currently selected, same spirit as bids_crosscheck_common.py's "Last conversion"
        # status panel (fixed-height QTextEdit, not a popup).
        reason_group = QGroupBox("Details")
        reason_layout = QVBoxLayout(reason_group)
        self.reason_text = QTextEdit()
        self.reason_text.setReadOnly(True)
        self.reason_text.setFont(QFont("Courier New"))
        self.reason_text.setMaximumHeight(140)
        self.reason_text.setPlainText("Select a row above to see details.")
        reason_layout.addWidget(self.reason_text)
        layout.addWidget(reason_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _key(self, file: Path) -> str:
        try:
            return file.relative_to(self.raw_folder).as_posix()
        except ValueError:
            return file.name

    def _on_selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectedIndexes()}
        if not rows:
            self.reason_text.setPlainText("Select a row above to see details.")
            return
        file = self._files[min(rows)]
        resolved = resolve_subject_id(file, self.raw_folder, self._existing_corrections)
        if resolved is None:
            detail = explain_unparseable_filename(file)
        else:
            detail = f"Currently resolves to subject id {resolved!r} from the filename."
        relevant_lines = [line for line in self._log_lines if file.name in line]
        if relevant_lines:
            log_text = "\n".join(relevant_lines)
        else:
            log_text = (
                '(no matching line from the last "Refresh BIDS" run in this session -- run '
                "it again to see one)"
            )
        self.reason_text.setPlainText(f"{detail}\n\nFrom the last conversion run:\n{log_text}")

    def _on_save(self) -> None:
        corrections = load_raw_filename_id_corrections(self.bids_folder)
        for row, file in enumerate(self._files):
            key = self._key(file)
            item = self.table.item(row, 2)
            corrected_id = item.text().strip() if item is not None else ""
            if corrected_id:
                corrections[key] = corrected_id
            else:
                corrections.pop(key, None)
        save_raw_filename_id_corrections(self.bids_folder, corrections)
        self.accept()


class RemoveSubjectFileDialog(QDialog):
    """Pick one of a subject's files of one scan type to remove from BIDS: a session dropdown
    (only sessions that actually have a file of this type), then a second dropdown with that
    session's files -- labelled by run for events (e.g. "run-002 (city3)"), by filename
    otherwise. Removal itself is `bids_crosscheck.record_files_removed`, done by the caller.
    """

    def __init__(
        self, bids_folder: Path, scan_type: str, files: list[Path], parent: QWidget | None = None
    ):
        super().__init__(parent)
        self.bids_folder = bids_folder
        self.scan_type = scan_type
        self._files_by_session: dict[str, list[Path]] = {}
        for file in sorted(files, key=lambda f: (_session_label(f), _run_sort_key(f))):
            self._files_by_session.setdefault(_session_label(file), []).append(file)

        self.setWindowTitle(f"Remove {scan_type}")
        self.resize(560, 0)
        layout = QVBoxLayout(self)

        info_label = QLabel(
            f"Removes the chosen {scan_type} file from BIDS, together with its scans.tsv row. "
            "The raw folder is never touched, so it can be brought back with "
            '"Restore from raw..." (which re-derives this whole subject from raw).'
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        form = QFormLayout()
        self.session_combo = QComboBox()
        self.session_combo.addItems(list(self._files_by_session))
        form.addRow("Session:", self.session_combo)
        self.file_combo = QComboBox()
        form.addRow("Run:" if scan_type == EVENTS_SCAN_TYPE else "File:", self.file_combo)
        self.reason_edit = QLineEdit()
        self.reason_edit.setPlaceholderText("e.g. wrong city started by mistake (optional)")
        form.addRow("Reason:", self.reason_edit)
        layout.addLayout(form)

        self.file_detail_label = QLabel()
        self.file_detail_label.setWordWrap(True)
        self.file_detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.file_detail_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("Remove")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.session_combo.currentTextChanged.connect(self._on_session_changed)
        self.file_combo.currentIndexChanged.connect(self._on_file_changed)
        self._on_session_changed(self.session_combo.currentText())

    def _file_label(self, file: Path) -> str:
        if self.scan_type == EVENTS_SCAN_TYPE:
            entities = _bids_entities(file)
            return f"run-{entities.get('run', '?')} ({entities.get('acq', '?')})"
        return file.name

    def _on_session_changed(self, session: str) -> None:
        self.file_combo.clear()
        for file in self._files_by_session.get(session, []):
            self.file_combo.addItem(self._file_label(file), file)
        self._on_file_changed()

    def _on_file_changed(self) -> None:
        file = self.selected_file()
        if file is None:
            self.file_detail_label.setText("")
            return
        date = read_scans_tsv_date(self.bids_folder, file) or "no date"
        self.file_detail_label.setText(f"{file.name}\nscans.tsv date: {date}")

    def selected_file(self) -> Path | None:
        return self.file_combo.currentData()

    def reason(self) -> str | None:
        return self.reason_edit.text().strip() or None


def _remove_subject_file_action(scan_type: str):
    """Builds the `extra_subject_actions` callback that opens `RemoveSubjectFileDialog` for
    `scan_type` and, once confirmed, removes the chosen file via `record_files_removed`."""

    def callback(
        bids_folder: Path,
        subject_id: str,
        subject_scans: dict[str, SubjectScan],
        parent: QWidget,
    ) -> bool:
        files = list(subject_scans[scan_type].files)
        if not files:
            QMessageBox.information(
                parent, f"Remove {scan_type}", f"sub-{subject_id} has no {scan_type} files."
            )
            return False
        dialog = RemoveSubjectFileDialog(bids_folder, scan_type, files, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        file = dialog.selected_file()
        if file is None:
            return False
        confirm = QMessageBox.question(
            parent,
            f"Remove {scan_type}",
            f"Remove this file from BIDS?\n\n{file.name}\n\n"
            "The raw folder is untouched -- the file comes back only via "
            '"Restore from raw...".',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return False
        try:
            record_files_removed(bids_folder, subject_id, scan_type, [file], dialog.reason())
        except (BidsCrosscheckError, OSError) as error:
            QMessageBox.warning(parent, f"Could not remove {scan_type}", str(error))
            return False
        return True

    return callback


def _on_fix_raw_filenames(raw_folder: Path, bids_folder: Path, parent: QWidget) -> None:
    """The longwalkV3-specific `extra_raw_actions` callback for the "Fix raw filenames..."
    button -- see `RawFilenameCorrectionDialog`.
    """
    RawFilenameCorrectionDialog(raw_folder, bids_folder, parent).exec()


def _run_longwalkv3_conversion(
    raw_folder: Path, bids_folder: Path, debrief_export: Path | None
) -> list[str]:
    """The longwalkV3-specific `raw_converter` callback `BidsCrosscheckWindow` calls when the
    "Refresh BIDS" button is clicked. Captures `convert_longwalkv3_to_bids`'s own log output
    (info/warning messages about skipped subjects, unparseable filenames, ...) alongside the
    final summary, so both show up together in the status panel. `debrief_export` is the
    REDCap csv to use: the human's "Debrief Data" pick, else the file the window just pulled
    from REDCap -- or None, leaving the converter to auto-detect one (see
    `longwalk3_bids.find_debrief_export`).
    """
    handler = _ListLogHandler()
    converter_logger = logging.getLogger("vrlab_toolbox.processing.longwalk3_bids")
    converter_logger.addHandler(handler)
    try:
        summary = convert_longwalkv3_to_bids(raw_folder, bids_folder, debrief_export)
    finally:
        converter_logger.removeHandler(handler)

    return [*handler.lines, "", _format_conversion_summary(summary)]


def main() -> None:
    run_bids_crosscheck_app(
        LONGWALKV3_DATASET_CONFIG,
        "LongwalkV3 BIDS Crosscheck",
        LongwalkV3CandidateExtras(),
        settings_app_name="LongwalkV3BidsCrosscheck",
        raw_converter=_run_longwalkv3_conversion,
        window_icon_path=Path("assets") / "longwalkv3_icon.png",
        override_file_label="Debrief Data",
        override_file_filter="CSV files (*.csv)",
        override_file_autodetect=find_debrief_export,
        extra_raw_actions=[
            (
                "Fix Filenames in Raw Folder",
                "Review every raw physiology/behaviour/actor-log filename and, if needed, "
                "declare its correct subject id. Saved separately -- never renames the raw "
                "file.",
                _on_fix_raw_filenames,
                EXTRA_RAW_ACTION_GROUP_RAW,
            ),
        ],
        convert_button_tooltip=DEFAULT_CONVERT_BUTTON_TOOLTIP,
        extra_backup_filenames=(RAW_FILENAME_ID_CORRECTIONS_FILENAME,),
        enable_redcap=True,
        extra_subject_actions=[
            (
                "Remove events by run...",
                "Pick a session and one of its runs to remove from BIDS -- e.g. a wrong city "
                "that was started by mistake and then restarted.",
                _remove_subject_file_action(EVENTS_SCAN_TYPE),
                True,
            ),
            (
                "Remove physiology...",
                "Pick a session's physiology recording to remove from BIDS.",
                _remove_subject_file_action(PHYSIOLOGY_SCAN_TYPE),
                False,
            ),
            (
                "Remove debrief...",
                "Remove this subject's debrief file from BIDS.",
                _remove_subject_file_action(DEBRIEF_SCAN_TYPE),
                False,
            ),
        ],
    )


if __name__ == "__main__":
    main()
