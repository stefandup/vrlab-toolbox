import logging
import re
from pathlib import Path
from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing.input_data import ParticipantConfig

logger = logging.getLogger(__name__)


def build_base_output_schema( additional_columns : dict[str, pa.Column] | None = None
                             ) -> pa.DataFrameSchema
    """Ensure all behaviour data has the minimal required data"""
    return pa.DataFrameSchema(
        {

        },
        coerce=True,
        strict=False,
    )


@dataclass
class BehaviourData:

    subject_config: ParticipantConfig
    behav_df : pd.DataFrame = field(init=False)

    def __post_init__(self):
        self.behav_df = self.validate_behav_data()

    def validate_behav_data(self) -> pd.DataFrame:
        return build_base_output_schema().validate(self.behav_df)

    @classmethod
    def read_csv(cls, config_in : ParticipantConfig):
        df = load_physiology_data_from_csv(config_in)
        return cls(config_in).validate_behav_data()

def load_and_validate_behaviour_csv(
    behav_file_fn: Path, validation_schema: pa.DataFrameSchema
) -> pd.DataFrame:
    # TODO: Decide what to do when multiple csv files are found
    behav_df = pd.read_csv(behav_file_fn)
    try:
        behav_df_validated = validation_schema.validate(behav_df)
    except pa.errors.SchemaErrors as e:
        logger.error("Error loading %s: %s", behav_file_fn, e.failure_cases.to_string(index=False))
        raise

    logger.info("Successfully loaded %s", behav_file_fn)

    return behav_df_validated


def load_validate_physiology_behav_data(
    config_in: ParticipantConfig, validation_schema: pa.DataFrameSchema
) -> pd.DataFrame:
    """
    Outputs validated dataframe of the behaviour data with associated physiology using a
    pandera data schema.

    """

    behav_files_found = behaviour_matches_physiology_data(config_in)

    if not behav_files_found:
        error = f"No files found for {config_in.subject_id}"
        logger.error(error)
        raise FileNotFoundError(error)

    logger.info(f"Found {behav_files_found}")

    behav_df_validated = load_and_validate_behaviour_csv(behav_files_found[0], validation_schema)
    return behav_df_validated

def load_physiology_data_from_csv(config_in : ParticipantConfig):
    behav_files_found = behaviour_matches_physiology_data(config_in)
    
    if not behav_files_found:
        error = f"No files found for {config_in.subject_id}"
        logger.error(error)
        raise FileNotFoundError(error)

    logger.info(f"Found {behav_files_found}")

    df_out = pd.read_csv(behav_files_found[0])

    return df_out

# Match with physiology data
def behaviour_matches_physiology_data(config_in: ParticipantConfig) -> list[Path]:
    logger.info(f"Looking for {config_in.subject_id} in {config_in.behav_folder}...")
    search_string = config_in.physiology_fn.split(".")[0]
    reg_pattern = f"^.*{search_string}.csv$"
    compiled = re.compile(reg_pattern)

    root = Path(config_in.behav_folder)
    return [
        behav_file_path
        for behav_file_path in root.rglob("*")
        if behav_file_path.is_file() and compiled.search(behav_file_path.name)
    ]
