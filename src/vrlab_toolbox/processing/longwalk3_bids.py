import logging
import re

logger = logging.getLogger(__name__)

PHYSIOLOGY_GLOB = "*_LongWalkV3Out.acq"
BEHAVIOUR_GLOB = "*_behaviour.csv"
DATATYPE_FOLDER_NAME = "beh"
# Will have 3 planned sessions
SESSION_TOKEN = "ses-"
# TODO Runs to count up for multiple ones
RUN_TOKEN = "run-000"
TASK_TOKEN = "task-longwalkv3"
_SUBJECT_ID_PATTERN = re.compile(r"^(?:(?P<date>\d+)[_-])?(?P<subject_id>.+?).*$", re.IGNORECASE)
_DUPLICATE_COPY_MARKER_PATTERN = re.compile(r"\(\d+\)\s*$")
_PID_DASH_PATTERN = re.compile(r"^PID-(\d+)$", re.IGNORECASE)


def gather_behaviour_data(datetime_in, subject_id_in: str):
    pass
