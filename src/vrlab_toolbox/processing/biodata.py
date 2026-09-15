import re
from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa

CANONICAL_LABEL_SPELLING = {
    "trigger": "Trigger",
    "eda": "EDA",
    "ecg": "ECG",
    "nseq": "nSeq",
    "markers": "Markers",
}
ACCEPTED_LABEL_PATTERN = re.compile(
    rf"^(?P<base>{'|'.join(re.escape(label) for label in CANONICAL_LABEL_SPELLING)})_?\d*$",
    re.IGNORECASE,
)


def all_columns_are_floats(df: pd.DataFrame) -> bool:
    results = []

    for column_name in df.columns:
        column_is_float: bool = pd.api.types.is_float_dtype(df[column_name])
        results.append(column_is_float)

    return all(results)


raw_bio_data_schema = pa.DataFrameSchema(
    {"time_stamps": pa.Column(float, nullable=False, coerce=True, required=True)},
    coerce=True,
    strict=False,
    checks=[pa.Check(all_columns_are_floats)],
)


@dataclass(frozen=True)
class RawBioData:
    """

    Class which other raw data input inherits from.
    Each child class should then see it its own importing methods and return a raw pd.dataframe
    as validated by RawBioData.

    """

    raw_data: dict[str, pd.DataFrame] = field(
        default_factory=dict
    )  # Different dataframes at potentially different Hz

    def __post_init__(self):
        validated_data: dict[str, pd.DataFrame] = {}
        for label, df in self.raw_data.items():
            normalized_cols_df = self.normalize_data_labels(df)
            validated_data[label] = raw_bio_data_schema.validate(normalized_cols_df)

        object.__setattr__(self, "raw_data", validated_data)

    def __getitem__(self, key: str) -> pd.DataFrame:
        return self.raw_data[key]

    def normalize_data_labels(self, df_in: pd.DataFrame) -> pd.DataFrame:
        df_out = df_in.copy()

        for col_name in df_in.columns:
            if col_name == "time_stamps":
                continue
            match = ACCEPTED_LABEL_PATTERN.match(col_name)
            if match is None:
                raise ValueError(
                    f"Column {col_name!r} doesn't match accepted labels "
                    f"{sorted(CANONICAL_LABEL_SPELLING)}"
                )
            # TODO: Cleanup lower case: refactor everything to lower case moving forwards
            canonical_name = CANONICAL_LABEL_SPELLING[match.group("base").lower()]
            df_out.rename(columns={col_name: canonical_name}, inplace=True)

        return df_out
