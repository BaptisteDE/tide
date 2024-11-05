import pandas as pd
import numpy as np
import datetime as dt
from bigtree import dict_to_tree, levelordergroup_iter
from bigtree.node import node
from typing import TypeVar

T = TypeVar("T", bound=node.Node)


def get_data_col_names_from_root(data_root):
    return [
        [node.get_attr("col_name") for node in node_group]
        for node_group in levelordergroup_iter(data_root)
    ][-1]


def get_data_level_names(data_root, level: str):
    depth_levels = {
        5: {"name": 4, "unit": 3, "bloc": 1, "sub_bloc": 2},
        4: {"name": 3, "unit": 2, "bloc": 1},
        3: {"name": 2, "unit": 1},
        2: {"name": 1},
    }

    max_depth = data_root.max_depth
    if max_depth not in depth_levels:
        raise ValueError(
            f"Unsupported root depth of {max_depth}. Allowed depths are 2 to 5."
        )

    level_indices = depth_levels[max_depth]

    if level not in level_indices:
        raise ValueError(f"Unknown level {level}")

    nodes = [
        [node.name for node in node_group]
        for node_group in levelordergroup_iter(data_root)
    ]

    selected_nodes = nodes[level_indices[level]]

    return set(selected_nodes) if level in {"bloc", "unit"} else selected_nodes


def parse_request_to_col_names(
    data_columns: pd.Index | list[str], request: str = None
) -> list[str]:
    if request is None:
        return list(data_columns)
    else:
        request_parts = request.split("__")

        if not (1 <= len(request_parts) <= 4):
            raise ValueError(
                f"Request '{request}' is malformed. "
                f"Use 'name__unit__bloc' format or a combination of these tags."
            )

        if len(request_parts) == 4:
            return [request] if request in data_columns else []

        return [
            col for col in data_columns if all(part in col for part in request_parts)
        ]


def data_columns_to_tree(columns: pd.Index | list[str]) -> T:
    """
    Parses column names and organizes them in a hierarchical structure.
    Column names must follow the format: "name__unit__bloc__sub_bloc" with tags
    separated by "__". Supported tags are: name, unit, bloc, and sub_bloc.
    Tree depth is automatically determined from the greater number of tags in a
    column name.
    Tags are supposed to be written in the above order.
    If only one tag is given, and tree depth is 4, it will be considered as name
    and the remaining tags will be set to DIMENSIONLESS, OTHER, OTHER

    :param columns: DataFrame columns or list of strings containing names of measured
    data time series. Names should follow the "name__unit__bloc_sub_bloc"
    naming convention
    """

    tag_levels = max(len(col.split("__")) for col in columns)

    if not 1 <= tag_levels <= 4:
        raise ValueError(f"Only up to 4 tags are allowed; found {tag_levels}.")

    parsed_dict = {}
    level_format = {
        1: lambda pt: f"DATA|{pt[0]}",
        2: lambda pt: f"DATA|{pt[1]}|{pt[0]}",
        3: lambda pt: f"DATA|{pt[2]}|{pt[1]}|{pt[0]}",
        4: lambda pt: f"DATA|{pt[2]}|{pt[3]}|{pt[1]}|{pt[0]}",
    }

    for col in columns:
        split_col = col.split("__")
        num_tags = len(split_col)

        pt = tuple(split_col + ["DIMENSIONLESS", "OTHER", "OTHER"][num_tags - 1 : 4])

        parsed_dict[level_format[tag_levels](pt)] = {"col_name": col}

    return dict_to_tree(parsed_dict, sep="|")


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
