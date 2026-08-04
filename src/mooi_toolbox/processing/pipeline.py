import logging
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar, cast

from matplotlib.figure import Figure

from mooi_toolbox.mobi_logging import LOG_DATE_FORMAT, LOG_FORMAT
from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from mooi_toolbox.processing.output_data import PipelineOutputData

# from mooi_toolbox.processing.vr_intervals import
# TODO: This could potentially form part of pipeline as a class override?
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals


@contextmanager
def participant_log_handler(participant_config_file_in: ParticipantConfig):
    handler = logging.FileHandler(
        participant_config_file_in.log_folder / f"{participant_config_file_in.subject_id}.log"
    )

    handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT, style="{"))

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    try:
        yield
    finally:
        root_logger.removeHandler(handler)
        handler.close()


logger = logging.getLogger(__name__)

BehaviourDataType = TypeVar("BehaviourDataType", bound="RawBehaviourData")
BehaviourDataOutType = TypeVar("BehaviourDataOutType", bound="RawBehaviourData", covariant=True)
PhysiologyDataType = TypeVar("PhysiologyDataType", bound="RawBioData")
PhysiologyInputDataType = TypeVar("PhysiologyInputDataType", bound="RawBioData", contravariant=True)
PipelineOutputDataType = TypeVar("PipelineOutputDataType", bound="PipelineOutputData")


@dataclass
class RawBehaviourDataStore:
    items: dict[type[RawBehaviourData], RawBehaviourData] = field(default_factory=dict)

    def add(self, item: RawBehaviourData) -> None:
        self.items[type(item)] = item

    def get(self, item_type: type[BehaviourDataType]) -> BehaviourDataType:
        try:
            return cast(BehaviourDataType, self.items[item_type])
        except KeyError as e:
            raise ValueError(f"Store has no behaviour of type {item_type.__name__}") from e

    def has(self, item_type: type[RawBehaviourData]) -> bool:
        return item_type in self.items


@dataclass
class RawPhysiologyDataStore:
    items: dict[type[RawBioData], RawBioData] = field(default_factory=dict)

    def add(self, item: RawBioData) -> None:
        self.items[type(item)] = item

    def get(self, item_type: type[PhysiologyDataType]) -> PhysiologyDataType:
        try:
            return cast(PhysiologyDataType, self.items[item_type])
        except KeyError as e:
            raise ValueError(f"Store has no physiology data of type {item_type.__name__}") from e

    def has(self, item_type: type[RawBioData]) -> bool:
        return item_type in self.items


# Strategies
# strategy base class


class FindParticipantFilesStrategyStep(Protocol):
    physiology_data_type: PhysiologyFileFormat
    behaviour_data_types: list[type]

    def run(
        self, participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
    ) -> ParticipantConfig: ...


class ImportBioDataStrategyStep(Protocol):
    input_data_file_format: PhysiologyFileFormat
    output_data_type: type[RawBioData] = RawBioData

    def run(self, config_in: ParticipantConfig) -> RawBioData: ...


class ImportBehaviourDataStrategyStep(Protocol[BehaviourDataType]):
    behaviour_output_type: type[BehaviourDataType]

    def run(self, config_in: ParticipantConfig) -> BehaviourDataType: ...


class ProcessBehaviourDataStrategyStep(Protocol[BehaviourDataType]):
    input_data_type: type[BehaviourDataType]

    def run(
        self, config_in: ParticipantConfig, raw_behaviour_data_in: BehaviourDataType
    ) -> PipelineOutputData: ...


class ProcessBehaviourDataWithIntervalsStrategyStep(Protocol[BehaviourDataType]):
    input_data_type: type[BehaviourDataType]

    def run(
        self,
        config_in: ParticipantConfig,
        raw_behaviour_data_in: BehaviourDataType,
        trial_intervals_in: TrialIntervals,
    ) -> PipelineOutputData: ...


class GetTrialIntervalsFallbackStartegy(Protocol):
    def run(self, raw_biodata_in: RawBioData) -> tuple[TrialIntervals, Figure, PipelineStatus]: ...


class GetTrialIntervalsStartegy(Protocol[PhysiologyDataType, BehaviourDataType]):
    input_bio_data_type: type[PhysiologyDataType]
    input_behaviour_data_type: type[BehaviourDataType]

    @property
    def fallback_strategy(self) -> GetTrialIntervalsFallbackStartegy | None: ...

    def run(
        self, raw_biodata_in: PhysiologyDataType, raw_behaviour_data_in: BehaviourDataType
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]: ...


# TODO: fill out for LSL
class GetTrialIntervalsFromBehaviourStrategy:
    def run(self): ...


class ProcessPhysiologyFallbackStrategy(Protocol[PhysiologyInputDataType]):
    def run(
        self, config_in: ParticipantConfig, biodata_in: PhysiologyInputDataType
    ) -> PipelineOutputData:
        return PipelineOutputData(config_in.subject_id)


class ProcessPhysiologyDataStrategyStep(Protocol[PhysiologyDataType]):
    input_data_type: type[PhysiologyDataType]
    fallback_strategy: ProcessPhysiologyFallbackStrategy[PhysiologyDataType] | None = None

    def run(
        self,
        config_in: ParticipantConfig,
        biodata_in: PhysiologyDataType,
        trial_interval_data: TrialIntervals,
    ) -> PipelineOutputData: ...


# TODO: Make the Sequentials unmodifiable i.e. you can inheret from them
@dataclass
class SequentialBehaviourImportSteps:
    raw_behaviour_data_Store: RawBehaviourDataStore = field(default_factory=RawBehaviourDataStore)
    steps: Sequence[ImportBehaviourDataStrategyStep] = field(default_factory=list)

    def run(self, config_in: ParticipantConfig) -> tuple[RawBehaviourDataStore, PipelineStatus]:
        pipeline_status = PipelineStatus()
        for step in self.steps:
            try:
                pipeline_raw_behav_data = step.run(config_in=config_in)
                self.raw_behaviour_data_Store.add(pipeline_raw_behav_data)
                pipeline_status.set(step.behaviour_output_type, ProcessingStatus.OK)
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error importing behaviour data for participant %s. %s", config_in.subject_id, e
                )
                pipeline_status.set(step.behaviour_output_type, ProcessingStatus.ERROR)

        return (self.raw_behaviour_data_Store, pipeline_status)


@dataclass
class SequentialBehaviourProcessingSteps:
    steps: Sequence[ProcessBehaviourDataStrategyStep] = field(default_factory=list)
    steps_with_trial_intervals: Sequence[ProcessBehaviourDataWithIntervalsStrategyStep] = field(
        default_factory=list
    )

    def run(
        self,
        config_in: ParticipantConfig,
        data_store_in: RawBehaviourDataStore,
        trial_intervals_in: TrialIntervals | None,
    ) -> tuple[PipelineOutputData, PipelineStatus]:
        behavioural_output_data = PipelineOutputData(config_in.subject_id)
        pipeline_status = PipelineStatus()
        for step in self.steps:
            try:
                in_data_type = step.input_data_type
                raw_behav_data = data_store_in.get(in_data_type)
                step_output: PipelineOutputData = step.run(
                    config_in=config_in, raw_behaviour_data_in=raw_behav_data
                )
                behavioural_output_data = behavioural_output_data.merge(step_output)
                pipeline_status.set(step.input_data_type, ProcessingStatus.OK)

            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error processing %s for participant %s. %s",
                    step.input_data_type,
                    config_in.subject_id,
                    e,
                )
                pipeline_status.set(step.input_data_type, ProcessingStatus.ERROR)

        if trial_intervals_in is not None:
            for step_with_interval in self.steps_with_trial_intervals:
                try:
                    in_data_type = step_with_interval.input_data_type
                    raw_behav_data = data_store_in.get(in_data_type)
                    step_with_interval_output: PipelineOutputData = step_with_interval.run(
                        config_in=config_in,
                        raw_behaviour_data_in=raw_behav_data,
                        trial_intervals_in=trial_intervals_in,
                    )
                    behavioural_output_data = behavioural_output_data.merge(
                        step_with_interval_output
                    )
                    pipeline_status.set(step_with_interval.input_data_type, ProcessingStatus.OK)
                except (ValueError, FileNotFoundError) as e:
                    logger.warning(
                        "Error processing %s for participant %s. %s",
                        step_with_interval.input_data_type,
                        config_in.subject_id,
                        e,
                    )
                    pipeline_status.set(step_with_interval.input_data_type, ProcessingStatus.ERROR)
        elif self.steps_with_trial_intervals:
            logger.warning(
                f"No intervals for behav pipeline for {config_in.subject_id}. Skipping. "
            )
            for step_with_interval in self.steps_with_trial_intervals:
                pipeline_status.set(step_with_interval.input_data_type, ProcessingStatus.ERROR)

        return (behavioural_output_data, pipeline_status)


@dataclass
class SequentialPhysiolgyImportSteps:
    raw_physiology_store: RawPhysiologyDataStore = field(default_factory=RawPhysiologyDataStore)
    steps: Sequence[ImportBioDataStrategyStep] = field(default_factory=list)

    def run(self, config_in: ParticipantConfig) -> tuple[RawPhysiologyDataStore, PipelineStatus]:
        pipeline_status = PipelineStatus()

        for step in self.steps:
            data_out_type = step.output_data_type
            try:
                data_out = step.run(config_in)
                self.raw_physiology_store.add(data_out)
                pipeline_status.set(data_out_type, ProcessingStatus.OK)
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error importing raw physiology data for participant %s. %s",
                    config_in.subject_id,
                    e,
                )
                pipeline_status.set(data_out_type, ProcessingStatus.ERROR)

        return (self.raw_physiology_store, pipeline_status)


@dataclass
class SequentialPhysiologyProcessingSteps:
    steps: Sequence[ProcessPhysiologyDataStrategyStep] = field(default_factory=list)

    def run(
        self,
        config_in: ParticipantConfig,
        data_store_in: RawPhysiologyDataStore,
        intervals_in: TrialIntervals,
    ) -> tuple[PipelineOutputData, PipelineStatus]:
        data_out = PipelineOutputData(config_in.subject_id)
        pipeline_status = PipelineStatus()
        for step in self.steps:
            # No data cuts early without trying to perform fallback
            try:
                in_data_type = step.input_data_type
                biodata_in = data_store_in.get(in_data_type)
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error getting physiology data for participant %s. %s", config_in.subject_id, e
                )
                pipeline_status.set(in_data_type, ProcessingStatus.ERROR)
                continue

            try:
                step_data_out = step.run(config_in, biodata_in, intervals_in)
                data_out = data_out.merge(step_data_out)
                pipeline_status.set(in_data_type, ProcessingStatus.OK)
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error processing physiology for participant %s. %s", config_in.subject_id, e
                )

                pipeline_status.set(in_data_type, ProcessingStatus.ERROR)

                if step.fallback_strategy is not None:
                    step_data_out = step.fallback_strategy.run(config_in, biodata_in)
                    data_out = data_out.merge(step_data_out)
                    pipeline_status.set(in_data_type, ProcessingStatus.PARTIAL)

        return (data_out, pipeline_status)


# Pipeline base class
class PipelineTemplate:
    """
    Template class for processing behavioural and physiological data for a single participant.
    Output data is merged to group level in a subsequent step.

    """

    def __init__(
        self,
        find_participant_strategy_step: FindParticipantFilesStrategyStep,
        sequential_physiology_import_steps: SequentialPhysiolgyImportSteps,
        sequential_behaviour_data_import_steps: SequentialBehaviourImportSteps,
        sequential_behaviour_processing_steps: SequentialBehaviourProcessingSteps,
        get_intervals_strategy: GetTrialIntervalsStartegy,
        sequential_physiology_processing_steps: SequentialPhysiologyProcessingSteps,
    ) -> None:

        self.find_participant_strategy_step = find_participant_strategy_step
        self.behaviour_raw_data_store = RawBehaviourDataStore()
        self.physiolgy_raw_data_store = RawPhysiologyDataStore()

        self.sequential_physiology_import_steps = sequential_physiology_import_steps
        self.sequential_behaviour_data_import_steps = sequential_behaviour_data_import_steps

        self.sequential_behaviour_processing_steps = sequential_behaviour_processing_steps
        self.sequential_physiology_steps = sequential_physiology_processing_steps
        self.get_interval_strategy = get_intervals_strategy

    def run(
        self, participant_id_in: str, data_folder_in: Path, output_folder_in: Path | None = None
    ) -> tuple[ParticipantConfig, PipelineOutputData]:

        pipeline_status = PipelineStatus()
        trial_intervals: TrialIntervals | None = None
        interval_qc_figure: Figure | None = None

        # TODO: can this be run inside the log handler loop?

        participant_config = self.find_participant_strategy_step.run(
            participant_id_in, data_folder_in, output_folder_in
        )
        with participant_log_handler(participant_config):
            behaviour_pipeline_data = PipelineOutputData(participant_config.subject_id)
            physiology_pipeline_data = PipelineOutputData(participant_config.subject_id)

            # Import Data

            # Import Physiology

            self.physiolgy_raw_data_store, physiology_data_status = (
                self.sequential_physiology_import_steps.run(participant_config)
            )
            pipeline_status = pipeline_status.merge(physiology_data_status)

            # Import behaviour data

            self.behaviour_raw_data_store, behav_import_status = (
                self.sequential_behaviour_data_import_steps.run(participant_config)
            )
            pipeline_status = pipeline_status.merge(behav_import_status)

            # Process Data

            # Process trial intervals

            try:
                raw_biodata_for_intervals = self.physiolgy_raw_data_store.get(
                    self.get_interval_strategy.input_bio_data_type
                )
            except ValueError as error:
                logger.warning(f"Could not retreave data from physiology store. - {error}")
                raw_biodata_for_intervals = None
                pipeline_status.set(
                    self.get_interval_strategy.input_bio_data_type, ProcessingStatus.ERROR
                )

            try:
                raw_behav_data_for_intervals = self.behaviour_raw_data_store.get(
                    self.get_interval_strategy.input_behaviour_data_type
                )
            except ValueError as error:
                raw_behav_data_for_intervals = None
                logger.warning(f"Could not retreave data from behavioural store. - {error}")

                pipeline_status.set(
                    self.get_interval_strategy.input_behaviour_data_type, ProcessingStatus.ERROR
                )
            if raw_biodata_for_intervals is not None and raw_behav_data_for_intervals is not None:
                try:
                    trial_intervals, interval_qc_figure, trial_interval_pipeline_status = (
                        self.get_interval_strategy.run(
                            raw_biodata_for_intervals, raw_behav_data_for_intervals
                        )
                    )
                    pipeline_status = pipeline_status.merge(trial_interval_pipeline_status)
                except (TypeError, ValueError) as error:
                    logger.warning(f"Error running trial intervals.{error}")
                    if (
                        self.get_interval_strategy.fallback_strategy is not None
                        and raw_biodata_for_intervals is not None
                    ):
                        trial_intervals, interval_qc_figure, trial_interval_pipeline_status = (
                            self.get_interval_strategy.fallback_strategy.run(
                                raw_biodata_for_intervals
                            )
                        )
                        pipeline_status = pipeline_status.merge(trial_interval_pipeline_status)

            # Process behaviour

            behaviour_pipeline_data, behav_processing_status = (
                self.sequential_behaviour_processing_steps.run(
                    participant_config, self.behaviour_raw_data_store, trial_intervals
                )
            )
            pipeline_status = pipeline_status.merge(behav_processing_status)

            # Process Physiology

            if trial_intervals is not None:
                physiology_pipeline_data, physiology_processing_status = (
                    self.sequential_physiology_steps.run(
                        participant_config, self.physiolgy_raw_data_store, trial_intervals
                    )
                )
                pipeline_status = pipeline_status.merge(physiology_processing_status)
            else:
                logger.warning("No trial intervals available. Skipping physiology.")
                pipeline_status.set(TrialIntervals, ProcessingStatus.ERROR)

            # Output single subject data

            pipeline_data_out = PipelineOutputData(participant_config.subject_id)
            pipeline_data_out.status = pipeline_status
            pipeline_data_out = pipeline_data_out.merge(behaviour_pipeline_data)
            pipeline_data_out = pipeline_data_out.merge(physiology_pipeline_data)
            if interval_qc_figure is not None:
                pipeline_data_out.figure_data_out["Interval_qc"] = interval_qc_figure

        return (participant_config, pipeline_data_out)
