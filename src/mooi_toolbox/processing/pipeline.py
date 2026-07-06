from abc import ABC
from typing import Protocol
import logging

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.output_data import PipelineData
from mooi_toolbox.processing.input_data import ParticipantConfig
from mooi_toolbox.processing.vr_intervals import VrIntervals

#from mooi_toolbox.processing.vr_intervals import 
#TODO: This could potentially form part of pipeline as a class override?
from mooi_toolbox.processing.processing_status import PipelineStatus, ProcessingStatus

logger = logging.getLogger(__name__)

# Strategies

#strategy base class
class ImportBioDataStrategy(Protocol):
    def import_data(self, config_in : ParticipantConfig) -> RawBioData:
        ...

class ProcessBehaviourDataStrategy(Protocol):
    def process_behaviour_data(self, config_in : ParticipantConfig, data_in : PipelineData | None = None) ->PipelineData:
        ...

class ProcessPhysiologyDataStrategy(Protocol):
    def process_physiology_data(
            self, 
            config_in : ParticipantConfig, 
            biodata_in : RawBioData,
            data_in : PipelineData | None = None, 
            intervals : VrIntervals | None = None 
            ) ->PipelineData:
        ...

class DataQcStrategy(Protocol):
    """Run the minimal amount of processing to check the data for correctness."""
    def qc_data(self, config_in : ParticipantConfig, data_in : PipelineData | None = None) -> None:
        ...

class SavingDataStrategy(Protocol):
    def save_data(self, config_in : ParticipantConfig, data_in : PipelineData) -> None:
        ...

#Pipeline base class
class PipelineTemplate(ABC):

    def __init__(
            self,
            import_strategy : ImportBioDataStrategy, 
            process_behav_strategy : ProcessBehaviourDataStrategy, 
            process_physiology_strategy : ProcessPhysiologyDataStrategy,
            save_strategy : SavingDataStrategy) -> None:

        self.import_strategy = import_strategy
        self.process_behav_strategy = process_behav_strategy
        self.process_physiology_strategy = process_physiology_strategy
        self.save_strategy = save_strategy

    def run(self, config_in : ParticipantConfig) -> None:

        pipeline_status = PipelineStatus()

        try:
            raw_physiology_data = self.import_strategy.import_data(config_in)
            pipeline_status.data_in = ProcessingStatus.OK
        except (ValueError,FileNotFoundError) as e:
            logger.warning("Error importing raw biodata for participant %s. %s",config_in.subject_id,e)
            pipeline_status.data_in = ProcessingStatus.ERROR

        try:
            pipeline_data = self.process_physiology_strategy.process_physiology_data(config_in,raw_physiology_data)
            pipeline_status.physiology = ProcessingStatus.OK
        except (ValueError,FileNotFoundError) as e:
            logger.warning("Error importing physiology data for participant %s. %s",config_in.subject_id,e)
            pipeline_status.physiology = ProcessingStatus.ERROR

        try:
            pipeline_data = self.process_behav_strategy.process_behaviour_data(config_in,pipeline_data)
            pipeline_status.behaviour = ProcessingStatus.OK
        except (ValueError,FileNotFoundError) as e:
            logger.warning("Error importing behaviour data for participant %s. %s",config_in.subject_id,e)
            pipeline_status.behaviour = ProcessingStatus.ERROR

        try:
            self.save_strategy.save_data(config_in,pipeline_data)
            pipeline_status.saved = ProcessingStatus.OK
        except (ValueError,FileNotFoundError) as e:
            logger.warning("Error importing saved data for participant %s. %s",config_in.subject_id,e)
            pipeline_status.saved = ProcessingStatus.ERROR

