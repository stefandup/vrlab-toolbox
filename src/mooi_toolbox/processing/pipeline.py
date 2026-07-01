from abc import ABC, abstractmethod
from typing import Protocol

from mooi_toolbox.processing.output_data import PipelineData
from mooi_toolbox.processing.input_data import ParticipantConfig

# Strategies

#strategy base class
class ImportDataStrategy(Protocol):
    def import_data(self, config_in : ParticipantConfig) -> PipelineData:
        ...

class ProcessBehaviourDataStrategy(Protocol):
    def process_behaviour_data(self, config_in : ParticipantConfig, data_in : PipelineData) ->PipelineData:
        ...

class ProcessPhysiologyDataStrategy(Protocol):
    def process_physiology_data(self, config_in : ParticipantConfig, data_in : PipelineData) ->PipelineData:
        ...

class DataQcStrategy(Protocol):
    """Run the minimal amount of processing to check the data for correctness."""
    def qc_data(self, config_in : ParticipantConfig, data_in : PipelineData) -> None:
        ...

class SavingDataStrategy(Protocol):
    def save_data(self, config_in : ParticipantConfig, data_in : PipelineData) -> None:
        ...

#Pipeline base class
class PipelineTemplate(ABC):

    def __init__(
            self,
            import_strategy : ImportDataStrategy, 
            process_behav_strategy : ProcessBehaviourDataStrategy, 
            process_physiology_strategy : ProcessPhysiologyDataStrategy,
            save_strategy : SavingDataStrategy) -> None:

        self.import_strategy = import_strategy
        self.process_behav_strategy = process_behav_strategy
        self.process_physiology_strategy = process_physiology_strategy
        self.save_strategy = save_strategy

    def run(self, config_in : ParticipantConfig) -> None:

        pipeline_data = self.import_strategy.import_data(config_in)
        pipeline_data = self.process_behav_strategy.process_behaviour_data(config_in,pipeline_data)
        pipeline_data = self.process_physiology_strategy.process_physiology_data(config_in,pipeline_data)
        self.save_strategy.save_data(config_in,pipeline_data)

