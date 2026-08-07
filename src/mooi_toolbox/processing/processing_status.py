from dataclasses import dataclass, field
from enum import Enum


class ProcessingStatus(Enum):
    NOT_RUN = "not_run"
    OK = "ok"
    PARTIAL = "partial"
    CORRECTED = "corrected"
    ERROR = "error"


_STATUS_RANK = list(ProcessingStatus)


@dataclass
class PipelineStatus:
    status: dict[type, ProcessingStatus] = field(default_factory=dict)

    def get_as_text(self) -> str:
        """To append to the participant's output data"""
        return " ".join(f"{key.__name__}={value.value}" for key, value in self.status.items())

    def set(self, data_type, status: ProcessingStatus):
        self.status[data_type] = status

    def merge(self, other: "PipelineStatus") -> "PipelineStatus":
        status_out = dict()
        for key in (self.status | other.status).keys():
            status_out[key] = max(
                self.status.get(key, ProcessingStatus.NOT_RUN),
                other.status.get(key, ProcessingStatus.NOT_RUN),
                key=_STATUS_RANK.index,
            )

        return PipelineStatus(status=status_out)
