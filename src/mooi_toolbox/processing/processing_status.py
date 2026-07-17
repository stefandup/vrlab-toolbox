from dataclasses import asdict, dataclass, fields
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
    # TODO: Split data_in into behav data, physiology data etc.
    data_in: ProcessingStatus = ProcessingStatus.NOT_RUN
    behaviour: ProcessingStatus = ProcessingStatus.NOT_RUN
    intervals: ProcessingStatus = ProcessingStatus.NOT_RUN
    physiology: ProcessingStatus = ProcessingStatus.NOT_RUN

    def as_dict(self) -> dict[str, ProcessingStatus]:
        """For looping"""
        return asdict(self)

    def get_as_text(self) -> str:
        """To append to the participant's output data"""
        return " ".join(f"{key}={value.value}" for key, value in self.as_dict().items())

    def merge(self, other: "PipelineStatus") -> "PipelineStatus":
        merged_stage_fields = {}
        for stage_field in fields(self):
            name = stage_field.name
            self_field_value = getattr(self, name)
            other_field_value = getattr(other, name)
            max_field_value = max(self_field_value, other_field_value, key=_STATUS_RANK.index)
            merged_stage_fields[name] = max_field_value
        return PipelineStatus(**merged_stage_fields)
