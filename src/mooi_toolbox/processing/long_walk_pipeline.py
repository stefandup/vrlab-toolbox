import logging
from dataclasses import dataclass

import pandas as pd
import pandera.pandas as pa
from matplotlib.figure import Figure
from pandas.core.api import DataFrame as DataFrame

from mooi_toolbox.processing import eda
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.biopac import BiopacPhysiologyDataImportStartegy
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.output_data import (
    PipelineOutputData,
    build_base_pipeline_output_schema,
)
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import get_raw_biopac_trigger_intervals

logger = logging.getLogger(__name__)

EXPECTED_INTERVAL_NR = 12


@dataclass
class LongWalkPipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> DataFrame:
        return build_long_walk_participant_output_schema().validate(self.subject_df_out)


def _optional_float_column() -> pa.Column:
    return pa.Column(float, nullable=True, coerce=True, required=False)


def build_long_walk_participant_output_schema():

    physiology_columns = {
        r"^.+_SCR_per_min$": pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
            regex=True,
        )
    }

    return build_base_pipeline_output_schema({**physiology_columns})


def run_pipeline(data_in: ParticipantConfig) -> LongWalkPipelineOutputData:
    # TODO: Make less of a messy pipeline! Fix Crane as well to be less messy!
    fig: Figure | None = None
    # Assume OK unless and exception is raied
    status = PipelineStatus()

    # Input raw eda

    try:
        raw_timestamped_data: RawBioData = BiopacPhysiologyDataImportStartegy().import_data(data_in)
        eda_raw_timestamped = raw_timestamped_data["EDA"]
        status.data_in = ProcessingStatus.OK
    except (ValueError, FileNotFoundError) as e:
        logger.warning("Error loading biopac eda data. %s", e)
        status.data_in = ProcessingStatus.ERROR
        return LongWalkPipelineOutputData.error(data_in.subject_id, status)

    participant_data_out = []

    # Do QC

    vr_intervals, status_out = get_raw_biopac_trigger_intervals(raw_timestamped_data["Trigger"])
    if len(vr_intervals) != EXPECTED_INTERVAL_NR:
        logger.warning(
            "Interval count is %d and not %d for subject %s.",
            len(vr_intervals),
            EXPECTED_INTERVAL_NR,
            data_in.subject_id,
        )
        status.intervals = ProcessingStatus.ERROR
    else:
        status.intervals = status_out

    try:
        scr_df_out = eda.run_eda_intervals(eda_raw_timestamped, vr_intervals)
        participant_data_out.append(scr_df_out)
        fig = eda.run_eda_qc(eda_raw_timestamped, scr_df_out, vr_intervals)
        status.physiology = ProcessingStatus.OK

    except ValueError as e:
        logger.warning("Skipping physiology analysis on %s. %s", data_in.subject_id, e)
        status.physiology = ProcessingStatus.ERROR

    # Append the final status
    participant_data_out.append(pd.DataFrame({"Processing_Status": [status.get_as_text()]}))

    df_out = pd.concat(participant_data_out, axis=1)

    if "Subject_ID" not in df_out.columns:
        df_out.insert(0, "Subject_ID", data_in.subject_id)

    return LongWalkPipelineOutputData(subject_df_out=df_out, figure_data_out=fig, status=status)
