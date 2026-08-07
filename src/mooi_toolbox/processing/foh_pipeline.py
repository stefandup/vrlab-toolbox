import logging
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
from matplotlib.figure import Figure
from typing_extensions import deprecated

from mooi_toolbox import config as cfg
from mooi_toolbox.cli.check_mobi_xdf import check_mobi_xdf as get_and_check_xdf
from mooi_toolbox.processing import lsl as xdf
from mooi_toolbox.processing import pipeline
from mooi_toolbox.processing.eda import ProcessEdaPhysiologyDataStrategyStep
from mooi_toolbox.processing.foh_behaviour import (
    ImportFohBehaviourDataStrategyStep,
    ProcessFohBehaviouralDataStrateyStep,
)
from mooi_toolbox.processing.foh_target_behaviour import (
    ImportFohTargetBehaviourDataStrategyStep,
    ProcessFohTargetDataWithIntervalsStrategyStep,
)
from mooi_toolbox.processing.foh_trial_intervals import FohGetTrialIntervalStrategyStep
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.lsl import FohLslPhysiologyDataImportStrategy
from mooi_toolbox.processing.output_data import PipelineOutputData

from . import ecg, eda
from . import foh_target_behaviour as tp
from . import trial_intervals as trial_intervals

logger = logging.getLogger(__name__)


def has_missing_requirements(missing: set, required: list[str]) -> bool:
    return any(stream in missing for stream in required)


class FindFohParticipantFilesStrategyStep:
    physiology_data_type = FohLslPhysiologyDataImportStrategy.input_data_file_format
    behaviour_data_types = [
        ProcessFohBehaviouralDataStrateyStep.input_data_type,
        ProcessFohTargetDataWithIntervalsStrategyStep.input_data_type,
    ]

    def run(
        self, participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
    ) -> ParticipantConfig:

        return ParticipantConfig.from_lsl_data(
            id_in=participant_id_in,
            physiology_data_type_in=self.physiology_data_type,
            data_folder_in=data_folder_in,
            output_folder_in=output_folder_in,
        )


# TODO: Fill out pipeline output schema for FOH
def build_foh_participant_output_schema() -> pa.DataFrameSchema:
    return pa.DataFrameSchema()


@dataclass
class FohPipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_foh_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(
    participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
) -> FohPipelineOutputData:

    import_behav_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[ImportFohBehaviourDataStrategyStep(), ImportFohTargetBehaviourDataStrategyStep()]
    )
    process_behav_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps=[], steps_with_trial_intervals=[ProcessFohTargetDataWithIntervalsStrategyStep()]
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[FohLslPhysiologyDataImportStrategy()]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessEdaPhysiologyDataStrategyStep()]
    )

    foh_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=FindFohParticipantFilesStrategyStep(),
        get_intervals_strategy=FohGetTrialIntervalStrategyStep(),
        sequential_behaviour_data_import_steps=import_behav_steps,
        sequential_behaviour_processing_steps=process_behav_steps,
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_config, participant_pipeline_data_output = foh_pipeline.run(
        participant_id_in=participant_id_in,
        data_folder_in=data_folder_in,
        output_folder_in=output_folder_in,
    )

    foh_pipeline_data_out = FohPipelineOutputData(participant_config.subject_id)
    foh_pipeline_data_out.subject_df_out = participant_pipeline_data_output.subject_df_out
    foh_pipeline_data_out.status = participant_pipeline_data_output.status
    foh_pipeline_data_out.figure_data_out = participant_pipeline_data_output.figure_data_out

    return foh_pipeline_data_out


@deprecated("Use new version of pipeline")
def run_lsl_pipeline(
    xdf_fn: str, verbose: bool, show_plots: bool
) -> tuple[pd.DataFrame, Figure | None]:
    """Run FOH pipeline for LSL EDA, ECG and Behavioural (i.e. Target) data. Tries to be robust wrt missing data."""
    if not xdf_fn:
        streams = get_and_check_xdf(cfg.get_default_xdf(), verbose=verbose)
    else:
        streams = get_and_check_xdf(xdf_fn, verbose=verbose)

    participant_data_out = []
    vr_intervals = None
    fig = None

    streams_to_get = ["OpenSignals", "VR_markers", "VR_trial_events", "FOH_target"]

    FOH_stream_dfs: dict[str, pd.DataFrame] = xdf.gather_xdf_data_streams(streams, streams_to_get)

    missing_streams = set(streams_to_get) - set(FOH_stream_dfs)
    if missing_streams:
        logger.warning(f"Missing streams: {missing_streams}")

    else:
        logger.info("No missing streams")

    # Create intervals

    if has_missing_requirements(missing_streams, ["VR_markers", "VR_trial_events"]):
        logger.warning("No trial info found in xdf. Cannot create intervals")
    else:
        try:
            vr_intervals = trial_intervals.create_lsl_trial_intervals(
                FOH_stream_dfs["VR_markers"], FOH_stream_dfs["VR_trial_events"]
            )
        except KeyError as e:
            logger.warning("%s", e)

    # Biosignals QC

    if has_missing_requirements(missing_streams, ["OpenSignals"]):
        logger.warning("Missing physiology data. Cannot run QC.")
    else:
        eda_raw_timestamped: pd.DataFrame = FOH_stream_dfs["OpenSignals"]
        eda_raw_timestamped = eda_raw_timestamped.rename(
            columns={cfg.get_opensignals_eda_data_label(): "EDA"}
        )
        fig = eda.run_eda_qc(eda_raw_timestamped)

    if vr_intervals is None:
        logger.warning(
            "No intervals present. Cannot proceed with interval based nor behaviour analysis"
        )
        return (pd.DataFrame(), None)

    # Biosignals processing
    if has_missing_requirements(missing_streams, ["OpenSignals", "VR_markers", "VR_trial_events"]):
        logger.warning(
            "Skipping ECG and EDA because required streams are missing: %s", missing_streams
        )
    else:
        try:
            eda_df_out = eda.run_eda_intervals(eda_raw_timestamped, vr_intervals)
            fig = eda.run_eda_qc(
                eda_raw_timestamped, eda_data_out=eda_df_out, vr_intervals=vr_intervals
            )
            participant_data_out.append(eda_df_out)

        except eda.EDAProcessingError as e:
            logger.exception("EDA failed to process")
            logger.warning("%s", e)

        try:
            ecg_df_out = ecg.run_ecg_pipeline(FOH_stream_dfs["OpenSignals"]["ECG1"], vr_intervals)
            participant_data_out.append(ecg_df_out)
        except ecg.ECGProcessingError as e:
            logger.exception("ECG failed to process")
            logger.warning("%s", e)

    # Behaviour processing
    if has_missing_requirements(missing_streams, ["FOH_target", "VR_markers", "VR_trial_events"]):
        logger.warning("Skipping target behaviour as there are none recorded")
    else:
        try:
            target_data_out, _ = tp.run_processing(FOH_stream_dfs["FOH_target"], vr_intervals)
            participant_data_out.append(target_data_out)
        except tp.TPProcessingError as e:
            logger.warning("Skipping target behaviour as there was a processing error")
            logger.warning("%s", e)
    if len(participant_data_out) != 0:
        # Concatenate row wise
        return (pd.concat(participant_data_out, axis=1), fig)
    else:
        return (pd.DataFrame(), None)
