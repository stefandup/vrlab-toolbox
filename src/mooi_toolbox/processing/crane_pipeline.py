import pandas as pd
from matplotlib.figure import Figure
import logging
import pandera.pandas as pa
from dataclasses import dataclass

from mooi_toolbox.processing import biopac
from mooi_toolbox.processing import eda
from mooi_toolbox.processing.vr_intervals import get_trigger_intervals
from mooi_toolbox.processing.vr_intervals import match_behav_intervals_with_trigger_intervals
from mooi_toolbox.processing import crane_behaviour_processing as cbp
from mooi_toolbox.processing import crane_debrief_data as debrief
from mooi_toolbox.processing.processing_status import ProcessingStatus, PipelineStatus
from mooi_toolbox.processing.input_data import PipelineInput

@dataclass
class CranePipelineOutput():

    subject_df_out : pd.DataFrame
    figure_data_out : Figure | None
    status : PipelineStatus

    def __post_init__(self):
        self.subject_df_out = validate_participant_output(self.subject_df_out)

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
EXPECTED_INTERVAL_NR = 23
def _optional_float_column() -> pa.Column:
    return pa.Column(float, nullable=True, coerce=True, required=False)

#Schema builds more or less automatically based on the constants set.
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
            "Subject_ID": pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=True),
            **behaviour_columns,
            **debrief_columns,
            **physiology_columns,
            "Processing_Status" : pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=True)
        },
        coerce=True,
        strict=False,
    )

def validate_participant_output(participant_out_df: pd.DataFrame) -> pd.DataFrame:
    """Validate and coerce the participant-level wide output."""
    return build_participant_output_schema().validate(participant_out_df)

def get_error_output(data_in : PipelineInput, status_in : PipelineStatus) -> CranePipelineOutput:

    return CranePipelineOutput(
        subject_df_out=pd.DataFrame({"Subject_ID" : [data_in.subject_id], 
                                     "Processing_Status" : [status_in.get_as_text()]}),
        figure_data_out=None,
        status=status_in
        ) 

def run_pipeline(data_in : PipelineInput) -> CranePipelineOutput:

    validated_behav_df = None
    fig : Figure | None = None
    # Assume OK unless and exception is raied
    status = PipelineStatus()

    # Input raw eda
    
    try:
        raw_timestamped_data : biopac.BiopacRawData = biopac.BiopacRawData.load_data(data_in)
        eda_raw_timestamped = raw_timestamped_data['EDA']
        status.data_in = ProcessingStatus.OK
    except (ValueError,FileNotFoundError) as e:
        logger.warning("Error loading biopac eda data. %s",e)
        status.data_in = ProcessingStatus.ERROR
        return get_error_output(data_in,status)

    participant_data_out = []

    # Import behaviour data
    try:
        behav_data_out,validated_behav_df = cbp.main(data_in.subject_id,data_in.behav_folder)
        behav_data_out.insert(0,"Subject_ID",data_in.subject_id)
        behav_data_out = behav_data_out.reset_index(drop=True)
        participant_data_out.append(behav_data_out)
        logger.info("Processed behav data for subject %s",data_in.subject_id)
        status.behaviour = ProcessingStatus.OK
    except (ValueError,FileNotFoundError) as e:
        logger.warning("Skipping behaviour analysis on %s. %s",data_in.subject_id,e)
        status.behaviour = ProcessingStatus.ERROR

    try:
        debrief_data_out = debrief.main(data_in.subject_id,data_in.behav_folder)
        debrief_data_out = debrief_data_out.reset_index(drop=True)
        participant_data_out.append(debrief_data_out)

        logger.info("Processed debrief data for subject %s",data_in.subject_id)
        status.debrief = ProcessingStatus.OK

    except (ValueError,FileNotFoundError) as e:
        logger.warning("Skipping debrief analysis on %s. %s",data_in.subject_id,e)
        status.debrief = ProcessingStatus.ERROR
    
    # Do QC
    vr_intervals,status_out = get_trigger_intervals(raw_timestamped_data['Trigger'])
    if len(vr_intervals) != EXPECTED_INTERVAL_NR:
        logger.warning("Interval count is %d and not %d for subject %s.",len(vr_intervals),EXPECTED_INTERVAL_NR,data_in.subject_id)
        status.intervals = ProcessingStatus.ERROR
    else:
        status.intervals = status_out

    scr_df_out = eda.run_eda_intervals(eda_raw_timestamped,vr_intervals)
    if validated_behav_df is not None:
        # Do labeled Physiology
        try:
            labeled_vr_intervals,behav_status = match_behav_intervals_with_trigger_intervals(vr_intervals,validated_behav_df)
            status.behaviour = behav_status
            scr_interval_df_out = eda.run_eda_intervals(eda_raw_timestamped,labeled_vr_intervals)
            scr_interval_df_out = scr_interval_df_out.reset_index(drop=True)

            scr_interval_df_out_corr = eda.correct_order(scr_interval_df_out)
            participant_data_out.append(scr_interval_df_out_corr)
            fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,labeled_vr_intervals)

            if status.intervals == ProcessingStatus.ERROR:
                status.physiology = ProcessingStatus.PARTIAL
            else:    
                status.physiology = ProcessingStatus.OK

        except ValueError as e:
                logger.warning("Skipping physiology analysis on %s. %s",data_in.subject_id,e)
                status.physiology = ProcessingStatus.ERROR
    else:
        status.behaviour = ProcessingStatus.ERROR
        status.physiology = ProcessingStatus.ERROR

    # Append the final status
    participant_data_out.append(pd.DataFrame({"Processing_Status" : [status.get_as_text()]})) 

    if fig is None:
        fig = eda.run_eda_qc(eda_raw_timestamped,scr_df_out,vr_intervals)

    df_out = pd.concat(participant_data_out, axis = 1)

    if "Subject_ID" not in df_out.columns:
        df_out.insert(0, "Subject_ID", data_in.subject_id)

    # Move processing to front

    col_to_mv = "Processing_Status"

    if col_to_mv in df_out.columns:
        cols = df_out.columns.tolist()
        cols.remove(col_to_mv)
        cols.insert(1, col_to_mv)
        df_out = df_out[cols]

    return CranePipelineOutput(
            subject_df_out=df_out,
            figure_data_out=fig,
            status=status
            )

