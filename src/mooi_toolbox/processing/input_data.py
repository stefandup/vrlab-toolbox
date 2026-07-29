import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# TODO: fix consistency here, i.e. BIOPAC vs LSL better
class PhysiologyFileFormat(Enum):
    MATLAB = ".mat"
    LSL = ".xdf"
    BIOPAC = ".acq"


logger = logging.getLogger(__name__)


# TODO: Add Pipelinestatus to config
# Dataclass is frozen to avoid changes during the pipeline
@dataclass(frozen=True)
class ParticipantConfig:
    subject_id: str
    physiology_fn: str
    physiology_data_type: PhysiologyFileFormat
    data_folder: Path
    behav_folder: Path
    _behaviour_file_names: dict[type, Path | None]
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
            logger.warning(
                f"Participant ID {id_in} is not valid as it contains non alphanumeric characters."
                f" Please correct."
            )
        search_root = data_folder_in
        physiology_fn_list = list(search_root.rglob(f"*_{id_in}_*{physiology_data_type_in.value}"))

        if physiology_fn_list:
            physiology_fn = physiology_fn_list[0]

            expected_date_string_from_physiology = str(physiology_fn).split("_")[0]

            if len(physiology_fn_list) > 1:
                logger.warning(
                    f"Multiple files detected for subject {id_in}."
                    f"Expect only 1 {physiology_fn_list}"
                )
        else:
            logger.warning(f"No matching physiology files found for {id_in}")
            physiology_fn = None

        if behav_folder_in is None:
            behav_folder_in = data_folder_in

        if output_folder_in is None:
            output_folder_in = data_folder_in / "output"

        output_folder_in.mkdir(parents=True, exist_ok=True)

        if log_folder_in is None:
            log_folder_in = output_folder_in / "logs"

        log_folder_in.mkdir(parents=True, exist_ok=True)

        behaviour_fn_dict = {}
        # TODO: implement cross checking for this toolbox.
        TEMP = "*"
        for behav_data_type in behaviour_data_types_in:
            glob_pattern = behav_data_type.filename_glob.format(
                date_string=TEMP, participant_id=id_in
            )

            behav_file_matches = list(behav_folder_in.rglob(glob_pattern))

            if physiology_fn_list:  # Check the dates
                behav_date_mismatches = [
                    file
                    for file in behav_file_matches
                    if not str(file).startswith(expected_date_string_from_physiology)
                ]

                if behav_date_mismatches:
                    logger.warning(
                        f"Date mismatch between {behav_date_mismatches} "
                        f"and the physiology file date - {expected_date_string_from_physiology}."
                    )

            if not behav_file_matches:
                logger.warning(
                    f"No file matches for {behav_data_type.__name__} for participant {id_in}"
                )
                behaviour_fn_dict[behav_data_type] = None
                continue
            else:
                behaviour_fn_dict[behav_data_type] = behav_file_matches[0]

            if len(behav_file_matches) > 1:
                logger.warning(
                    f"Multiple {behav_data_type.__name__} files for {id_in}: {behav_file_matches}"
                )

        return cls(
            subject_id=id_in,
            physiology_fn=str(physiology_fn) if physiology_fn else "",
            physiology_data_type=physiology_data_type_in,
            data_folder=data_folder_in,
            behav_folder=behav_folder_in,
            _behaviour_file_names=behaviour_fn_dict,
            log_folder=log_folder_in,
            output_folder=output_folder_in,
            verbose=verbose,
            show_plots=show_plots,
        )

    def get_behaviour_file_name(self, behaviour_type: type) -> Path | None:

        try:
            behav_out = self._behaviour_file_names[behaviour_type]
        except KeyError:
            logger.warning(f"No matching behaviour files for key {behaviour_type}")
            return None

        return behav_out
