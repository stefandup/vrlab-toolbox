import unittest
from pathlib import Path

from vrlab_toolbox.processing import biopac
from vrlab_toolbox.processing.biodata import RawBioData

CORRECT_SAMPLE_MAT_FILE = Path(r"crane_examples\\2026100_DUMMY000_CraneOut.mat")
COPRRECT_SAMPLE_ACQ_FILE = Path(r"longwalkv3_examples\\202609181245_Test 1_LongWalkV3Out.acq")


class TestBiopacPhysiologyImport(unittest.TestCase):
    def test_biopac_mat_import(self):
        mat_file = biopac.import_biopac_mat(CORRECT_SAMPLE_MAT_FILE)

    def test_biopac_acq_import(self):
        acq_file = biopac.import_biopac_acq(COPRRECT_SAMPLE_ACQ_FILE)

    def test_load_biopac_data_mat(self):
        raw_biodata = biopac.load_biopac_data(CORRECT_SAMPLE_MAT_FILE)
        self.assertIsInstance(raw_biodata, RawBioData)

    def test_load_biopac_data_acq(self):
        raw_biodata = biopac.load_biopac_data(COPRRECT_SAMPLE_ACQ_FILE)
        self.assertIsInstance(raw_biodata, RawBioData)
