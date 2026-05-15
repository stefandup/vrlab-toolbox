import logging
import mooi_toolbox.config as cfg
import scipy.io as sio
import pandas as pd
import numpy as np
import os

logger = logging.getLogger(__name__)

def clean_biopac_labels(labels_in):

    return [label.strip() for label in labels_in.flatten()]

def load_biopac_data(biopac_fn : str, data_to_load : str) -> pd.DataFrame:
    """Load biopac mat files into pd Dataframe."""
    # time_stamps EDA DF
    
    logger.info(f"Loading {biopac_fn}")
    
    try:
        imported_data = sio.loadmat(biopac_fn)
    except ValueError as e:
        logger.error("Error loading %s: %s",biopac_fn,e)
        raise
    mat_data = imported_data['data']
    mat_isi = imported_data['isi']
    mat_labels = clean_biopac_labels(imported_data['labels'])

    idx = [i for i,s in enumerate(mat_labels) if data_to_load in s]

    if idx is None:
        logger.error("No EDA data found")
        raise 

    data = mat_data[:,idx].squeeze()
    isi = mat_isi.squeeze()/1000 # As in ms
    sampling_freq = 1/isi # Hz should be in seconds :)
    time_stamps = np.arange(len(data))/sampling_freq

    return pd.DataFrame({"time_stamps": time_stamps, data_to_load: data})

def get_subject_id_from_mat(biopac_mat_fn : str) -> str:
    return os.path.basename(biopac_mat_fn).split('.')[0].strip().replace(' ','').split('_')[1]