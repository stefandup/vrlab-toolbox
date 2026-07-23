import logging
import os

import numpy as np
import pandas as pd
import scipy.io as sio

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import ParticipantConfig

logger = logging.getLogger(__name__)


class FindParticipantFilesWithBiopacStrategyStep:
    def run(self, participant_id_in: str) -> ParticipantConfig:

        return ParticipantConfig()


class BiopacDataImportStartegy:
    def run(self, config_in: ParticipantConfig) -> RawBioData:

        raw_data_for_pipeline = load_biopac_data(config_in)

        return raw_data_for_pipeline


def clean_biopac_labels(labels_in):

    return [label.strip().split(" ")[0] for label in labels_in.flatten()]


def load_biopac_data(config_in: ParticipantConfig) -> RawBioData:
    """Load biopac mat files into pd Dataframe."""
    # time_stamps EDA DF

    logger.info(f"Loading {config_in.physiology_fn}")
    dfs_out: dict[str, pd.DataFrame] = {}

    try:
        imported_data = sio.loadmat(config_in.physiology_fn)
    except ValueError as e:
        logger.error("Error loading %s: %s", config_in.physiology_fn, e)
        raise
    mat_data = imported_data["data"]
    mat_isi = imported_data["isi"]
    mat_labels = clean_biopac_labels(imported_data["labels"])

    # Append each dataset to a dictionary. Not they have potentially different sampling freq,
    # so needs a differnt set for each

    for idx, label in enumerate(mat_labels):
        data = mat_data[:, idx].squeeze()
        isi = mat_isi.squeeze() / 1000  # As in ms
        sampling_freq = 1 / isi  # Hz should be in seconds :)
        time_stamps = np.arange(len(data)) / sampling_freq
        new_data = pd.DataFrame({"time_stamps": time_stamps, label: data})
        dfs_out.update({label: new_data})

    raw_bio_data_out = RawBioData(raw_data=dfs_out)

    return raw_bio_data_out


def get_subject_id_from_mat(biopac_mat_fn: str) -> str:
    return os.path.basename(biopac_mat_fn).split(".")[0].strip().replace(" ", "").split("_")[1]
