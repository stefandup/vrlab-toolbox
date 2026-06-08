import pandas as pd
from matplotlib.figure import Figure
import logging
import pandera.pandas as pa

from mooi_toolbox.processing import biopac
from mooi_toolbox import config as cfg
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.vr_intervals import get_trigger_intervals
from mooi_toolbox.processing.vr_intervals import match_behav_intervals_with_trigger_intervals
from mooi_toolbox.processing import crane_behaviour_processing as cbp
from mooi_toolbox.processing import crane_debrief_data as debrief

logger = logging.getLogger(__name__)

BLOCK_TYPES = ("NonStressBlock", "StressBlock")
TRIAL_TYPES = ("SlipTrial", "NonSlipTrial")
BEHAVIOUR_OUTPUT_METRICS = (
    "nausea_avg",
    "dizziness_avg",
    "stressed_avg",
    "dropped_total",
    "nr_frustration_barrels",
    "nr_error_slips",
    "nr_slips",
    "nr_no_reason_slips",
    "nr_forced_slips",
    "avg_velocity",
    "target_score",
    *(f"{emotion}_proportion" for emotion in cbp.EMOTIONS_TESTED),
)
DEBRIEF_OUTPUT_METRICS = tuple(debrief.emotion_cols)

def _optional_float_column() -> pa.Column:
    return pa.Column(float, nullable=True, coerce=True, required=False)

def build_participant_output_schema() -> pa.DataFrameSchema:
    """Create schema for the wide participant output produced by this pipeline."""
    behaviour_columns = {
        f"{metric}_{block_type}_{trial_type}": _optional_float_column()
        for metric in BEHAVIOUR_OUTPUT_METRICS
        for block_type in BLOCK_TYPES
        for trial_type in TRIAL_TYPES
    }

    debrief_columns = {
        f"Debrief_{metric}_{trial_type}": _optional_float_column()
        for metric in DEBRIEF_OUTPUT_METRICS
        for trial_type in TRIAL_TYPES
    }

    physiology_columns = {
        r"^.+_SCR_per_min$": pa.Column(
            float,
            nullable=True,
            coerce=True,
            required=False,
            regex=True,
        )
    }

    return pa.DataFrameSchema(
        {
            "Subject_ID": pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=False),
            **behaviour_columns,
            **debrief_columns,
            **physiology_columns,
        },
        coerce=True,
        strict=False,
    )

def validate_participant_output(participant_out_df: pd.DataFrame) -> pd.DataFrame:
    """Validate and coerce the participant-level wide output."""
    return build_participant_output_schema().validate(participant_out_df)

def run_pipeline(subject_id : str,biopac_fn : str,behav_folder : str,verbose : bool = False,show_plots : bool = False) -> tuple[pd.DataFrame,Figure]:
    
    fig : Figure = None

    try:
        eda_raw_timestamped : pd.DataFrame = biopac.load_biopac_data(biopac_fn,cfg.get_biopac_eda_data_label())
    except ValueError as e:
        logger.warning("Error loading biopac eda data. %s",e)
        raise

    participant_data_out = []
            
    try:
        behav_data_out,validated_behav_df = cbp.main(subject_id,behav_folder)
        behav_data_out.insert(0,"Subject_ID",subject_id)
        behav_data_out = behav_data_out.reset_index(drop=True)
        participant_data_out.append(behav_data_out)
        logger.info("Processed behav data for subject %s",subject_id)

    except ValueError as e:
        logger.warning("Skipping behaviour analysis on %s. %s",subject_id,e)

    try:
        debrief_data_out = debrief.main(subject_id,behav_folder)
        debrief_data_out = debrief_data_out.reset_index(drop=True)
        participant_data_out.append(debrief_data_out)

        logger.info("Processed debrief data for subject %s",subject_id)

    except ValueError as e:
        logger.warning("Skipping debrief analysis on %s. %s",subject_id,e)
    

    # Do QC

    vr_intervals = get_trigger_intervals(biopac.load_biopac_data(biopac_fn,'Trigger'))
    scr_df_out = eda.run_eda_intervals(eda_raw_timestamped,vr_intervals)
    
    # Do labeled Physiology
    try:
        labeled_vr_intervals = match_behav_intervals_with_trigger_intervals(vr_intervals,validated_behav_df)
        scr_interval_df_out = eda.run_eda_intervals(eda_raw_timestamped,labeled_vr_intervals)
        scr_interval_df_out = scr_interval_df_out.reset_index(drop=True)
        fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,labeled_vr_intervals)
        participant_data_out.append(scr_interval_df_out)
    except ValueError as e:
            logger.warning("Skipping physiology analysis on %s. %s",subject_id,e)
     
     # TODO: rather validate at subject level

    if fig is None:
        fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,vr_intervals)

    if len(participant_data_out) != 0:
        # Concatenate row wise
        return (pd.concat(participant_data_out, axis = 1),fig)
    else:
        return (pd.DataFrame(),None)

