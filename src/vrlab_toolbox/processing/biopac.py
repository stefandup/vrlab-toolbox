import logging
import os
from pathlib import Path

import bioread
import numpy as np
import pandas as pd
import scipy.io as sio

from vrlab_toolbox.processing.biodata import RawBioData
from vrlab_toolbox.processing.input_data import ParticipantConfig, PhysiologyFileFormat

logger = logging.getLogger(__name__)


class BiopacPhysiologyDataImportStartegy:
    input_data_file_format = PhysiologyFileFormat.MATLAB
    output_data_type = RawBioData

    def run(self, config_in: ParticipantConfig) -> RawBioData:

        raw_data_for_pipeline = load_biopac_data(Path(config_in.physiology_fn))

        return raw_data_for_pipeline


def clean_biopac_mat_labels(labels_in: np.ndarray) -> list[str]:

    return [label.strip().split(" ")[0] for label in labels_in.flatten()]


def clean_biopac_acq_label(label_in: str) -> str:
    return label_in.strip().split(" ")[0]


def import_biopac_acq(physiology_fn) -> dict[str, pd.DataFrame]:
    imported_data = bioread.read_file(physiology_fn)
    dfs_out: dict[str, pd.DataFrame] = {}

    for channel in imported_data.channels:
        if channel.name is not None:
            label = clean_biopac_acq_label(channel.name)
            raw_channel_data = channel.data
            if raw_channel_data is not None:
                sampling_freq = channel.samples_per_second
                time_stamps = np.arange(len(raw_channel_data)) / np.float64(sampling_freq)
                new_data = pd.DataFrame({"time_stamps": time_stamps, label: raw_channel_data})

                dfs_out.update({label: pd.DataFrame(new_data)})

    return dfs_out


def import_biopac_mat(physiology_fn) -> dict[str, pd.DataFrame]:
    dfs_out: dict[str, pd.DataFrame] = {}
    imported_data = sio.loadmat(physiology_fn)
    mat_data = imported_data["data"]
    mat_isi = imported_data["isi"]
    mat_labels = clean_biopac_mat_labels(imported_data["labels"])

    # Append each dataset to a dictionary. Not they have potentially different sampling freq,
    # so needs a differnt set for each

    for idx, label in enumerate(mat_labels):
        data = mat_data[:, idx].squeeze()
        isi = mat_isi.squeeze() / 1000  # As in ms
        sampling_freq = 1 / isi  # Hz should be in seconds :)
        time_stamps = np.arange(len(data)) / sampling_freq
        new_data = pd.DataFrame({"time_stamps": time_stamps, label: data})
        dfs_out.update({label: new_data})

    return dfs_out


get_physiology_importer = {".mat": import_biopac_mat, ".acq": import_biopac_acq}


def load_biopac_data(physiology_fn: Path) -> RawBioData:
    """Load biopac mat files into pd Dataframe."""
    # time_stamps EDA DF

    logger.info(f"Loading {str(physiology_fn)}")

    try:
        physiology_importer = get_physiology_importer[physiology_fn.suffix]
        imported_data = physiology_importer(physiology_fn)
    except ValueError as e:
        logger.error("Error loading %s: %s", physiology_fn, e)
        raise

    raw_bio_data_out = RawBioData(raw_data=imported_data)

    return raw_bio_data_out


def get_subject_id_from_mat(biopac_mat_fn: Path) -> str:
    return (
        os.path.basename(str(biopac_mat_fn))
        .split(".")[0]
        .strip()
        .replace(" ", "")
        .split("_")[0]
        .replace("sub-", "")
    )
