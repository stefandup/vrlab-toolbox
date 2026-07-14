from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pandera.pandas as pa


def build_base_bids_events_schema(
    additional_columns: dict[str, pa.Column] | None = None,
) -> pa.DataFrameSchema:
    """Build a BIDS-compatible events schema.

    Use this as the base schema for any events.tsv-style output. The schema always
    requires valid BIDS timing columns: finite numeric `onset` values and finite,
    non-negative numeric `duration` values.

    Pass `additional_columns` to extend the schema for pipeline-specific outputs
    while preserving the required BIDS columns.

    Example:
        class CraneEventsOutput:
            validation_schema = build_bids_events_schema(
                {
                    "trial_type": pa.Column(pd.StringDtype(), nullable=False, coerce=True),
                    "response_time": pa.Column(pd.Float64Dtype(), nullable=True, coerce=True),
                }
            )
    """

    return pa.DataFrameSchema(
        {
            "onset": pa.Column(
                pd.Float64Dtype(),
                checks=pa.Check(
                    lambda s: np.isfinite(s).all(),
                    error="onsets must contain finite numeric values",
                ),
                nullable=False,
                coerce=True,
                required=True,
            ),
            "duration": pa.Column(
                pd.Float64Dtype(),
                checks=[
                    pa.Check.ge(0),
                    pa.Check(
                        lambda s: np.isfinite(s).all(), error="duration must contain finite numbers"
                    ),
                ],
                nullable=False,
                coerce=True,
                required=True,
            ),
            **(additional_columns or {}),
        },
        coerce=True,
        strict=False,
    )


@dataclass
class BidsEventsData:
    events_df: pd.DataFrame = field(init=False)
    additional_columns: dict[str, pa.Column] = field(default_factory=dict, init=False)
    validation_schema: pa.DataFrameSchema = field(default_factory=build_base_bids_events_schema)

    def __post_init__(self):
        self.events_df = pd.DataFrame(
            {"onset": pd.Series(dtype="Float64"), "duration": pd.Series(dtype="Float64")}
        )

        self.validation_schema = build_base_bids_events_schema(self.additional_columns)
        self.events_df = self.validation_schema.validate(self.events_df)

    def append_dataframe(
        self, df_in: pd.DataFrame, additional_columns: dict[str, pa.Column] | None = None
    ) -> None:
        additional_columns = additional_columns or {}
        self.validation_schema = build_base_bids_events_schema(
            {**self.additional_columns, **additional_columns}
        )
        df_in_reset = df_in.reset_index(drop=True)

        exisiting_df = self.events_df
        exisiting_df_reset = exisiting_df.reset_index(drop=True)
        data_list = [df_in_reset, exisiting_df_reset]
        data_list = [data for data in data_list if not data.empty]

        if not data_list:
            raise ValueError("Cannot concatenate empty dataset.")

        combined_df = pd.concat(data_list, axis=0, ignore_index=True)

        self.events_df = self.validation_schema.validate(combined_df)

    @classmethod
    def from_csv(cls, csv_fn: Path, delimiter: str = "\t"):
        new_df = pd.read_csv(csv_fn, delimiter=delimiter)
        result = cls()
        result.append_dataframe(new_df)

        return result
