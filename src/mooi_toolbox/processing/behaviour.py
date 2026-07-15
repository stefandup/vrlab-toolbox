import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing.bids import BidsEventsData
from mooi_toolbox.processing.input_data import ParticipantConfig

logger = logging.getLogger(__name__)


# TODO: This is very messy. Not sure if half of these functions arent redundant!
def build_base_output_schema(
    additional_columns: dict[str, pa.Column] | None = None,
) -> pa.DataFrameSchema:
    """Ensure all behaviour data has the minimal required data"""
    return pa.DataFrameSchema(
        {},
        coerce=True,
        strict=False,
    )


@dataclass
class RawBehaviourData:
    subject_config: ParticipantConfig
    raw_behav_df: pd.DataFrame
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_output_schema)

    def __post_init__(self):
        self.raw_behav_df = self.validate_behav_data()

    def validate_behav_data(self) -> pd.DataFrame:
        return self.validation_schema.validate(self.raw_behav_df)

    def to_bids_events(self) -> BidsEventsData:
        return BidsEventsData()

    @classmethod
    def load_from_config(cls, config_in: ParticipantConfig) -> Self:
        behav_df = load_from_participant_config(config_in)
        return cls(config_in, behav_df)


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

    behav_files_found = behaviour_matches_biopac_physiology_data(config_in)

    if not behav_files_found:
        error = f"No files found for {config_in.subject_id}"
        logger.error(error)
        raise FileNotFoundError(error)

    logger.info(f"Found {behav_files_found}")

    behav_df_validated = load_and_validate_behaviour_csv(behav_files_found[0], validation_schema)
    return behav_df_validated


def load_from_participant_config(config_in: ParticipantConfig):
    behav_files_found = behaviour_matches_biopac_physiology_data(config_in)

    if not behav_files_found:
        error = (
            f"No files found for {config_in.subject_id} at {config_in.physiology_fn.split('.')[0]}"
        )
        logger.error(error)
        raise FileNotFoundError(error)

    logger.info(f"Found {behav_files_found}")

    df_out = pd.read_csv(behav_files_found[0])

    return df_out


# Match with physiology data
def behaviour_matches_biopac_physiology_data(config_in: ParticipantConfig) -> list[Path]:
    logger.info(f"Looking for {config_in.subject_id} in {config_in.behav_folder}...")
    search_string = Path(config_in.physiology_fn).stem
    reg_pattern = f"^.*{search_string}.csv$"
    compiled = re.compile(reg_pattern)

    root = Path(config_in.behav_folder)
    return [
        behav_file_path
        for behav_file_path in root.rglob("*")
        if behav_file_path.is_file() and compiled.search(behav_file_path.name)
    ]
