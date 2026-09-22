import pandera.pandas as pa
from pandera import Check


def int_col():
    return pa.Column(
        pa.Int64,
        nullable=True,
        coerce=True,
    )


def float_col():
    return pa.Column(
        float,
        nullable=True,
        coerce=True,
    )


def optional_float_col():
    return pa.Column(float, nullable=True, coerce=True, required=False)


def str_col():
    return pa.Column(
        str,
        nullable=True,
        coerce=True,
    )


def optional_str_col():
    return pa.Column(str, nullable=True, coerce=True, required=False)


def date_col():
    """A python readable datestring"""
    return pa.Column(
        pa.DateTime,
        nullable=True,
        coerce=True,
    )


def checkbox_col():
    """Typical REDCap checkbox export: 0 = unchecked, 1 = checked."""
    return pa.Column(
        pa.Int64,
        nullable=True,
        coerce=True,
        checks=Check.isin([0, 1]),
    )


def complete_col():
    """Typical REDCap form status: 0=incomplete, 1=unverified, 2=complete."""
    return pa.Column(
        pa.Int64,
        nullable=True,
        coerce=True,
        checks=Check.isin([0, 1, 2]),
    )


def likert_col():
    """
    Likert scale: 1 = Strongly disagree, 2 = Disagree, 3 = Neutral, 4 = Agree, 5 = Strongly agree
    """
    return pa.Column(pa.Int64, nullable=True, coerce=True, checks=Check.isin([1, 2, 3, 4, 5]))


def coord_axis_col():
    return pa.Column(float, nullable=True, coerce=True, regex=True)
