from dataclasses import dataclass
from matplotlib.figure import Figure
import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing.processing_status import PipelineStatus
from mooi_toolbox.processing.input_data import ParticipantConfig

def build_base_output_schema( additional_columns : dict[str, pa.Column] | None = None) -> pa.DataFrameSchema:
    '''Ensure that all pipelines have Subject_ID and Processing_Status values'''
    return pa.DataFrameSchema(
            {
                "Subject_ID": pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=True),
                **(additional_columns or {}),
                "Processing_Status" : pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=True)
            },
            coerce=True,
            strict=False,
        )

@dataclass
class PipelineData():
    subject_df_out : pd.DataFrame
    figure_data_out : Figure | None
    status : PipelineStatus

    def __post_init__(self):
        self.subject_df_out = self.validate_participant_output()

    def validate_participant_output(self) -> pd.DataFrame:
        return build_base_output_schema().validate(self.subject_df_out)

    @classmethod
    def error(cls, data_in : ParticipantConfig , status_in : PipelineStatus):
        error_df_out = pd.DataFrame(
            {"Subject_ID" : [data_in.subject_id],
             "Processing_Status" : [status_in.get_as_text()]})
        
        return cls(
            subject_df_out = error_df_out,
            figure_data_out = None,
            status=status_in
            )
