import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from vrlab_toolbox import vrlab_logging
from vrlab_toolbox.processing.longwalk3_dummy_data import (
    DEFAULT_CITY_LABELS,
    ERROR_TYPES,
    SHAPE_ERROR_TYPES,
    SHAPE_MANIFEST_FILENAME,
    generate_dummy_longwalkv3_dataset,
    generate_dummy_longwalkv3_dataset_from_shape,
    write_longwalkv3_shape_manifest,
)

EXAMPLES_EPILOG = f"""
Examples:

\b
  Recommended -- from a reviewed shape manifest (current export format), 1 clean participant
  plus one per error scenario ({", ".join(SHAPE_ERROR_TYPES)}), reproducible:
  longwalk3_generate_sample_data longwalkv3_examples/shape/{SHAPE_MANIFEST_FILENAME} \\
    longwalkv3_examples/dummy_data --with-errors --seed 1

\b
  Legacy template mode -- 1 clean dummy participant ("dummy01"), reproducible, one city per
  session (ses-01=city1, ses-02=city2, ses-03=city3) -- cloned from old raw templates with
  date and worldLocation columns reshaped (see longwalk3_dummy_data.py):
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy

\b
  Also add one participant per known error scenario: {", ".join(ERROR_TYPES)}:
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy --with-errors

\b
  5 clean dummy participants, only city1/city2:
  longwalk3_generate_sample_data longwalkv3_examples longwalk3_examples_dummy \\
    --n-clean 5 --cities city1 --cities city2

\b
  Profile the *shape* of a real, extracted longwalkV3 data folder (sub-<id>/ses-*/...) into
  shape_out/{SHAPE_MANIFEST_FILENAME} -- structure only, no data values; review it before
  sharing:
  longwalk3_generate_sample_data --profile-shape path/to/longwalkv3_data shape_out

\b
  Same, also profiling a REDCap debrief export kept outside the data folder (exports sitting
  directly in the data folder are picked up automatically):
  longwalk3_generate_sample_data --profile-shape path/to/longwalkv3_data shape_out \\
    --redcap-export path/to/Project_DATA_2026-11-18_1200.csv
"""


@click.command(epilog=EXAMPLES_EPILOG)
@click.version_option(package_name="vrlab-toolbox")
@click.argument(
    "template_folder", type=click.Path(exists=True, dir_okay=True, path_type=Path), required=True
)
@click.argument("output_folder", type=click.Path(path_type=Path), required=True)
@click.option(
    "--n-clean", default=1, show_default=True, help="Number of well-formed dummy participants"
)
@click.option(
    "--with-errors",
    is_flag=True,
    help="Also generate one participant per known error scenario (shape mode: "
    f"{', '.join(SHAPE_ERROR_TYPES)}; legacy template mode: {', '.join(ERROR_TYPES)})",
)
@click.option(
    "--cities",
    multiple=True,
    default=DEFAULT_CITY_LABELS,
    show_default=True,
    help="Task labels to generate a behaviour/actor-log file set for, repeatable "
    "(--cities city1 --cities city2 ...).",
)
@click.option("--seed", type=int, default=None, help="Seed for reproducible generation")
@click.option(
    "--profile-shape",
    is_flag=True,
    help="Don't generate anything: treat TEMPLATE_FOLDER as a real, extracted longwalkV3 data "
    f"folder, search it recursively for .csv and .acq files, and write OUTPUT_FOLDER/"
    f"{SHAPE_MANIFEST_FILENAME} describing its structure only (no data values). "
    "--n-clean/--with-errors/--cities/--seed are ignored.",
)
@click.option(
    "--redcap-export",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="With --profile-shape: also profile this REDCap debrief export (.csv) into the "
    "manifest's redcap_exports. REDCap exports directly in TEMPLATE_FOLDER are found anyway.",
)
def main(
    template_folder: Path,
    output_folder: Path,
    n_clean: int,
    with_errors: bool,
    cities: tuple[str, ...],
    seed: int | None,
    profile_shape: bool,
    redcap_export: Path | None,
) -> None:
    """Generate synthetic longwalkV3 participant data, or profile real data's shape. Three modes,
    picked by the first argument and flags:

    \b
    1. Shape mode (recommended) -- TEMPLATE_FOLDER is a reviewed shape manifest (.json, made
       with --profile-shape). Writes the current real export's layout under OUTPUT_FOLDER:
       sub-dummyNN/ses-NN/ with one <timestamp>_sub-<id>_longwalkv3out.acq per session plus
       one behaviour.csv and the actor logs per run (run-00N/ subfolders when a run was
       restarted). Headers, header repeats, row counts, actor counts, time spans, which actor
       logs each city has, ragged rows, and the .acq channels/rate/duration all follow the
       manifest; cell values, EDA signal and Trigger pulses are synthetic. If the manifest has
       a REDCap profile, also writes a long-format dummy REDCap debrief export (one row per
       subject per event/session, same columns; answers synthetic, Likert 1-5).
    2. Legacy template mode -- TEMPLATE_FOLDER holds old raw files to clone (see below).
    3. --profile-shape -- profile real data (see below).

    Shape-mode error scenarios (--with-errors), one participant each:

    \b
    - "aborted_run_restarted": one session has run-001/ (an aborted start, mostly header-only
      logs) and run-002/ four minutes later; the .acq starts at the restart. Seen in real data.
    - "session_folder_underscore": one session folder is "ses_NN" instead of "ses-NN". Seen in
      real data.
    - "multiple_cities_per_session": one session runs a wrong city first, then the planned one.
    - "malformed_subject_id_in_physiology_filename" / "missing_subject_id_in_physiology_filename"
      / "mislabeled_physiology_date": as in legacy mode below, applied to one session's .acq.

    Legacy template mode clones the raw file set in template_folder: one .acq physiology file
    per session (sessions are different days, so physiology can't span them -- see
    longwalk3_dummy_data.py), plus one behaviour.csv and one actor-location log per city per
    session.

    With --profile-shape, it profiles real data instead, so synthetic data can be modelled on
    it without anyone copying patient data. TEMPLATE_FOLDER is then the extracted real data
    folder (unzip it first), laid out as sub-<id>/<session folder>/files; each sub- folder is
    searched recursively for .csv and BIOPAC AcqKnowledge .acq files. The manifest written to
    OUTPUT_FOLDER holds:

    \b
    - folder layout: subjects renumbered sub-001, sub-002, ...; session folder spellings as
      found (e.g. "ses_01" vs "ses-02"); other top-level folders by name and file count only
      (never opened)
    - filename patterns: subject id -> "{id}", timestamps -> "{timestamp}" plus a minute offset
      from the session's earliest file; any other token seen for only one subject (a typo'd
      id, a name) -> "{masked:<length>}"
    - per CSV: header, how often it repeats, data-row count, and per column the *kind* of
      cells (empty/int/float/digit_timestamp/fvector/text) -- never a value
    - per .acq (headers only, no samples or journal): channel names/units, sample rate,
      duration
    - per REDCap export (long format): header, number of records, rows per record and which
      event/repeat instance each row is (REDCap's own labels, e.g. "session_1_arm_1"), and
      per column the kind of cells per event -- never an answer

    Read the manifest yourself before sharing it with anyone or any tool.

    Legacy mode: a well-formed ("clean") participant gets one city's file set per session
    (longwalkV3 has 3 planned sessions -- ses-01=city_labels[0], ses-02=city_labels[1], ...).
    --with-errors also adds one participant per known error scenario -- currently:

    \b
    - "multiple_cities_per_session": still the standard number of sessions, but one randomly
      chosen session gets two runs instead of one: the wrong city first (as if that city was
      started by mistake), then that session's actually-planned city. Both are written as
      run-000, the same as the real Unreal-side export always does -- exercising detection of
      a session with more than one run/city, without it always being the same session.
    - "malformed_subject_id_in_physiology_filename": otherwise a normal, well-formed layout,
      but one randomly chosen session's physiology .acq file has its subject id mistyped
      (e.g. "dummy(7)" instead of "dummy07"), so it resolves to a stray extra subject until
      the correct id is typed in the crosscheck GUI's "Fix Filenames in Raw Folder" dialog.
    - "missing_subject_id_in_physiology_filename": one randomly chosen session's physiology
      .acq file is saved without a subject id ("{date}__LongWalkV3Out.acq"), so no subject id
      can be parsed from it -- shows as "(unparseable)" in the crosscheck GUI's "Fix Filenames
      in Raw Folder" dialog until a corrected id is typed there.
    - "mislabeled_physiology_date": the last session's physiology .acq filename carries a date
      a month after the real session day, so its scans.tsv date no longer matches that
      session's events.

    Each actor-location log's year/month/day/hour/minute/second/millisecond columns are combined
    into a single "date" column (concatenated yyyyMMddHHmmssSSS, e.g. "20260916175501873" -- the
    millisecond part is randomly generated per row, reproducibly under --seed, since the
    template CSVs don't carry a real recorded value yet), and its
    worldLocationX/Y/Z columns into a single "worldLocation" column formatted the way an Unreal
    FVector prints via ToString() (e.g. "X=1.0 Y=2.0 Z=3.0"). Repeated header rows in a template
    are preserved as-is.
    """

    if profile_shape:
        _profile_shape(template_folder, output_folder, redcap_export)
        return

    output_folder.mkdir(parents=True, exist_ok=True)

    if template_folder.is_file() and template_folder.suffix.lower() == ".json":
        dataset_result = generate_dummy_longwalkv3_dataset_from_shape(
            template_folder, output_folder, n_clean, with_errors, cities, seed
        )
    else:
        dataset_result = generate_dummy_longwalkv3_dataset(
            template_folder, output_folder, n_clean, with_errors, cities, seed
        )

    table = Table(title="Generated longwalkV3 dummy data")
    table.add_column("Subject ID")
    table.add_column("Scenario")
    table.add_column("Physiology files")
    table.add_column("Behaviour files")
    table.add_column("Actor-log files")

    for result in dataset_result.participant_results:
        table.add_row(
            result.subject_id,
            result.scenario,
            str(len(result.acq_paths)),
            str(len(result.behaviour_paths)),
            str(len(result.actor_log_paths)),
        )

    console = Console()
    console.print(table)

    if dataset_result.redcap_debrief_path is not None:
        console.print(
            f"[green]Dummy REDCap debrief file written for "
            f"{len(dataset_result.participant_results)} subject(s):[/green] "
            f"{dataset_result.redcap_debrief_path}"
        )
    else:
        console.print(
            "[yellow]No REDCap debrief export template found -- skipped dummy debrief "
            "file.[/yellow]"
        )


def _profile_shape(data_folder: Path, output_folder: Path, redcap_export: Path | None) -> None:
    manifest_path = write_longwalkv3_shape_manifest(data_folder, output_folder, redcap_export)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    table = Table(title="longwalkV3 data shape (structure only)")
    table.add_column("Subject")
    table.add_column("Session folder")
    table.add_column(".acq files")
    table.add_column(".csv files")
    table.add_column("Unreadable")
    for subject in manifest["subjects"]:
        for session in subject["sessions"]:
            files = session["files"]
            table.add_row(
                subject["subject"],
                session["folder"],
                str(sum(f["kind"] == "acq" for f in files)),
                str(sum(f["kind"] != "acq" for f in files)),
                str(sum("error" in f for f in files)),
            )

    console = Console()
    console.print(table)
    for folder in manifest["other_top_level_folders"]:
        console.print(
            f"[yellow]Not profiled (not a sub- folder):[/yellow] {folder['name']} "
            f"({folder['n_files']} files)"
        )
    for redcap in manifest.get("redcap_exports", []):
        if "error" in redcap:
            console.print(f"[red]REDCap export could not be profiled:[/red] {redcap['error']}")
            continue
        rows_per_record = sorted({len(p["row_types"]) for p in redcap["record_row_patterns"]})
        console.print(
            f"[green]REDCap export profiled:[/green] {redcap['n_records']} records, "
            f"{len(redcap['header'])} columns, {len(redcap['row_types'])} row types, "
            f"rows per record: {rows_per_record}"
        )
    d6 = manifest.get("datetime_summary")
    if d6:
        console.print("[bold]datetime cells (D6):[/bold]")
        console.print(f"  digit lengths: {d6['digit_lengths']}")
        in_order, pairs = d6["full_length_in_order"]
        console.print(f"  17-digit cells in time order: {in_order} of {pairs} consecutive pairs")
        for hypothesis, counts in d6["hypotheses"].items():
            console.print(f"  {hypothesis}: {counts}")
        console.print(
            f"  decisive (only this reading keeps time order): {d6['decisive'] or 'none'}"
        )
    console.print(f"[green]Shape manifest written:[/green] {manifest_path}")
    console.print(
        "[bold yellow]Review it before sharing -- it should hold no values, ids, dates or "
        "names.[/bold yellow]"
    )


if __name__ == "__main__":
    vrlab_logging.init(__file__)
    main()
