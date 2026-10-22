from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pandera.pandas as pa
import pyxdf

from vrlab_toolbox.processing import pipeline
from vrlab_toolbox.processing.behaviour import RawBehaviourData
from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.graphomotor_xdf import (
    XdfStream,
    find_eda_stream_and_column,
    find_largest_stream,
    is_eeg_stream,
    is_pen_stream,
    stream_to_dataframe,
)
from vrlab_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from vrlab_toolbox.processing.output_data import (
    PipelineOutputData,
    build_base_pipeline_output_schema,
)
from vrlab_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from vrlab_toolbox.processing.spiral import (
    MOTOR_CHANNELS,
    OCCIPITAL_CHANNELS,
    SpiralDrawingIntervals,
    get_spiral_drawing_intervals,
    plot_spiral_qc,
    run_spiral_eda_processing,
    run_spiral_eeg_processing,
)
from vrlab_toolbox.processing.trial_intervals import TrialIntervals

logger = logging.getLogger(__name__)


class SpiralEEGProcessing:
    pass


class SpiralEDAProcessing:
    pass


class RawSpiralBehaviourData(RawBehaviourData):
    pass


@dataclass(frozen=True)
class RawSpiralPhysiologyData(RawBioData):
    def __post_init__(self) -> None:
        validated_data: dict[str, pd.DataFrame] = {}

        for label, dataframe in self.raw_data.items():
            if "time_stamps" not in dataframe.columns:
                raise ValueError(f"Spiral {label} data has no time_stamps column.")

            validated = dataframe.copy()
            validated["time_stamps"] = pd.to_numeric(
                validated["time_stamps"],
                errors="coerce",
            )

            if validated["time_stamps"].isna().any():
                raise ValueError(f"Spiral {label} data contains invalid timestamps.")

            for column in validated.columns:
                if column == "time_stamps":
                    continue
                validated[column] = pd.to_numeric(validated[column], errors="coerce")

            validated_data[label] = validated

        object.__setattr__(self, "raw_data", validated_data)


@dataclass
class SpiralTrialIntervals(TrialIntervals):
    drawing_intervals: SpiralDrawingIntervals | None = None


@lru_cache(maxsize=1)
def _load_spiral_xdf(filename: str) -> tuple[XdfStream, ...]:
    streams, _ = pyxdf.load_xdf(filename)
    return tuple(streams)


def _spiral_output_columns() -> dict[str, pa.Column]:
    columns: dict[str, pa.Column] = {
        "XDF_File": pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=False),
        "Spiral_Attempts_Detected": pa.Column(int, nullable=False, coerce=True, required=False),
        "Spiral_Selected_Count": pa.Column(int, nullable=False, coerce=True, required=False),
        "Switch_Time_sec": pa.Column(float, nullable=True, coerce=True, required=False),
        "Dominant_SCR_per_min": pa.Column(float, nullable=True, coerce=True, required=False),
        "NonDominant_SCR_per_min": pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
        ),
    }

    for channel in (*MOTOR_CHANNELS, *OCCIPITAL_CHANNELS):
        columns[f"{channel}_dominant_alpha"] = pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
        )
        columns[f"{channel}_nondominant_alpha"] = pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
        )

    for channel in MOTOR_CHANNELS:
        columns[f"{channel}_dominant_beta"] = pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
        )
        columns[f"{channel}_nondominant_beta"] = pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
        )

    return columns


def build_spiral_participant_output_schema() -> pa.DataFrameSchema:
    return build_base_pipeline_output_schema(_spiral_output_columns())


class FindSpiralParticipantFilesStrategyStep:
    physiology_data_type = PhysiologyFileFormat.LSL
    behaviour_data_types: list[type] = []

    def run(
        self,
        participant_id_in: str,
        data_folder_in: Path,
        output_folder_in: Path | None = None,
    ) -> ParticipantConfig:
        subject_folder = data_folder_in / f"sub-{participant_id_in}"

        if not subject_folder.is_dir():
            raise FileNotFoundError(
                f"No BIDS subject folder found for participant {participant_id_in}."
            )

        xdf_files = sorted(subject_folder.rglob("*.xdf"))

        if not xdf_files:
            raise FileNotFoundError(
                f"No Spiral XDF file found for participant {participant_id_in}."
            )
        if len(xdf_files) > 1:
            raise ValueError(
                f"Multiple Spiral XDF files found for participant {participant_id_in}. "
                "Run the Spiral BIDS crosscheck first."
            )

        if output_folder_in is None:
            output_folder_in = data_folder_in.parent / "output"

        output_folder_in.mkdir(parents=True, exist_ok=True)
        log_folder = output_folder_in / "logs"
        log_folder.mkdir(parents=True, exist_ok=True)

        return ParticipantConfig(
            subject_id=participant_id_in,
            physiology_fn=str(xdf_files[0]),
            physiology_data_type=PhysiologyFileFormat.LSL,
            data_folder=data_folder_in,
            behav_folder=data_folder_in,
            _behaviour_file_names={},
            log_folder=log_folder,
            output_folder=output_folder_in,
            verbose=False,
            show_plots=False,
        )


class ImportSpiralBehaviourDataStrategyStep:
    behaviour_output_type = RawSpiralBehaviourData

    def run(self, config_in: ParticipantConfig) -> RawSpiralBehaviourData:
        streams = list(_load_spiral_xdf(config_in.physiology_fn))
        pen_stream = find_largest_stream(streams, is_pen_stream)

        if pen_stream is None:
            raise ValueError("No Spiral Pen/iPad stream found.")

        pen_df = stream_to_dataframe(pen_stream)
        coordinate_columns = [column for column in pen_df.columns if column != "time_stamps"]

        if len(coordinate_columns) < 2:
            raise ValueError("Spiral Pen/iPad stream does not contain x/y coordinates.")

        pen_df = pen_df[["time_stamps", coordinate_columns[0], coordinate_columns[1]]].rename(
            columns={
                coordinate_columns[0]: "x",
                coordinate_columns[1]: "y",
            }
        )
        pen_df["time_stamps"] = pd.to_numeric(pen_df["time_stamps"], errors="coerce")
        pen_df["x"] = pd.to_numeric(pen_df["x"], errors="coerce")
        pen_df["y"] = pd.to_numeric(pen_df["y"], errors="coerce")

        return RawSpiralBehaviourData(config_in, pen_df)


class ImportSpiralPhysiologyDataStrategyStep:
    input_data_file_format = PhysiologyFileFormat.LSL
    output_data_type = RawSpiralPhysiologyData

    def run(self, config_in: ParticipantConfig) -> RawSpiralPhysiologyData:
        streams = list(_load_spiral_xdf(config_in.physiology_fn))
        raw_data: dict[str, pd.DataFrame] = {}

        eeg_stream = find_largest_stream(streams, is_eeg_stream)
        if eeg_stream is not None:
            raw_data["EEG"] = stream_to_dataframe(eeg_stream)

        eda_stream, eda_column = find_eda_stream_and_column(streams)
        if eda_stream is not None and eda_column is not None:
            eda_df = stream_to_dataframe(eda_stream)
            if eda_column != "EDA":
                eda_df = eda_df.rename(columns={eda_column: "EDA"})
            raw_data["EDA"] = eda_df[["time_stamps", "EDA"]]

        return RawSpiralPhysiologyData(raw_data=raw_data)


class GetSpiralTrialIntervalStrategyStep:
    input_bio_data_type = RawSpiralPhysiologyData
    input_behaviour_data_type = RawSpiralBehaviourData
    fallback_strategy = None

    def run(
        self,
        raw_biodata_in: RawSpiralPhysiologyData,
        raw_behaviour_data_in: RawSpiralBehaviourData,
    ) -> tuple[SpiralTrialIntervals, None, PipelineStatus]:
        del raw_biodata_in

        pen_df = raw_behaviour_data_in.raw_behav_df
        pen_stream: XdfStream = {
            "time_stamps": pen_df["time_stamps"].to_numpy(dtype=float),
            "time_series": pen_df[["x", "y"]].to_numpy(dtype=float),
        }

        drawing_intervals = get_spiral_drawing_intervals(pen_stream)
        intervals: dict[str, tuple[float, float]] = {}

        for index, interval in enumerate(drawing_intervals.dominant_intervals, start=1):
            intervals[f"Dominant_Active_{index:02d}"] = interval

        for index, interval in enumerate(drawing_intervals.nondominant_intervals, start=1):
            intervals[f"NonDominant_Active_{index:02d}"] = interval

        spiral_intervals = SpiralTrialIntervals(
            intervals=intervals,
            physiology_file_format=PhysiologyFileFormat.LSL,
            drawing_intervals=drawing_intervals,
        )

        status = PipelineStatus()
        status.set(TrialIntervals, ProcessingStatus.OK)

        return spiral_intervals, None, status


class ProcessSpiralBehaviourDataWithIntervalsStrategyStep:
    input_data_type = RawSpiralBehaviourData

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: RawSpiralBehaviourData,
        trial_intervals_in: TrialIntervals,
    ) -> PipelineOutputData:
        del raw_behaviour_data_in

        if not isinstance(trial_intervals_in, SpiralTrialIntervals):
            raise ValueError("Spiral trial intervals were not available.")
        if trial_intervals_in.drawing_intervals is None:
            raise ValueError("Spiral drawing intervals were not available.")

        drawing = trial_intervals_in.drawing_intervals
        task_start = float(drawing.selected_attempts.iloc[0]["Start_Time"])

        summary = pd.DataFrame(
            [
                {
                    "XDF_File": Path(config_in.physiology_fn).name,
                    "Spiral_Attempts_Detected": len(drawing.attempt_features),
                    "Spiral_Selected_Count": len(drawing.selected_attempts),
                    "Switch_Time_sec": drawing.switch_time - task_start,
                }
            ]
        )

        output = PipelineOutputData(config_in.subject_id)
        output.append_dataframe(
            summary,
            {
                key: value
                for key, value in _spiral_output_columns().items()
                if key
                in {
                    "XDF_File",
                    "Spiral_Attempts_Detected",
                    "Spiral_Selected_Count",
                    "Switch_Time_sec",
                }
            },
        )
        return output


class ProcessSpiralPhysiologyDataStrategyStep:
    input_data_type = RawSpiralPhysiologyData
    fallback_strategy = None

    def run(
        self,
        config_in: ParticipantConfig,
        biodata_in: RawSpiralPhysiologyData,
        trial_interval_data: TrialIntervals,
    ) -> PipelineOutputData:
        if not isinstance(trial_interval_data, SpiralTrialIntervals):
            raise ValueError("Spiral trial intervals were not available.")
        if trial_interval_data.drawing_intervals is None:
            raise ValueError("Spiral drawing intervals were not available.")

        drawing = trial_interval_data.drawing_intervals
        output = PipelineOutputData(config_in.subject_id)
        summary_parts: list[pd.DataFrame] = []

        eeg_result = None
        if "EEG" in biodata_in.raw_data:
            try:
                eeg_result = run_spiral_eeg_processing(
                    biodata_in.raw_data["EEG"],
                    drawing,
                )
                output.status.set(SpiralEEGProcessing, ProcessingStatus.OK)

                summary_long = eeg_result["summary_data"]
                summary_wide: dict[str, float | None] = {}

                for _, row in summary_long.iterrows():
                    channel = str(row["channel"])
                    summary_wide[f"{channel}_dominant_alpha"] = row["dominant_alpha"]
                    summary_wide[f"{channel}_nondominant_alpha"] = row["nondominant_alpha"]

                    if channel in MOTOR_CHANNELS:
                        summary_wide[f"{channel}_dominant_beta"] = row["dominant_beta"]
                        summary_wide[f"{channel}_nondominant_beta"] = row["nondominant_beta"]

                if summary_wide:
                    summary_parts.append(pd.DataFrame([summary_wide]))
            except ValueError as error:
                logger.warning(
                    "Skipping Spiral EEG processing for %s: %s",
                    config_in.subject_id,
                    error,
                )
                output.status.set(SpiralEEGProcessing, ProcessingStatus.ERROR)
        else:
            logger.warning("No EEG data found for %s.", config_in.subject_id)
            output.status.set(SpiralEEGProcessing, ProcessingStatus.ERROR)

        eda_result = None
        if "EDA" in biodata_in.raw_data:
            try:
                eda_result = run_spiral_eda_processing(
                    biodata_in.raw_data["EDA"],
                    drawing,
                )
                output.status.set(SpiralEDAProcessing, ProcessingStatus.OK)
                summary_parts.append(eda_result["summary_data"])
            except ValueError as error:
                logger.warning(
                    "Skipping Spiral EDA processing for %s: %s",
                    config_in.subject_id,
                    error,
                )
                output.status.set(SpiralEDAProcessing, ProcessingStatus.ERROR)
        else:
            logger.warning("No EDA data found for %s.", config_in.subject_id)
            output.status.set(SpiralEDAProcessing, ProcessingStatus.ERROR)

        if summary_parts:
            summary = pd.concat(
                [part.reset_index(drop=True) for part in summary_parts],
                axis=1,
            )
            output.append_dataframe(summary, _spiral_output_columns())

        output.figure_data_out["Spiral_QC"] = plot_spiral_qc(
            subject_id=config_in.subject_id,
            drawing_intervals=drawing,
            eeg_result=eeg_result,
            eda_result=eda_result,
        )

        return output


@dataclass
class SpiralPipelineOutputData(PipelineOutputData):
    def validate_participant_output(self) -> pd.DataFrame:
        return build_spiral_participant_output_schema().validate(self.subject_df_out)


def run_pipeline(
    participant_id_in: str,
    data_folder_in: Path,
    output_folder_in: Path | None = None,
) -> SpiralPipelineOutputData:
    import_behaviour_steps = pipeline.SequentialBehaviourImportSteps(
        steps=[ImportSpiralBehaviourDataStrategyStep()]
    )
    process_behaviour_steps = pipeline.SequentialBehaviourProcessingSteps(
        steps=[],
        steps_with_trial_intervals=[ProcessSpiralBehaviourDataWithIntervalsStrategyStep()],
    )
    import_physiology_steps = pipeline.SequentialPhysiolgyImportSteps(
        steps=[ImportSpiralPhysiologyDataStrategyStep()]
    )
    process_physiology_steps = pipeline.SequentialPhysiologyProcessingSteps(
        steps=[ProcessSpiralPhysiologyDataStrategyStep()]
    )

    spiral_pipeline = pipeline.PipelineTemplate(
        find_participant_strategy_step=FindSpiralParticipantFilesStrategyStep(),
        sequential_physiology_import_steps=import_physiology_steps,
        sequential_behaviour_data_import_steps=import_behaviour_steps,
        sequential_behaviour_processing_steps=process_behaviour_steps,
        get_intervals_strategy=GetSpiralTrialIntervalStrategyStep(),
        sequential_physiology_processing_steps=process_physiology_steps,
    )

    participant_config, participant_output = spiral_pipeline.run(
        participant_id_in=participant_id_in,
        data_folder_in=data_folder_in,
        output_folder_in=output_folder_in,
    )

    spiral_output = SpiralPipelineOutputData(participant_config.subject_id)
    spiral_output.subject_df_out = participant_output.subject_df_out
    spiral_output.status = participant_output.status
    spiral_output.figure_data_out = participant_output.figure_data_out

    return spiral_output
