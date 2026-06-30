from dataclasses import dataclass
from matplotlib.figure import Figure
import pandas as pd
import pandera.pandas as pa

from mooi_toolbox.processing.processing_status import PipelineStatus

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
class PipelineOutput():
    subject_df_out : pd.DataFrame
    figure_data_out : Figure | None
    status : PipelineStatus

    def __post_init__(self):
        self.subject_df_out = self.validate_participant_output()

    def validate_participant_output(self) -> pd.DataFrame:
        return build_base_output_schema().validate(self.subject_df_out)