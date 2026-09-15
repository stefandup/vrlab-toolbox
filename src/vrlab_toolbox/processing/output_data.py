from dataclasses import dataclass, field
from typing import Self

import pandas as pd
import pandera.pandas as pa
from matplotlib.figure import Figure

from vrlab_toolbox.processing.processing_status import PipelineStatus


def build_base_pipeline_output_schema(
    additional_columns: dict[str, pa.Column] | None = None,
) -> pa.DataFrameSchema:
    """Ensure that all pipelines have Subject_ID and Processing_Status values"""
    return pa.DataFrameSchema(
        {
            "Subject_ID": pa.Column(pd.StringDtype(), nullable=False, coerce=True, required=True),
            **(additional_columns or {}),
            "Processing_Status": pa.Column(
                pd.StringDtype(), nullable=False, coerce=True, required=True
            ),
        },
        coerce=True,
        strict=False,
    )


@dataclass
class PipelineOutputData:
    # TODO: Fix that on init it inits already an empty participant output data using config.
    subject_id: str
    subject_df_out: pd.DataFrame = field(init=False)
    figure_data_out: dict[str, Figure] = field(default_factory=dict, init=False)
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_pipeline_output_schema)
    status: PipelineStatus = field(default_factory=PipelineStatus, init=False)

    def __post_init__(self):
        self.subject_df_out = pd.DataFrame(
            [{"Subject_ID": self.subject_id, "Processing_Status": self.status.get_as_text()}]
        )

        self.subject_df_out = self.validate_participant_output()

    def validate_participant_output(self) -> pd.DataFrame:
        return self.validation_schema.validate(self.subject_df_out)

    def append_dataframe(
        self, data_in: pd.DataFrame, additional_columns: dict[str, pa.Column]
    ) -> None:
        revised_validation_schema = build_base_pipeline_output_schema(additional_columns)
        data_in_reset = data_in.reset_index(drop=True)

        # Drop columns from data in.

        data_in_reset = data_in_reset.drop(
            columns=["Subject_ID", "Processing_Status"], errors="ignore"
        )

        existing_df = self.subject_df_out
        existing_df_reset = existing_df.reset_index(drop=True)
        data_list = [existing_df_reset, data_in_reset]
        combined_df = pd.concat(data_list, axis=1)

        if "Subject_ID" not in combined_df.columns:
            combined_df.insert(0, "Subject_ID", self.subject_id)

        if not len(combined_df) == 1:
            raise ValueError("Output data must contain exactly one row.")

        self.subject_df_out = revised_validation_schema.validate(combined_df)

    def merge(self, other: "PipelineOutputData") -> "PipelineOutputData":
        merged_output = PipelineOutputData(self.subject_id)
        merged_output.status = self.status.merge(other.status)
        merged_output.validation_schema = pa.DataFrameSchema(
            {**self.validation_schema.columns, **other.validation_schema.columns}
        )
        merged_output.subject_df_out = self.subject_df_out.copy()
        merged_output.append_dataframe(other.subject_df_out, other.validation_schema.columns)
        merged_output.subject_df_out["Processing_Status"] = merged_output.status.get_as_text()
        merged_output.figure_data_out = {**self.figure_data_out, **other.figure_data_out}

        return merged_output

    @classmethod
    def error(cls, subject_id: str, status_in: PipelineStatus) -> Self:
        error_df_out = pd.DataFrame(
            {"Subject_ID": [subject_id], "Processing_Status": [status_in.get_as_text()]}
        )
        result = cls(subject_id)
        result.subject_df_out = error_df_out
        result.figure_data_out = {}
        result.status = status_in

        return result
