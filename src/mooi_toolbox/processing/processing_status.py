from enum import Enum

class ProcessingStatus(Enum):
    ERROR = "error"
    PARTIAL = "partial"
    OK = "ok"
