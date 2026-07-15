import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar, cast

from mooi_toolbox.processing.behaviour import RawBehaviourData
from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.output_data import PipelineOutputData

# from mooi_toolbox.processing.vr_intervals import
# TODO: This could potentially form part of pipeline as a class override?
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus
from mooi_toolbox.processing.trial_intervals import TrialIntervals

logger = logging.getLogger(__name__)

BehaviourDataType = TypeVar("BehaviourDataType", bound="RawBehaviourData")
PhysiologyDataType = TypeVar("PhysiologyDataType", bound="RawBioData")


# TODO: Probably can use a template method here for the StoreClass...
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


class ImportBioDataStrategyStep(Protocol):
    def run(self, config_in: ParticipantConfig) -> RawBioData: ...


class ImportBehaviourDataStrategyStep(Protocol):
    def run(self, config_in: ParticipantConfig) -> RawBehaviourData: ...


class ProcessBehaviourDataStrategyStep(Protocol):
    input_data_type: type[RawBehaviourData]

    def run(
        self, config_in: ParticipantConfig, raw_behaviour_data_in: RawBehaviourData
    ) -> PipelineOutputData: ...


class GetTrialIntervalsStartegy(Protocol):
    input_bio_data_type: type[RawBioData]
    input_behaviour_data_type: type[RawBehaviourData]

    def run(
        self, raw_biodata_in: RawBioData, raw_behaviour_data_in: RawBehaviourData
    ) -> tuple[TrialIntervals, PipelineStatus]: ...


class ProcessPhysiologyDataStrategyStep(Protocol):
    input_data_type: type[RawBioData]

    def run(
        self,
        config_in: ParticipantConfig,
        biodata_in: RawBioData,
        trial_intervals: TrialIntervals | None = None,
    ) -> PipelineOutputData: ...


class SavingDataStrategy(Protocol):
    def run(self, config_in: ParticipantConfig, data_in: PipelineOutputData) -> None: ...


@dataclass
class SequentialBehaviourImportSteps:
    raw_behaviour_data_Store: RawBehaviourDataStore = field(default_factory=RawBehaviourDataStore)
    steps: Sequence[ImportBehaviourDataStrategyStep] = field(default_factory=list)

    def run(self, config_in: ParticipantConfig) -> RawBehaviourDataStore:

        for step in self.steps:
            pipeline_raw_behav_data = step.run(config_in=config_in)
            self.raw_behaviour_data_Store.add(pipeline_raw_behav_data)

        return self.raw_behaviour_data_Store


@dataclass
class SequentialBehaviourProcessingSteps:
    steps: Sequence[ProcessBehaviourDataStrategyStep] = field(default_factory=list)

    def run(
        self,
        config_in: ParticipantConfig,
        data_store_in: RawBehaviourDataStore,
    ) -> PipelineOutputData:
        behavioural_output_data = PipelineOutputData(config_in.subject_id)
        for step in self.steps:
            in_data_type = step.input_data_type
            raw_behav_data = data_store_in.get(in_data_type)
            step_output: PipelineOutputData = step.run(
                config_in=config_in, raw_behaviour_data_in=raw_behav_data
            )
            behavioural_output_data.merge(step_output)
        return behavioural_output_data


@dataclass
class SequentialPhysiolgyImportSteps:
    raw_physiology_store: RawPhysiologyDataStore = field(default_factory=RawPhysiologyDataStore)
    steps: Sequence[ImportBioDataStrategyStep] = field(default_factory=list)

    def run(self, config_in: ParticipantConfig) -> RawPhysiologyDataStore:
        for step in self.steps:
            data_out = step.run(config_in)
            self.raw_physiology_store.add(data_out)

        return self.raw_physiology_store


@dataclass
class SequentialPhysiologyProcessingSteps:
    data_out: PipelineOutputData
    steps: Sequence[ProcessPhysiologyDataStrategyStep] = field(default_factory=list)

    def run(
        self,
        config_in: ParticipantConfig,
        data_store_in: RawPhysiologyDataStore,
        intervals_in: TrialIntervals,
    ):

        for step in self.steps:
            in_data_type = step.input_data_type
            biodata_in = data_store_in.get(in_data_type)
            step_data_out = step.run(config_in, biodata_in, intervals_in)
            self.data_out.merge(step_data_out)

        return self.data_out


# Pipeline base class
class PipelineTemplate:
    def __init__(
        self,
        behaviour_raw_data_store: RawBehaviourDataStore,
        physiolgy_raw_data_store: RawPhysiologyDataStore,
        sequential_physiology_import_steps: SequentialPhysiolgyImportSteps,
        sequential_behaviour_data_import_steps: SequentialBehaviourImportSteps,
        sequential_behaviour_processing_steps: SequentialBehaviourProcessingSteps,
        get_intervals_strategy: GetTrialIntervalsStartegy,
        sequential_physiology_processing_steps: SequentialPhysiologyProcessingSteps,
        save_strategy: SavingDataStrategy,
    ) -> None:

        self.behaviour_raw_data_store = behaviour_raw_data_store
        self.physiolgy_raw_data_store = physiolgy_raw_data_store

        self.sequential_physiology_import_steps = sequential_physiology_import_steps
        self.sequential_behaviour_data_import_steps = sequential_behaviour_data_import_steps

        self.sequential_behaviour_steps = sequential_behaviour_processing_steps
        self.sequential_physiology_steps = sequential_physiology_processing_steps
        self.get_interval_strategy = get_intervals_strategy
        self.save_strategy = save_strategy

    def run(self, config_in: ParticipantConfig) -> None:

        pipeline_status = PipelineStatus()

        try:
            self.behaviour_raw_data_store = self.sequential_behaviour_data_import_steps.run(
                config_in
            )
            pipeline_status.data_in = ProcessingStatus.OK
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing raw biodata for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.data_in = ProcessingStatus.ERROR

        try:
            pipeline_data = self.sequential_behaviour_steps.run(
                config_in, self.behaviour_raw_data_store
            )
            pipeline_status.behaviour = ProcessingStatus.OK
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing behaviour data for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.behaviour = ProcessingStatus.ERROR

        try:
            self.physiolgy_raw_data_store = self.sequential_physiology_import_steps.run(config_in)
            pipeline_status.data_in = ProcessingStatus.OK
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing raw biodata for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.data_in = ProcessingStatus.ERROR

        try:
            raw_biodata_for_intervals = self.physiolgy_raw_data_store.get(
                self.get_interval_strategy.input_bio_data_type
            )
            raw_behav_data_for_intervals = self.behaviour_raw_data_store.get(
                self.get_interval_strategy.input_behaviour_data_type
            )
            trial_intervals, trial_interval_pipeline_status = self.get_interval_strategy.run(
                raw_biodata_for_intervals, raw_behav_data_for_intervals
            )
            pipeline_status = pipeline_status.merge(trial_interval_pipeline_status)
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error processing intervals for participant %s. %s", config_in.subject_id, e
            )

        try:
            pipeline_data = self.sequential_physiology_steps.run(
                config_in, self.physiolgy_raw_data_store, trial_intervals
            )
            pipeline_status.physiology = ProcessingStatus.OK
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing physiology data for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.physiology = ProcessingStatus.ERROR

        try:
            self.save_strategy.run(config_in, pipeline_data)
            pipeline_status.saved = ProcessingStatus.OK
        except (ValueError, FileNotFoundError) as e:
            logger.warning(
                "Error importing saved data for participant %s. %s", config_in.subject_id, e
            )
            pipeline_status.saved = ProcessingStatus.ERROR
