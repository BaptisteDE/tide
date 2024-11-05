import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from tide.utils import check_and_return_dt_index_df


def plot_gaps_heatmap(
    data: pd.Series | pd.DataFrame,
    time_step: str | pd.Timedelta | dt.timedelta = None,
    title: str = None,
):
    """
    Generates a heatmap that visualizes data availability over time as a percentage.

    Parameters
    ----------
    data : pd.Series or pd.DataFrame
        Time-indexed data to analyze for gaps. Non-NaN values are considered
        as available data, and NaN values represent gaps. Each column
        (if DataFrame) will be treated independently.
    time_step : str, pd.Timedelta, or datetime.timedelta, optional
        The resampling frequency for aggregating data availability.
         If specified, the availability is calculated as the mean percentage within
         each time interval.
        Examples: '1d' (daily), 'h' (hourly), or pd.Timedelta('15min')
        for 15-minute intervals.
    title : str, optional
        The title for the heatmap.
    """

    data = check_and_return_dt_index_df(data)
    zero_one_df = (~data.isna()).astype(int) * 100
    if time_step is not None:
        zero_one_df = zero_one_df.resample(time_step).mean()

    fig = px.imshow(
        zero_one_df.T,
        title=title,
        color_continuous_scale="RdBu",
        origin="lower",
        labels={"x": ""},
    )

    fig.update_layout(coloraxis_colorbar=dict(title="% of available data"))

    return fig

def plot(
    data: pd.Series | pd.DataFrame,
    title: str = None,
    y_axis_labels: [str] = None,
    axis_space: float = 0.03,
    y_axis_dict: dict[str, str] = None,
    mode_dict: dict[str, str] = None,
    y_title_standoff: int | float = 5,
    markers_opacity: float = 0.5,
    lines_width: float = 2.0,
):
    """
    Generates a Plotly line plot with support for multiple y-axes.

    This function plots time series data with one or more y-axes.
    Each column in the input `data` can be assigned to a specific y-axis.
    Primary y-axis labels are displayed on the left, while additional y-axes
    are positioned on the right with configurable spacing.

    Parameters:
    ----------
    data : pd.Series | pd.DataFrame
        The input time series data to be plotted. Each column will be represented
        by a separate line.
    title : str, optional
        Title of the plot. Defaults to "Gaps plot".
    y_axis_labels : list[str], optional
        List of labels for the y-axes. The first label corresponds to the left y-axis;
        additional labels correspond to the right y-axes in the order they appear.
    axis_space : float, optional
        Space between consecutive right y-axes. Defaults to 0.03.
    y_axis_dict : dict[str, str], optional
        Dictionary mapping each column in `data` to a y-axis. Keys are column names,
         values are y-axis identifiers (e.g., "y", "y2", "y3").
         Defaults to assigning all columns to "y".
    mode_dict : dict[str, str], optional
        Dictionary mapping each column in `data` to a Plotly mode
        (e.g., "lines", "markers"). If not specified, defaults to "lines" for
        all columns.
    y_title_standoff : int | float, optional
        Distance of the y-axis titles from the axis line. A smaller value moves
        titles closer to the axis. Defaults to 5.
    markers_opacity : float, optional
        Opacity of the markers in the plot. Ranges from 0 to 1. Defaults to 0.5.
    lines_width : float, optional
        Width of the lines in the plot. Defaults to 2.0.
        """

    data = check_and_return_dt_index_df(data)
    if y_axis_dict is None:
        y_axis_dict = {col: "y" for col in data.columns}

    fig = go.Figure()
    for i, col in enumerate(data.columns):
        fig.add_scattergl(
            x=data.index,
            y=data[col],
            name=f"{col}",
            mode=mode_dict[col] if mode_dict is not None else None,
            line=dict(width=lines_width),
            marker=dict(opacity=markers_opacity),
            yaxis=y_axis_dict[col],
        )

    layout_dict = {
        "legend": dict(orientation="h", yanchor="top", y=-0.1, xanchor="center", x=0.5),
        "title": title,
        "yaxis": dict(
            title=y_axis_labels[0] if y_axis_labels is not None else None,
            side="left",
            title_standoff=y_title_standoff,
        ),
    }

    nb_right_y_axis = len(set(y_axis_dict.values())) - 1
    x_right_space = 1 - axis_space * nb_right_y_axis
    fig.update_xaxes(domain=(0, x_right_space))

    for i in range(nb_right_y_axis):
        layout_dict[f"yaxis{i + 2}"] = dict(
            title=y_axis_labels[1 + i] if y_axis_labels is not None else None,
            overlaying="y",
            side="right",
            position=x_right_space + i * axis_space,
            title_standoff=y_title_standoff,
        )

    fig.update_layout(layout_dict)

    return fig