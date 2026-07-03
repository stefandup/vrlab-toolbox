from enum import Enum
from dataclasses import dataclass, asdict

class ProcessingStatus(Enum):
    NOT_RUN = "not_run"
    CORRECTED = "corrected"
    ERROR = "error"
    PARTIAL = "partial"
    OK = "ok"

@dataclass
class PipelineStatus:

    data_in : ProcessingStatus = ProcessingStatus.NOT_RUN
    behaviour : ProcessingStatus  = ProcessingStatus.NOT_RUN
    debrief : ProcessingStatus  = ProcessingStatus.NOT_RUN
    intervals : ProcessingStatus  = ProcessingStatus.NOT_RUN
    physiology : ProcessingStatus  = ProcessingStatus.NOT_RUN
    saved : ProcessingStatus = ProcessingStatus.NOT_RUN

    def as_dict(self) -> dict[str,ProcessingStatus]:
        '''For looping'''
        return asdict(self)
    
    def get_as_text(self) -> str:
        '''To append to the participant's output data'''
        return " ".join(f"{key}={value.value}" for key, value in self.as_dict().items())