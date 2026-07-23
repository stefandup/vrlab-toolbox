import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar, cast

from matplotlib.figure import Figure

from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat
from mooi_toolbox.processing.output_data import PipelineOutputData

# from mooi_toolbox.processing.vr_intervals import
# TODO: This could potentially form part of pipeline as a class override?
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals

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

    def run(self, participant_id_in: str, data_folder_in: Path) -> ParticipantConfig: ...


class ImportBioDataStrategyStep(Protocol):
    input_data_file_format: PhysiologyFileFormat

    def run(self, config_in: ParticipantConfig) -> RawBioData: ...


class ImportBehaviourDataStrategyStep(Protocol[BehaviourDataOutType]):
    def run(self, config_in: ParticipantConfig) -> BehaviourDataOutType: ...


class ProcessBehaviourDataStrategyStep(Protocol[BehaviourDataType]):
    input_data_type: type[BehaviourDataType]

    def run(
        self, config_in: ParticipantConfig, raw_behaviour_data_in: BehaviourDataType
    ) -> PipelineOutputData: ...


class GetTrialIntervalsStartegy(Protocol[PhysiologyDataType, BehaviourDataType]):
    input_bio_data_type: type[PhysiologyDataType]
    input_behaviour_data_type: type[BehaviourDataType]

    def run(
        self, raw_biodata_in: PhysiologyDataType, raw_behaviour_data_in: BehaviourDataType
    ) -> tuple[TrialIntervals, Figure, PipelineStatus]: ...


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
                pipeline_status.data_in = ProcessingStatus.OK
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error importing behaviour data for participant %s. %s", config_in.subject_id, e
                )
                pipeline_status.data_in = ProcessingStatus.ERROR

        return (self.raw_behaviour_data_Store, pipeline_status)


@dataclass
class SequentialBehaviourProcessingSteps:
    steps: Sequence[ProcessBehaviourDataStrategyStep] = field(default_factory=list)

    def run(
        self,
        config_in: ParticipantConfig,
        data_store_in: RawBehaviourDataStore,
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
                pipeline_status.behaviour = ProcessingStatus.OK
            # TODO: Printout the rest also using data type
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error processing %s for participant %s. %s",
                    in_data_type,
                    config_in.subject_id,
                    e,
                )
                pipeline_status.behaviour = ProcessingStatus.ERROR

        return (behavioural_output_data, pipeline_status)


@dataclass
class SequentialPhysiolgyImportSteps:
    raw_physiology_store: RawPhysiologyDataStore = field(default_factory=RawPhysiologyDataStore)
    steps: Sequence[ImportBioDataStrategyStep] = field(default_factory=list)

    def run(self, config_in: ParticipantConfig) -> tuple[RawPhysiologyDataStore, PipelineStatus]:
        for step in self.steps:
            pipeline_status = PipelineStatus()
            try:
                data_out = step.run(config_in)
                self.raw_physiology_store.add(data_out)
                pipeline_status.data_in = ProcessingStatus.OK
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error importing raw physiology data for participant %s. %s",
                    config_in.subject_id,
                    e,
                )
                pipeline_status.data_in = ProcessingStatus.ERROR

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
                pipeline_status.physiology = ProcessingStatus.ERROR
                continue

            try:
                step_data_out = step.run(config_in, biodata_in, intervals_in)
                data_out = data_out.merge(step_data_out)
                pipeline_status.physiology = ProcessingStatus.OK
            except (ValueError, FileNotFoundError) as e:
                logger.warning(
                    "Error processing physiology for participant %s. %s", config_in.subject_id, e
                )

                pipeline_status.physiology = ProcessingStatus.ERROR

                if step.fallback_strategy is not None:
                    step_data_out = step.fallback_strategy.run(config_in, biodata_in)
                    data_out = data_out.merge(step_data_out)

        return (data_out, pipeline_status)


# Pipeline base class
class PipelineTemplate:
    """
    Template class for processing behavioural and physiological data for a single participant.
    Output data is merged to group level in a subsequent step.

    """

    def __init__(
        self,
        sequential_physiology_import_steps: SequentialPhysiolgyImportSteps,
        sequential_behaviour_data_import_steps: SequentialBehaviourImportSteps,
        sequential_behaviour_processing_steps: SequentialBehaviourProcessingSteps,
        get_intervals_strategy: GetTrialIntervalsStartegy,
        sequential_physiology_processing_steps: SequentialPhysiologyProcessingSteps,
    ) -> None:

        self.behaviour_raw_data_store = RawBehaviourDataStore()
        self.physiolgy_raw_data_store = RawPhysiologyDataStore()

        self.sequential_physiology_import_steps = sequential_physiology_import_steps
        self.sequential_behaviour_data_import_steps = sequential_behaviour_data_import_steps

        self.sequential_behaviour_processing_steps = sequential_behaviour_processing_steps
        self.sequential_physiology_steps = sequential_physiology_processing_steps
        self.get_interval_strategy = get_intervals_strategy

    def run(self, config_in: ParticipantConfig) -> PipelineOutputData:

        pipeline_status = PipelineStatus()
        trial_intervals: TrialIntervals | None = None
        interval_qc_figure: Figure | None = None
        behaviour_pipeline_data = PipelineOutputData(config_in.subject_id)
        physiology_pipeline_data = PipelineOutputData(config_in.subject_id)

        # Import behaviour data

        try:
            self.behaviour_raw_data_store, behav_import_status = (
                self.sequential_behaviour_data_import_steps.run(config_in)
            )
            pipeline_status = pipeline_status.merge(behav_import_status)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing raw biodata for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.data_in = ProcessingStatus.ERROR

        # Process behaviour

        try:
            behaviour_pipeline_data, behav_processing_status = (
                self.sequential_behaviour_processing_steps.run(
                    config_in, self.behaviour_raw_data_store
                )
            )
            pipeline_status = pipeline_status.merge(behav_processing_status)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing behaviour data for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.behaviour = ProcessingStatus.ERROR

        # Import Physiology

        try:
            self.physiolgy_raw_data_store, physiology_data_status = (
                self.sequential_physiology_import_steps.run(config_in)
            )
            pipeline_status = pipeline_status.merge(physiology_data_status)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing raw biodata for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.data_in = ProcessingStatus.ERROR

        # Process trial intervals

        try:
            raw_biodata_for_intervals = self.physiolgy_raw_data_store.get(
                self.get_interval_strategy.input_bio_data_type
            )
            raw_behav_data_for_intervals = self.behaviour_raw_data_store.get(
                self.get_interval_strategy.input_behaviour_data_type
            )
            trial_intervals, interval_qc_figure, trial_interval_pipeline_status = (
                self.get_interval_strategy.run(
                    raw_biodata_for_intervals, raw_behav_data_for_intervals
                )
            )
            pipeline_status = pipeline_status.merge(trial_interval_pipeline_status)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error processing intervals for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.intervals = ProcessingStatus.ERROR

        # Run Physiology

        try:
            if trial_intervals is None:
                raise ValueError(f"Trial intervals unavailable for {config_in.subject_id}")
            physiology_pipeline_data, physiology_processing_status = (
                self.sequential_physiology_steps.run(
                    config_in, self.physiolgy_raw_data_store, trial_intervals
                )
            )
            pipeline_status = pipeline_status.merge(physiology_processing_status)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing physiology data for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.physiology = ProcessingStatus.ERROR

        # Perform fallback if there are no interval data or if there is an error with the interval
        # data

        # Output single subject data

        pipeline_data_out = PipelineOutputData(config_in.subject_id)
        pipeline_data_out.status = pipeline_status
        pipeline_data_out = pipeline_data_out.merge(behaviour_pipeline_data)
        pipeline_data_out = pipeline_data_out.merge(physiology_pipeline_data)
        if interval_qc_figure is not None:
            pipeline_data_out.figure_data_out["Interval_qc"] = interval_qc_figure

        return pipeline_data_out
