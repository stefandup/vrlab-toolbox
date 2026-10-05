import pandas as pd
from matplotlib.figure import Figure

from vrlab_toolbox.gui.spiral_process_results_gui import (
    SPIRAL_PROCESS_RESULTS_CONFIG,
    build_spiral_group_dashboard,
    spiral_dashboard_overhead_lines,
)


def _sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Subject_ID": "1001",
                "Spiral_Attempts_Detected": 18,
                "Spiral_Selected_Count": 16,
                "Switch_Time_sec": 250.0,
                "Dominant_SCR_per_min": 2.0,
                "NonDominant_SCR_per_min": 3.0,
                "C3_dominant_alpha": 1.0,
                "C3_nondominant_alpha": 1.2,
                "C4_dominant_alpha": 1.1,
                "C4_nondominant_alpha": 1.3,
                "Cz_dominant_alpha": 1.4,
                "Cz_nondominant_alpha": 1.5,
                "O1_dominant_alpha": 2.0,
                "O1_nondominant_alpha": 2.2,
                "O2_dominant_alpha": 2.1,
                "O2_nondominant_alpha": 2.3,
                "C3_dominant_beta": 0.5,
                "C3_nondominant_beta": 0.6,
                "C4_dominant_beta": 0.7,
                "C4_nondominant_beta": 0.8,
                "Cz_dominant_beta": 0.9,
                "Cz_nondominant_beta": 1.0,
                "Processing_Status": "TrialIntervals=ok SpiralEEGProcessing=ok SpiralEDAProcessing=ok",
            }
        ]
    )


def test_spiral_process_results_config() -> None:
    assert SPIRAL_PROCESS_RESULTS_CONFIG.dataset_name == "spiral"
    assert SPIRAL_PROCESS_RESULTS_CONFIG.csv_glob == "spiral_process_batch_out.csv"
    assert SPIRAL_PROCESS_RESULTS_CONFIG.bids_physio_glob == "*.xdf"


def test_spiral_dashboard_builds_three_panels() -> None:
    figure = Figure()
    build_spiral_group_dashboard(figure, _sample_dataframe(), ["1001"])
    assert len(figure.axes) == 3


def test_spiral_dashboard_overhead_reports_completion() -> None:
    lines = spiral_dashboard_overhead_lines(_sample_dataframe(), ["1001"])
    assert any("16/16" in line and "1 / 1" in line for line in lines)
    assert any("18.0" in line for line in lines)
    assert any("250.0 s" in line for line in lines)
