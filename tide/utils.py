import pandas as pd
import numpy as np
import datetime as dt
from bigtree import list_to_tree


def parse_columns(columns: pd.Index | list[str]) -> list[tuple[str, str, str]]:
    """
    Parses a DataFrame columns or a list of strings.
    Columns names must be formatted in the following way: "name__unit__bloc"
    Tags are separated by a double underscore "__"
    Only unit and bloc tags are allowed. More tags will raise an error
    If only one tag is given, it will be considered as unit tag. The bloc tag
    will be set to "OTHER".
    If no tag is given unit tag will be set to "DIMENSIONLESS", bloc tag will be set to
    "OTHER"

    :param columns: DataFrame columns or list of strings containing names of measured
    data time series. Names should follow the "name__unit__bloc" naming convention
    """

    parsed_list = []

    for col in columns:
        split_col = col.split("__")
        num_tags = len(split_col)

        if num_tags == 1:
            parsed_tuple = (split_col[0], "DIMENSIONLESS", "OTHER")
        elif num_tags == 2:
            parsed_tuple = (split_col[0], split_col[1], "OTHER")
        elif num_tags == 3:
            parsed_tuple = tuple(split_col)
        else:
            raise ValueError(f"Too many tags; last tag '{split_col[-1]}' is not valid")

        parsed_list.append(parsed_tuple)

    return parsed_list


def columns_to_tree(columns: pd.Index | list[str]):
    parsed_columns = parse_columns(columns)
    parsed_to_str = [f"DATA|{p[2]}|{p[1]}|{p[0]}" for p in parsed_columns]
    return list_to_tree(parsed_to_str, sep="|")


def check_and_return_dt_index_df(X: pd.Series | pd.DataFrame) -> pd.DataFrame:
    if not (isinstance(X, pd.Series) or isinstance(X, pd.DataFrame)):
        raise ValueError(
            f"Invalid X data, was expected an instance of pandas Dataframe "
            f"or Pandas Series. Got {type(X)}"
        )
    if not isinstance(X.index, pd.DatetimeIndex):
        raise ValueError("X index is not a pandas DateTime index")

    return X.to_frame() if isinstance(X, pd.Series) else X


def get_data_blocks(
    data: pd.Series | pd.DataFrame,
    is_null: bool = False,
    cols: str | list[str] = None,
    lower_td_threshold: str | dt.timedelta = None,
    upper_td_threshold: str | dt.timedelta = None,
    lower_threshold_inclusive: bool = True,
    upper_threshold_inclusive: bool = True,
    return_combination=True,
):
    """
    Identifies groups of valid data if is_null = False, or groups of nan if
    is_null = True (gaps in measurements).
    Returns them in a dictionary as list of DateTimeIndex. The keys values are
    data columns (or name if data is a Series).
    The groups can be filtered using lower_dt_threshold or higher_dt_threshold.
    The argument return indicates if an additional key must be set to the dictionary
    to account for all data presence.

    Parameters
    ----------
    data : pd.Series or pd.DataFrame
        The input time series data with a DateTime index. NaN values are
        considered gaps.
    is_null : Bool, default False
        Whether to return groups with valid data, or groups of Nan values
        (is_null = True)
    cols : str or list[str], optional
        The columns in the DataFrame for which to detect gaps. If None (default), all
        columns are considered.
    lower_td_threshold : str or timedelta, optional
        The minimum duration of a period for it to be considered valid.
        Can be passed as a string (e.g., '1d' for one day) or a `timedelta`.
        If None, no threshold is applied, NaN values are considered gaps.
    upper_td_threshold : str or timedelta, optional
        The maximum duration of a period for it to be considered valid.
        Can be passed as a string (e.g., '1d' for one day) or a `timedelta`.
        If None, no threshold is applied, NaN values are considered gaps.
    lower_threshold_inclusive : bool, optional
        Include the gaps of exactly lower_td_threshold duration
    upper_threshold_inclusive : bool, optional
        Include the gaps of exactly upper_td_threshold duration
    return_combination : bool, optional
        If True (default), a combination column is created that checks for NaNs
        across all columns in the DataFrame. Gaps in this combination column represent
        rows where NaNs are present in any of the columns.

    Returns
    -------
    dict[str, list[pd.DatetimeIndex]]
        A dictionary where the keys are the column names (or "combination" if
        `return_combination` is True) and the values are lists of `DatetimeIndex`
        objects.
        Each `DatetimeIndex` represents a group of one or several consecutive
        timestamps where the values in the corresponding column were NaN and
        exceeded the gap threshold.

    """

    data = check_and_return_dt_index_df(data)

    if isinstance(cols, str):
        cols = [cols]
    elif cols is None:
        cols = list(data.columns)

    if isinstance(lower_td_threshold, str):
        lower_td_threshold = pd.to_timedelta(lower_td_threshold)
    elif lower_td_threshold is None:
        lower_td_threshold = pd.to_timedelta(0)

    if isinstance(upper_td_threshold, str):
        upper_td_threshold = pd.to_timedelta(upper_td_threshold)
    elif upper_td_threshold is None:
        upper_td_threshold = pd.Timedelta.max

    freq = get_freq_delta_or_min_time_interval(data)
    # If data index has no frequency, a frequency based on minimum
    # timedelta is set.
    df = data.asfreq(freq)

    df = df.isnull() if is_null else ~df.isnull()

    if return_combination:
        df["combination"] = df.any(axis=1)
        cols += ["combination"]

    def is_valid_block(group, lgt, hgt):
        new_block = pd.DatetimeIndex(group)
        block_duration = new_block.max() - new_block.min() + freq

        lower_check = (
            block_duration >= lgt if lower_threshold_inclusive else block_duration > lgt
        )
        upper_check = (
            block_duration <= hgt if upper_threshold_inclusive else block_duration < hgt
        )

        return lower_check and upper_check

    def finalize_block(current_group):
        # For indexes where frequency has been imposed,
        # Get back to the original data index
        current_group = [ts for ts in current_group if ts in data.index]
        new_block_index = pd.DatetimeIndex(current_group)
        new_block_index.freq = new_block_index.inferred_freq
        return new_block_index

    block_dict = {}
    for col in cols:
        groups = []
        current_group = []

        for timestamp in df.index:
            if df.loc[timestamp, col]:
                current_group.append(timestamp)
            else:
                if current_group and is_valid_block(
                    current_group, lower_td_threshold, upper_td_threshold
                ):
                    groups.append(finalize_block(current_group))
                current_group = []

        # Append the last group if it exists and is valid
        if current_group and is_valid_block(
            current_group, lower_td_threshold, upper_td_threshold
        ):
            groups.append(finalize_block(current_group))

        block_dict[col] = groups

    return block_dict


def get_freq_delta_or_min_time_interval(df: pd.Series | pd.DataFrame):
    df = check_and_return_dt_index_df(df)
    freq = df.index.inferred_freq
    if freq:
        freq = pd.to_timedelta("1" + freq) if freq.isalpha() else pd.to_timedelta(freq)
    else:
        freq = df.index.to_frame().diff().min()[0]

    return freq


def get_outer_timestamps(idx: pd.DatetimeIndex, ref_index: pd.DatetimeIndex):
    try:
        out_start = ref_index[ref_index < idx[0]][-1]
    except IndexError:
        out_start = ref_index[0]

    try:
        out_end = ref_index[ref_index > idx[-1]][0]
    except IndexError:
        out_end = ref_index[-1]

    return out_start, out_end


def get_gaps_mask(
    data: pd.Series, operator: str, size: str | pd.Timedelta | dt.timedelta = None
):
    """
    Returns np boolean array of shape (len(data),) with True if an entry of data is
    part of a gap of size less han or equal to, LTE, less than LT, greater than or
     equal to GTE, greater than GT the specified size.
    :param data: Pandas Series with DatetimeIndex
    :param operator : str the operator for the test.
    Must be one of 'GTE', 'GT', 'LT', 'LTE'.
    Will raise an error otherwise
    :param size: str | timedelta : size threshold of the gap
    :return:
    """

    data = check_and_return_dt_index_df(data)
    size = pd.to_timedelta(size) if isinstance(size, str) else size

    if operator == "GTE":
        gaps = get_data_blocks(
            data, is_null=True, lower_td_threshold=size, return_combination=False
        )
    elif operator == "GT":
        gaps = get_data_blocks(
            data,
            is_null=True,
            lower_td_threshold=size,
            return_combination=False,
            lower_threshold_inclusive=False,
        )

    elif operator == "LTE":
        gaps = get_data_blocks(
            data, is_null=True, upper_td_threshold=size, return_combination=False
        )

    elif operator == "LT":
        gaps = get_data_blocks(
            data,
            is_null=True,
            upper_td_threshold=size,
            return_combination=False,
            upper_threshold_inclusive=False,
        )

    else:
        raise ValueError(
            f"invalid operator {operator}, choose one of 'LTE', 'LT', 'GTE', 'GT'"
        )

    gaps_idx = gaps[data.columns[0]]

    if gaps_idx:
        if len(gaps_idx) > 1:
            final_index = gaps_idx[0]
            for idx in gaps_idx[1:]:
                final_index = final_index.union(idx)
        else:
            final_index = gaps_idx[0]
    else:
        final_index = pd.DatetimeIndex([])

    return np.isin(data.index, final_index)


def timedelta_to_int(td: int | str | dt.timedelta, df):
    if isinstance(td, int):
        return td
    else:
        if isinstance(td, str):
            td = pd.to_timedelta(td)
        return abs(int(td / df.index.freq))


def validate_odd_param(param_name, param_value):
    if isinstance(param_value, int) and param_value % 2 == 0:
        raise ValueError(
            f"{param_name}={param_value} is not valid, it must be an odd number"
        )


def process_stl_odd_args(param_name, X, stl_kwargs):
    param_value = stl_kwargs[param_name]
    if isinstance(param_value, int):
        # Is odd already check at init in case of int
        stl_kwargs[param_name] = param_value
    elif param_value is not None:
        processed_value = timedelta_to_int(param_value, X)
        if processed_value % 2 == 0:
            processed_value += 1  # Ensure the value is odd
        stl_kwargs[param_name] = processed_value
