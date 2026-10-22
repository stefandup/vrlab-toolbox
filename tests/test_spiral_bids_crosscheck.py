import unittest

from vrlab_toolbox.gui.spiral_bids_crosscheck_gui import (
    SpiralCandidateInfo,
    rank_spiral_candidate,
)


def make_candidate(
    *,
    selected_spirals: int = 16,
    eda: float = 100.0,
    ecg: float = 100.0,
    neon: float = 100.0,
    eeg: float = 100.0,
    current_eeg_filename: bool = False,
) -> SpiralCandidateInfo:
    return SpiralCandidateInfo(
        drawing_detected=True,
        detected_attempts=selected_spirals,
        selected_spirals=selected_spirals,
        drawing_active_duration_sec=300.0,
        eda_present=eda > 0,
        eda_coverage_pct=eda,
        ecg_present=ecg > 0,
        ecg_coverage_pct=ecg,
        neon_present=neon > 0,
        neon_coverage_pct=neon,
        eeg_present=eeg > 0,
        eeg_coverage_pct=eeg,
        eeg_nominal_srate=300.0,
        eeg_effective_srate=260.0,
        filename_is_current_eeg_xdf=current_eeg_filename,
        parse_error=False,
    )


class TestSpiralCandidateRanking(unittest.TestCase):
    def test_complete_spiral_structure_beats_current_eeg_filename(self):
        complete_old = make_candidate(selected_spirals=16, current_eeg_filename=False)
        incomplete_current = make_candidate(selected_spirals=15, current_eeg_filename=True)

        self.assertGreater(
            rank_spiral_candidate(complete_old),
            rank_spiral_candidate(incomplete_current),
        )

    def test_better_coverage_beats_current_eeg_filename(self):
        better_old = make_candidate(
            eda=100.0,
            ecg=100.0,
            neon=100.0,
            eeg=95.0,
            current_eeg_filename=False,
        )
        weaker_current = make_candidate(
            eda=40.0,
            ecg=40.0,
            neon=40.0,
            eeg=100.0,
            current_eeg_filename=True,
        )

        self.assertGreater(
            rank_spiral_candidate(better_old),
            rank_spiral_candidate(weaker_current),
        )

    def test_current_eeg_filename_breaks_an_otherwise_exact_tie(self):
        old = make_candidate(current_eeg_filename=False)
        current = make_candidate(current_eeg_filename=True)

        self.assertGreater(rank_spiral_candidate(current), rank_spiral_candidate(old))


if __name__ == "__main__":
    unittest.main()
