import pandera.pandas as pa
import pandas as pd
from dataclasses import dataclass, field

def all_columns_are_floats(df : pd.DataFrame) -> bool:
    results = []

    for column_name in df.columns:
        column_is_float : bool = pd.api.types.is_float_dtype(df[column_name])
        results.append(column_is_float)

    return all(results)

raw_bio_data_schema = pa.DataFrameSchema(
    {
    "time_stamps" : pa.Column(float,nullable=False,coerce=True,required=True)
    }, 
    coerce=True,
    strict=False,
    checks =[
        pa.Check(all_columns_are_floats)
        ]
    )
@dataclass(frozen=True)
class RawBioData:
    '''
    
    Class which other raw data input inherits from. 
    Each child class should then see it its own importing methods and return a raw pd.dataframe
    as validated by RawBioData.
    
    '''
    raw_data : dict[str,pd.DataFrame]  = field(default_factory=dict)# Different dataframes at potentially different Hz

    def __post_init__(self):
        validated_data : dict[str,pd.DataFrame] = {}
        for label,df in self.raw_data.items():
            validated_data[label] = raw_bio_data_schema.validate(df)

        object.__setattr__(self, "raw_data", validated_data)

    def __getitem__(self, key :str) -> pd.DataFrame:
        return self.raw_data[key]