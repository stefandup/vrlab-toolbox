import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PhysiologyFileFormat(Enum):
    MATLAB = ".mat"
    LSL = ".xdf"
    BIOPAC = ".acq"


logger = logging.getLogger(__name__)


# Dataclass is frozen to avoid changes during the pipeline
@dataclass(frozen=True)
class ParticipantConfig:
    subject_id: str
    physiology_fn: str
    physiology_data_type: PhysiologyFileFormat
    data_folder: Path
    behav_folder: str
    _behaviour_file_names: dict[type, Path]
    log_folder: Path
    output_folder: Path
    verbose: bool
    show_plots: bool
    # _expected_date_format = "%Y%m%d%H%M"

    @classmethod
    def from_physiology_data(
        cls,
        id_in: str,
        physiology_data_type_in: PhysiologyFileFormat,
        data_folder_in: Path,
        behaviour_data_types_in: list[type],
        behav_folder_in: Path | None = None,
        output_folder_in: Path | None = None,
        log_folder_in: Path | None = None,
        verbose: bool = False,
        show_plots: bool = False,
    ) -> "ParticipantConfig":

        if not id_in.isalnum():
            raise ValueError(
                f"Participant ID {id_in} is not valid as it contains non alphanumeric characters"
            )
        search_root = data_folder_in
        physiology_fn_list = list(search_root.rglob(f"*_{id_in}_*{physiology_data_type_in.value}"))

        if not physiology_fn_list:
            raise FileNotFoundError(f"No matching physiology files found for {id_in}")

        if len(physiology_fn_list) > 1:
            raise ValueError(
                f"Multiple files detected for subject {id_in}. Expect only 1 {physiology_fn_list}"
            )

        physiology_fn = physiology_fn_list[0]

        expected_date_string_from_physiology = str(physiology_fn).split("_")[0]

        if behav_folder_in is None:
            behav_folder_in = data_folder_in

        if output_folder_in is None:
            output_folder_in = data_folder_in / "output"

        output_folder_in.mkdir(parents=True, exist_ok=True)

        if log_folder_in is None:
            log_folder_in = data_folder_in / "logs"

        log_folder_in.mkdir(parents=True, exist_ok=True)

        behaviour_fn_dict = {}

        for behav_data_type in behaviour_data_types_in:
            glob_pattern = behav_data_type.filename_glob.format(
                date_string=expected_date_string_from_physiology, participant_id=id_in
            )

            file_matches = list(behav_folder_in.rglob(glob_pattern))

            if not file_matches:
                raise FileNotFoundError(
                    f"No file matches for {behav_data_type.__name__} for participant {id_in}"
                )

            if len(file_matches) > 1:
                raise ValueError(
                    f"Multiple {behav_data_type.__name__} files for {id_in}: {file_matches}"
                )

            behaviour_fn_dict[behav_data_type] = file_matches[0]

        return cls(
            subject_id=id_in,
            physiology_fn=str(physiology_fn),
            physiology_data_type=physiology_data_type_in,
            data_folder=data_folder_in,
            behav_folder=str(behav_folder_in),
            _behaviour_file_names=behaviour_fn_dict,
            log_folder=log_folder_in,
            output_folder=output_folder_in,
            verbose=verbose,
            show_plots=show_plots,
        )

    def get_behaviour_file_name(self, behaviour_type: type) -> Path:
        return self._behaviour_file_names[behaviour_type]
