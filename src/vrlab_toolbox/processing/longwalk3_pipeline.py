import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandera.pandas as pa

from vrlab_toolbox.processing import pipeline
from vrlab_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from vrlab_toolbox.processing.eda import ProcessEdaPhysiologyDataStrategyStep
from vrlab_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from vrlab_toolbox.processing.longwalk3_behaviour import (
    ImportLongWalkV3BehaviourDataStrategyStep,
    ProcessLongWalkV3BehaviourDataStrategyStep,
)
from vrlab_toolbox.processing.longwalk3_debrief_behaviour import (
    ImportLongWalkV3DebriefDataProcessStrategyStep,
    ProcessLongWalkV3DebriefBehaviourDataStrategyStep,
)
from vrlab_toolbox.processing.longwalk3_trial_intervals import (
    LongWalkV3GetTrialIntervalStrategyStep,
)
from vrlab_toolbox.processing.output_data import (
    PipelineOutputData,
    build_base_pipeline_output_schema,
)

logger = logging.getLogger(__name__)


@dataclass
class FindLongWalkV3ParticipantFilesStrategyStep:
    physiology_data_type = PhysiologyFileFormat.BIOPAC
    behaviour_data_types = [
        ProcessLongWalkV3BehaviourDataStrategyStep.input_data_type,
        ProcessLongWalkV3DebriefBehaviourDataStrategyStep.input_data_type,
    ]
    session_nr: int = 1

    def run(
        self,
        participant_id_in: str,
        data_folder_in: Path,
        output_folder_in: Path | None = None,
    ) -> ParticipantConfig:

        return ParticipantConfig.from_bids_data(
            id_in=participant_id_in,
            physiology_data_type_in=self.physiology_data_type,
            data_folder_in=data_folder_in,
            session_nr=self.session_nr,
            behaviour_data_types_in=self.behaviour_data_types,
            output_folder_in=output_folder_in,
        )


# One wide row per subject (D3, docs/longwalk3_plan.md): every session's columns carry a
# "ses01_"-style prefix -- no hyphen, since SPSS variable names can't contain one.
SESSION_COLUMN_PREFIX = "ses{session_nr:02d}_"
_SESSION_FOLDER_PATTERN = re.compile(r"^ses-(?P<session_nr>\d+)$")
PHYSIOLOGY_GLOB = "*_physio*.acq"


def session_column_prefix(session_nr: int) -> str:
    return SESSION_COLUMN_PREFIX.format(session_nr=session_nr)


def build_longwalkv3_participant_output_schema() -> pa.DataFrameSchema:
    """Subject_ID + Processing_Status (base schema), plus per session its own processing
    status and SCR-per-minute per actor-instance interval. D1 (behaviour metrics) is still
    open, so no behaviour columns yet."""
    return build_base_pipeline_output_schema(
        {
            r"^ses\d{2}_Processing_Status$": pa.Column(
                pd.StringDtype(), nullable=True, coerce=True, required=False, regex=True
            ),
            r"^ses\d{2}_.+_SCR_per_min.*$": pa.Column(
                float, nullable=True, coerce=True, required=False, regex=True
            ),
        }
    )


def find_longwalkv3_sessions(participant_id: str, data_folder: Path) -> list[int]:
    """Session numbers that have a physiology recording for this participant -- the sessions
    the pipeline can process."""
    subject_folder = data_folder / f"sub-{participant_id}"
    sessions = []
    for folder in sorted(subject_folder.glob("ses-*")):
        match = _SESSION_FOLDER_PATTERN.match(folder.name)
        if match and any(folder.rglob(PHYSIOLOGY_GLOB)):
            sessions.append(int(match.group("session_nr")))
    return sessions


@dataclass
class LongWalkV3PipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_longwalkv3_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(
    participant_id_in: str,
    data_folder_in: Path,
    session_nr_in: int,
    output_folder_in: Path | None = None,
) -> LongWalkV3PipelineOutputData:
    """Run the longwalkV3 behaviour/physiology pipeline for a single participant.

    `data_folder_in` must be a BIDS-formatted folder. This assumes the data has
    already been through the crosscheck tool (`gui/longwalkV3_bids_crosscheck_gui.py`)
    so duplicate runs and id/date corrections are resolved before processing.
    """

    import_behav_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[
            ImportLongWalkV3BehaviourDataStrategyStep(),
            ImportLongWalkV3DebriefDataProcessStrategyStep(),
        ]
    )
    process_behav_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps=[
            ProcessLongWalkV3BehaviourDataStrategyStep(),
            ProcessLongWalkV3DebriefBehaviourDataStrategyStep(),
        ]
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[
            BiopacPhysiologyDataImportStartegy(
                input_data_file_format=FindLongWalkV3ParticipantFilesStrategyStep.physiology_data_type
            )
        ]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessEdaPhysiologyDataStrategyStep()]
    )

    longwalkV3_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=FindLongWalkV3ParticipantFilesStrategyStep(
            session_nr=session_nr_in
        ),
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_behaviour_data_import_steps=import_behav_steps,
        get_intervals_strategy=LongWalkV3GetTrialIntervalStrategyStep(),
        sequential_behaviour_processing_steps=process_behav_steps,
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_config, participant_pipeline_data_out = longwalkV3_pipeline.run(
        participant_id_in,
        data_folder_in,
        output_folder_in,
    )
    # TODO: This needs a classmethod to avoid future errors when implementing pipeline
    longwalkV3_pipeline_output_data = LongWalkV3PipelineOutputData(participant_config.subject_id)
    longwalkV3_pipeline_output_data.subject_df_out = participant_pipeline_data_out.subject_df_out
    longwalkV3_pipeline_output_data.status = participant_pipeline_data_out.status
    longwalkV3_pipeline_output_data.figure_data_out = participant_pipeline_data_out.figure_data_out

    return longwalkV3_pipeline_output_data


def run_pipeline_all_sessions(
    participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
) -> LongWalkV3PipelineOutputData:
    """Every session with a physiology recording (find_longwalkv3_sessions), each through
    `run_pipeline`, joined into one wide row: each session's columns prefixed "sesNN_", its
    own status in "sesNN_Processing_Status", and the overall Processing_Status the worst of
    them. A session that fails is logged and marked "error" without stopping the others."""
    output = LongWalkV3PipelineOutputData(participant_id_in)
    session_parts: list[pd.DataFrame] = []
    figures = {}

    sessions = find_longwalkv3_sessions(participant_id_in, data_folder_in)
    if not sessions:
        raise FileNotFoundError(f"No session with a physiology recording for {participant_id_in}")

    for session_nr in sessions:
        prefix = session_column_prefix(session_nr)
        try:
            session_output = run_pipeline(
                participant_id_in, data_folder_in, session_nr, output_folder_in
            )
        except (FileNotFoundError, ValueError, KeyError, TypeError) as error:
            logger.warning("Session %d of %s failed: %s", session_nr, participant_id_in, error)
            session_parts.append(pd.DataFrame([{f"{prefix}Processing_Status": f"error: {error}"}]))
            continue

        output.status = output.status.merge(session_output.status)
        session_df = session_output.subject_df_out.drop(
            columns=["Subject_ID", "Processing_Status"], errors="ignore"
        ).add_prefix(prefix)
        session_df.insert(0, f"{prefix}Processing_Status", session_output.status.get_as_text())
        session_parts.append(session_df.reset_index(drop=True))
        figures.update(
            {f"{prefix}{title}": fig for title, fig in session_output.figure_data_out.items()}
        )

    wide = pd.concat([pd.DataFrame([{"Subject_ID": participant_id_in}]), *session_parts], axis=1)
    wide["Processing_Status"] = output.status.get_as_text()
    output.subject_df_out = wide
    output.subject_df_out = output.validate_participant_output()
    output.figure_data_out = figures
    return output
