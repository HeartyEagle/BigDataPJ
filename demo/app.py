"""Streamlit demo entry.

成员 6 主要维护本文件：
1. 从 results/profiles 读取统计文件做首页和统计图表。
2. 从 data/cleaned 读取清洗后的时间序列数据。
3. 从 results/anomalies 读取异常结果并标红异常点。
4. 从 results/performance 读取性能测试结果做对比。

本 Demo 只负责展示，不重新计算统计或异常检测结果。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROFILES = ROOT / "results" / "profiles"
ANOMALIES = ROOT / "results" / "anomalies"
PERFORMANCE = ROOT / "results" / "performance"

CLEANED_METRICS = DATA / "cleaned" / "metrics_cleaned.csv"
PERFORMANCE_REPORT = PERFORMANCE / "performance_report.csv"

METRICS_COLUMNS = ["timestamp", "cmdb_id", "kpi_name", "value"]
ANOMALY_COLUMNS = [
    "timestamp",
    "cmdb_id",
    "kpi_name",
    "value",
    "method",
    "is_anomaly",
    "score",
    "threshold_low",
    "threshold_high",
]
PERFORMANCE_COLUMNS = [
    "method",
    "server_num",
    "series_count",
    "data_count",
    "runtime_sec",
    "throughput",
]


st.set_page_config(page_title="时间序列异常检测", layout="wide")


def format_number(value: object) -> str:
    """Format metric values for Streamlit cards."""

    if value is None or value == "":
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if np.isnan(number):
        return "-"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    """Return whether a DataFrame contains all required columns."""

    return all(column in df.columns for column in columns)


@st.cache_data(ttl=30, show_spinner=False)
def load_json(path_text: str) -> dict:
    """Load a JSON file. Missing or invalid files return an empty dict."""

    path = Path(path_text)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@st.cache_data(ttl=30, show_spinner=False)
def load_csv(path_text: str) -> pd.DataFrame:
    """Load a CSV file. Missing or invalid files return an empty DataFrame."""

    path = Path(path_text)
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def normalize_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize cleaned metric data for plotting."""

    if df.empty or not has_columns(df, METRICS_COLUMNS):
        return pd.DataFrame(columns=METRICS_COLUMNS)

    normalized = df.loc[:, METRICS_COLUMNS].copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], errors="coerce")
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    normalized["cmdb_id"] = normalized["cmdb_id"].astype(str)
    normalized["kpi_name"] = normalized["kpi_name"].astype(str)
    normalized = normalized.dropna(subset=METRICS_COLUMNS)
    return normalized.sort_values(["cmdb_id", "kpi_name", "timestamp"])


def normalize_anomalies(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize anomaly result data and drop repeated Hadoop header rows."""

    if df.empty or not has_columns(df, ANOMALY_COLUMNS):
        return pd.DataFrame(columns=ANOMALY_COLUMNS)

    normalized = df.loc[:, ANOMALY_COLUMNS].copy()
    normalized = normalized[normalized["timestamp"].astype(str) != "timestamp"]
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], errors="coerce")
    for column in ["value", "is_anomaly", "score", "threshold_low", "threshold_high"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized[["threshold_low", "threshold_high"]] = normalized[["threshold_low", "threshold_high"]].replace(
        [np.inf, -np.inf], np.nan
    )
    normalized["cmdb_id"] = normalized["cmdb_id"].astype(str)
    normalized["kpi_name"] = normalized["kpi_name"].astype(str)
    normalized["method"] = normalized["method"].astype(str)
    normalized = normalized.dropna(subset=["timestamp", "cmdb_id", "kpi_name", "value", "method"])
    normalized["is_anomaly"] = normalized["is_anomaly"].fillna(0).astype(int)
    return normalized.sort_values(["method", "cmdb_id", "kpi_name", "timestamp"])


def add_series_label(df: pd.DataFrame) -> pd.DataFrame:
    """Add a human-readable series label."""

    if df.empty or not has_columns(df, ["cmdb_id", "kpi_name"]):
        return df.copy()
    labeled = df.copy()
    labeled["series_label"] = labeled["cmdb_id"].astype(str) + " | " + labeled["kpi_name"].astype(str)
    return labeled


@st.cache_data(ttl=30, show_spinner=False)
def load_hadoop_parts(directory_text: str) -> pd.DataFrame:
    """Load Hadoop Streaming part-* files and filter repeated header rows."""

    directory = Path(directory_text)
    if not directory.exists():
        return pd.DataFrame(columns=ANOMALY_COLUMNS)

    frames: list[pd.DataFrame] = []
    for part_file in sorted(directory.glob("part-*")):
        if not part_file.is_file():
            continue
        try:
            frame = pd.read_csv(part_file)
        except Exception:
            continue
        if has_columns(frame, ANOMALY_COLUMNS):
            frames.append(frame.loc[:, ANOMALY_COLUMNS])

    if not frames:
        return pd.DataFrame(columns=ANOMALY_COLUMNS)
    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=30, show_spinner=False)
def load_anomaly_files(directory_text: str) -> pd.DataFrame:
    """Load local anomaly_*.csv files and Hadoop part-* files."""

    directory = Path(directory_text)
    frames: list[pd.DataFrame] = []

    if directory.exists():
        for anomaly_file in sorted(directory.glob("anomaly_*.csv")):
            try:
                frame = pd.read_csv(anomaly_file)
            except Exception:
                continue
            if has_columns(frame, ANOMALY_COLUMNS):
                frames.append(frame.loc[:, ANOMALY_COLUMNS])

    hadoop_frame = load_hadoop_parts(str(directory / "hadoop_iqr"))
    if not hadoop_frame.empty and has_columns(hadoop_frame, ANOMALY_COLUMNS):
        frames.append(hadoop_frame.loc[:, ANOMALY_COLUMNS])

    if not frames:
        return pd.DataFrame(columns=ANOMALY_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def render_project_overview() -> None:
    """Render the project overview tab."""

    st.subheader("项目概览")
    overview = load_json(str(PROFILES / "data_overview.json"))

    if not overview:
        st.info("还没有统计结果，请先运行：`python -m src.preprocessing.build_profiles`。")
        return

    metric_items = [
        ("记录数", overview.get("record_count")),
        ("时间序列数", overview.get("series_count")),
        ("监控对象数", overview.get("cmdb_count")),
        ("KPI 数", overview.get("kpi_count")),
        ("采样频率", f"{overview.get('sampling_interval_sec', '-')} 秒"),
    ]

    columns = st.columns(len(metric_items))
    for column, (label, value) in zip(columns, metric_items):
        column.metric(label, format_number(value) if label != "采样频率" else str(value))

    st.markdown("#### 时间范围")
    time_columns = st.columns(2)
    time_columns[0].write(f"开始时间：`{overview.get('start_time', '-')}`")
    time_columns[1].write(f"结束时间：`{overview.get('end_time', '-')}`")

    st.markdown("#### 项目处理流程")
    st.code(
        "原始监控数据 -> 数据清洗 -> 时间序列构造 -> 异常检测 -> 结果汇总 -> Demo 可视化",
        language="text",
    )


def render_data_statistics() -> None:
    """Render the data statistics tab."""

    st.subheader("数据统计")

    kpi = load_csv(str(PROFILES / "kpi_distribution.csv"))
    missing = load_csv(str(PROFILES / "missing_topn.csv"))
    profile = load_csv(str(PROFILES / "series_profile.csv"))

    if kpi.empty and missing.empty and profile.empty:
        st.info("暂无统计画像文件，请先运行：`python -m src.preprocessing.build_profiles`。")
        return

    if not kpi.empty and has_columns(kpi, ["kpi_name", "record_count"]):
        st.markdown("#### KPI 分布")
        kpi_plot = kpi.sort_values("record_count", ascending=False).head(30)
        fig = px.bar(kpi_plot, x="kpi_name", y="record_count", title="Top 30 KPI 记录数")
        fig.update_layout(xaxis_title="KPI", yaxis_title="记录数")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("缺少 `kpi_distribution.csv` 或字段不完整，无法展示 KPI 分布。")

    left, right = st.columns(2)

    with left:
        if not missing.empty and has_columns(missing, ["cmdb_id", "kpi_name", "missing_rate"]):
            st.markdown("#### 缺失率 Top-N")
            missing_plot = add_series_label(missing).sort_values("missing_rate", ascending=False).head(10)
            fig = px.bar(
                missing_plot.sort_values("missing_rate"),
                x="missing_rate",
                y="series_label",
                orientation="h",
                title="缺失率 Top 10",
            )
            fig.update_layout(xaxis_title="缺失率", yaxis_title="时间序列")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无缺失率统计文件。")

    with right:
        if not profile.empty and has_columns(profile, ["count"]):
            st.markdown("#### 序列长度分布")
            fig = px.histogram(profile, x="count", nbins=30, title="时间序列点数分布")
            fig.update_layout(xaxis_title="序列点数", yaxis_title="序列数量")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无序列画像文件。")

    if not profile.empty:
        st.markdown("#### 序列画像样例")
        st.dataframe(profile.head(50), use_container_width=True)


def render_series_browser(metrics: pd.DataFrame) -> None:
    """Render the cleaned time-series browser tab."""

    st.subheader("时间序列浏览")

    if metrics.empty:
        st.info("暂无清洗数据，请先生成 `data/cleaned/metrics_cleaned.csv`。")
        return

    metrics = add_series_label(metrics)
    series_options = sorted(metrics["series_label"].dropna().unique())
    if not series_options:
        st.info("清洗数据中没有可展示的时间序列。")
        return

    selected_series = st.selectbox("选择时间序列", series_options, key="series_browser_select")
    selected = metrics.loc[metrics["series_label"] == selected_series].sort_values("timestamp")

    fig = px.line(selected, x="timestamp", y="value", title=f"原始时间序列：{selected_series}")
    fig.update_layout(xaxis_title="时间", yaxis_title="指标值")
    st.plotly_chart(fig, use_container_width=True)

    st.caption(f"当前序列共有 {len(selected):,} 个点。")
    st.dataframe(selected[METRICS_COLUMNS].head(100), use_container_width=True)


def build_anomaly_figure(series: pd.DataFrame, title: str) -> go.Figure:
    """Build a line chart with red anomaly points and threshold lines."""

    series = series.sort_values("timestamp")
    anomalies = series.loc[series["is_anomaly"] > 0]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=series["timestamp"],
            y=series["value"],
            mode="lines",
            name="原始曲线",
            line={"color": "#1f77b4"},
        )
    )
    if not anomalies.empty:
        fig.add_trace(
            go.Scatter(
                x=anomalies["timestamp"],
                y=anomalies["value"],
                mode="markers",
                name="异常点",
                marker={"color": "red", "size": 8},
            )
        )

    for column, name, color in [
        ("threshold_low", "下阈值", "#ff7f0e"),
        ("threshold_high", "上阈值", "#2ca02c"),
    ]:
        threshold = series[column].dropna()
        if threshold.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=series["timestamp"],
                y=series[column],
                mode="lines",
                name=name,
                line={"dash": "dash", "color": color},
            )
        )

    fig.update_layout(title=title, xaxis_title="时间", yaxis_title="指标值", hovermode="x unified")
    return fig


def render_anomaly_view(anomalies: pd.DataFrame) -> None:
    """Render the anomaly detection visualization tab."""

    st.subheader("异常检测展示")

    if anomalies.empty:
        st.info("还没有异常结果，请先运行：`python -m src.algorithms.baseline --method all`。")
        return

    anomalies = add_series_label(anomalies)
    methods = sorted(anomalies["method"].dropna().unique())
    if not methods:
        st.info("异常结果中没有可用算法名称。")
        return

    left, right = st.columns([1, 2])
    selected_method = left.selectbox("选择算法", methods)
    method_data = anomalies.loc[anomalies["method"] == selected_method]

    series_options = sorted(method_data["series_label"].dropna().unique())
    if not series_options:
        st.info("当前算法没有可展示的时间序列。")
        return
    selected_series = right.selectbox("选择时间序列", series_options, key="anomaly_series_select")

    selected = method_data.loc[method_data["series_label"] == selected_series]
    anomaly_count = int(selected["is_anomaly"].sum())
    total_count = len(selected)

    metric_cols = st.columns(3)
    metric_cols[0].metric("算法", selected_method)
    metric_cols[1].metric("当前序列点数", f"{total_count:,}")
    metric_cols[2].metric("异常点数", f"{anomaly_count:,}")

    fig = build_anomaly_figure(selected, f"{selected_method} 异常检测：{selected_series}")
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### 异常点列表")
    anomaly_points = selected.loc[selected["is_anomaly"] > 0, ANOMALY_COLUMNS]
    if anomaly_points.empty:
        st.info("当前序列没有检测到异常点。")
    else:
        st.dataframe(anomaly_points.head(100), use_container_width=True)


def render_algorithm_and_performance(anomalies: pd.DataFrame) -> None:
    """Render algorithm summary and performance comparison tab."""

    st.subheader("算法与性能对比")

    if anomalies.empty:
        st.info("暂无异常结果，无法展示算法对比。")
    else:
        anomalies = add_series_label(anomalies)
        anomalies["is_anomaly"] = pd.to_numeric(anomalies["is_anomaly"], errors="coerce").fillna(0).astype(int)

        point_summary = anomalies.groupby("method", as_index=False).agg(
            total_points=("is_anomaly", "size"),
            anomaly_points=("is_anomaly", "sum"),
        )
        series_summary = (
            anomalies.loc[anomalies["is_anomaly"] > 0, ["method", "series_label"]]
            .drop_duplicates()
            .groupby("method")
            .size()
            .reset_index(name="anomaly_series")
        )
        summary = point_summary.merge(series_summary, on="method", how="left")
        summary["anomaly_series"] = summary["anomaly_series"].fillna(0).astype(int)
        summary["anomaly_rate"] = summary["anomaly_points"] / summary["total_points"].replace(0, np.nan)

        st.markdown("#### 异常检测结果汇总")
        chart_cols = st.columns(2)
        with chart_cols[0]:
            fig = px.bar(summary, x="method", y="anomaly_points", title="各算法异常点数量")
            fig.update_layout(xaxis_title="算法", yaxis_title="异常点数")
            st.plotly_chart(fig, use_container_width=True)
        with chart_cols[1]:
            fig = px.bar(summary, x="method", y="anomaly_series", title="各算法异常序列数量")
            fig.update_layout(xaxis_title="算法", yaxis_title="异常序列数")
            st.plotly_chart(fig, use_container_width=True)
        st.dataframe(summary, use_container_width=True)

    performance = load_csv(str(PERFORMANCE_REPORT))
    if performance.empty or not has_columns(performance, PERFORMANCE_COLUMNS):
        st.info("暂无性能测试结果。成员 5 生成 `results/performance/performance_report.csv` 后会在这里展示。")
        return

    performance = performance.loc[:, PERFORMANCE_COLUMNS].copy()
    performance["runtime_sec"] = pd.to_numeric(performance["runtime_sec"], errors="coerce")
    performance["throughput"] = pd.to_numeric(performance["throughput"], errors="coerce")
    performance["server_num"] = performance["server_num"].astype(str)

    st.markdown("#### 单机 / Hadoop 性能对比")
    perf_cols = st.columns(2)
    with perf_cols[0]:
        fig = px.bar(
            performance,
            x="method",
            y="runtime_sec",
            color="server_num",
            barmode="group",
            title="运行时间对比",
        )
        fig.update_layout(xaxis_title="算法", yaxis_title="运行时间（秒）", legend_title="服务器数")
        st.plotly_chart(fig, use_container_width=True)
    with perf_cols[1]:
        fig = px.bar(
            performance,
            x="method",
            y="throughput",
            color="server_num",
            barmode="group",
            title="吞吐量对比",
        )
        fig.update_layout(xaxis_title="算法", yaxis_title="吞吐量", legend_title="服务器数")
        st.plotly_chart(fig, use_container_width=True)

    st.dataframe(performance, use_container_width=True)


def main() -> None:
    """Render the Streamlit app."""

    st.title("时间序列异常检测 Demo")
    st.caption("面向运维监控指标的时间序列异常检测与 Hadoop 分布式处理展示")

    metrics = normalize_metrics(load_csv(str(CLEANED_METRICS)))
    anomalies = normalize_anomalies(load_anomaly_files(str(ANOMALIES)))

    tabs = st.tabs(["项目概览", "数据统计", "时间序列浏览", "异常检测展示", "算法与性能对比"])

    with tabs[0]:
        render_project_overview()
    with tabs[1]:
        render_data_statistics()
    with tabs[2]:
        render_series_browser(metrics)
    with tabs[3]:
        render_anomaly_view(anomalies)
    with tabs[4]:
        render_algorithm_and_performance(anomalies)


if __name__ == "__main__":
    main()
