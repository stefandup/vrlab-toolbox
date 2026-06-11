import logging
import scipy.io as sio
import pandas as pd
import numpy as np
import os

from mooi_toolbox.processing.biodata import RawBioData
from mooi_toolbox.processing.input_data import PipelineInput

logger = logging.getLogger(__name__)

def clean_biopac_labels(labels_in):

    return [label.strip().split(" ")[0] for label in labels_in.flatten()]

def load_biopac_data(data_in : PipelineInput) -> dict[str,pd.DataFrame]:
    """Load biopac mat files into pd Dataframe."""
    # time_stamps EDA DF
    
    logger.info(f"Loading {data_in.biopac_fn}")
    dfs_out : dict[str,pd.DataFrame] = {}

    try:
        imported_data = sio.loadmat(data_in.biopac_fn)
    except ValueError as e:
        logger.error("Error loading %s: %s",data_in.biopac_fn,e)
        raise
    mat_data = imported_data['data']
    mat_isi = imported_data['isi']
    mat_labels = clean_biopac_labels(imported_data['labels'])

    # Append each dataset to a dictionary. Not they have potentially different sampling freq, 
    # so needs a differnt set for each
    
    for idx,label in enumerate(mat_labels):
        data = mat_data[:,idx].squeeze()
        isi = mat_isi.squeeze()/1000 # As in ms
        sampling_freq = 1/isi # Hz should be in seconds :)
        time_stamps = np.arange(len(data))/sampling_freq
        new_data = pd.DataFrame({"time_stamps" : time_stamps, label : data})
        dfs_out.update({label : new_data})

    return dfs_out

def get_subject_id_from_mat(biopac_mat_fn : str) -> str:
    return os.path.basename(biopac_mat_fn).split('.')[0].strip().replace(' ','').split('_')[1]

class BiopacRawData(RawBioData):
    '''
    Inherets from biodata class. Here we add a load method for the particular data type.
    Using this class based method it is easier to add new methods inherting from the biodata class.
    
    '''
    @classmethod
    def load_data(cls,pipeline_input : PipelineInput):
        biopac_data : dict[str,pd.DataFrame] = load_biopac_data(pipeline_input)
        return cls(biopac_data)