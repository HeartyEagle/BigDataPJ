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
import inspect
import warnings
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
ANALYSIS_PACKAGE = ROOT / "results" / "analysis_package"

CLEANED_METRICS = DATA / "cleaned" / "metrics_cleaned.csv"
PERFORMANCE_REPORTS = [
    PERFORMANCE / "performance_report.csv",
    PERFORMANCE / "full_comparison_report.csv",
]
MAX_DIRECT_ANOMALY_FILE_MB = 200
METRICS_CHUNK_SIZE = 250_000
ANOMALY_CHUNK_SIZE = 250_000
ZERO_SERIES_EPS = 1e-12
DEFAULT_ANALYSIS_PACKAGE_MODE = True

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
FULL_PERFORMANCE_COLUMNS = ["method", "mode", "server_num", "data_count", "anomaly_count", "runtime_sec", "throughput"]
ANALYSIS_METHOD_COLUMNS = ["method", "total_points", "anomaly_points", "anomaly_rate"]
METHOD_HINTS = {
    "iqr": "IQR",
    "ksigma": "K-Sigma",
    "k_sigma": "K-Sigma",
    "k-sigma": "K-Sigma",
    "range": "Range",
    "advanced": "Advanced",
}
ADVANCED_METHOD_KEYS = {"advanced", "rollingrobustzscore", "rollingzscore", "robustzscore"}


st.set_page_config(page_title="时间序列异常检测", layout="wide")


def supports_stretch_width(function: object) -> bool:
    """Return whether this Streamlit version supports width='stretch'."""

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return False
    width_param = signature.parameters.get("width")
    if width_param is None:
        return False
    annotation = str(width_param.annotation)
    default = width_param.default
    return default == "stretch" or "stretch" in annotation or "Width" in annotation


def render_plotly_chart(fig: go.Figure) -> None:
    """Render Plotly charts without triggering Streamlit width deprecation warnings."""

    if supports_stretch_width(st.plotly_chart):
        st.plotly_chart(fig, width="stretch")
    else:
        st.plotly_chart(fig, use_container_width=True)


def render_dataframe(data: object) -> None:
    """Render dataframes full-width across old and new Streamlit versions."""

    if supports_stretch_width(st.dataframe):
        st.dataframe(data, width="stretch")
    else:
        st.dataframe(data, use_container_width=True)


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


def parse_epoch_numeric(values: pd.Series) -> pd.Series:
    """Parse Unix timestamps by normalizing common epoch units to datetime."""

    numeric = pd.to_numeric(values, errors="coerce")
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    abs_values = numeric.abs()
    unit_masks = [
        ("ns", numeric.notna() & abs_values.ge(1e17)),
        ("us", numeric.notna() & abs_values.ge(1e14) & abs_values.lt(1e17)),
        ("ms", numeric.notna() & abs_values.ge(1e11) & abs_values.lt(1e14)),
        ("s", numeric.notna() & abs_values.lt(1e11)),
    ]
    for unit, mask in unit_masks:
        if mask.any():
            parsed.loc[mask] = pd.to_datetime(numeric.loc[mask], unit=unit, errors="coerce")
    return parsed


def repair_1970_epoch_strings(parsed: pd.Series) -> pd.Series:
    """Repair strings created by parsing Unix epoch numbers as nanoseconds."""

    if parsed.empty:
        return parsed
    repaired = parsed.copy()
    mask = repaired.notna() & (repaired.dt.year == 1970)
    if not mask.any():
        return repaired

    epoch_ns = repaired.loc[mask].astype("int64")
    repairable = epoch_ns.ge(1_000_000_000)
    if repairable.any():
        repaired.loc[epoch_ns.index[repairable]] = parse_epoch_numeric(epoch_ns.loc[repairable])
    return repaired


def parse_timestamp(values: pd.Series) -> pd.Series:
    """Parse timestamp values with seconds/ms/us/ns Unix epoch detection."""

    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        return parse_epoch_numeric(numeric)

    text = values.astype("string").str.strip()
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    formats = [
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for timestamp_format in formats:
        mask = parsed.isna() & text.notna() & (text != "")
        if not mask.any():
            break
        candidate = pd.to_datetime(text.loc[mask], format=timestamp_format, errors="coerce")
        valid = candidate.notna()
        parsed.loc[candidate.index[valid]] = candidate.loc[valid]

    mask = parsed.isna() & text.notna() & (text != "")
    if mask.any():
        numeric_text = pd.to_numeric(text.loc[mask], errors="coerce")
        valid_numeric = numeric_text.dropna()
        if not valid_numeric.empty:
            candidate = parse_epoch_numeric(numeric_text)
            valid = candidate.notna()
            parsed.loc[candidate.index[valid]] = candidate.loc[valid]

    mask = parsed.isna() & text.notna() & (text != "")
    if mask.any():
        try:
            parsed.loc[mask] = pd.to_datetime(text.loc[mask], format="mixed", errors="coerce")
        except (TypeError, ValueError):
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="Could not infer format", category=UserWarning)
                parsed.loc[mask] = pd.to_datetime(text.loc[mask], errors="coerce")
    return repair_1970_epoch_strings(parsed)


def normalize_method_name(method: object) -> str:
    """Normalize method labels so file-name hints and CSV values can be matched."""

    return "".join(ch for ch in str(method).lower() if ch.isalnum())


def canonical_method_key(method: object) -> str:
    """Collapse method aliases such as Advanced and Rolling-Robust-ZScore."""

    normalized = normalize_method_name(method)
    if normalized == "ksigma":
        return "ksigma"
    if normalized in ADVANCED_METHOD_KEYS:
        return "advanced"
    return normalized


def infer_method_from_path(path: Path) -> str | None:
    """Infer the algorithm name from common anomaly output paths."""

    text = f"{path.parent.name}_{path.stem}".lower()
    for hint, method in METHOD_HINTS.items():
        if hint in text:
            return method
    return None


def method_matches_path(path: Path, method: str) -> bool:
    inferred = infer_method_from_path(path)
    if inferred is None:
        return True
    return canonical_method_key(inferred) == canonical_method_key(method)


def file_size_mb(path: Path) -> float:
    if not path.exists() or not path.is_file():
        return 0.0
    return path.stat().st_size / 1024 / 1024


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


def first_existing_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


@st.cache_data(ttl=300, show_spinner=True)
def load_metric_series(path_text: str, cmdb_id: str, kpi_name: str) -> pd.DataFrame:
    """Load one time series from the large cleaned metrics CSV in chunks."""

    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return pd.DataFrame(columns=METRICS_COLUMNS)

    frames: list[pd.DataFrame] = []
    try:
        for chunk in pd.read_csv(path, usecols=METRICS_COLUMNS, chunksize=METRICS_CHUNK_SIZE):
            chunk["cmdb_id"] = chunk["cmdb_id"].astype(str)
            chunk["kpi_name"] = chunk["kpi_name"].astype(str)
            selected = chunk[(chunk["cmdb_id"] == cmdb_id) & (chunk["kpi_name"] == kpi_name)]
            if not selected.empty:
                frames.append(selected.loc[:, METRICS_COLUMNS])
    except Exception:
        return pd.DataFrame(columns=METRICS_COLUMNS)

    if not frames:
        return pd.DataFrame(columns=METRICS_COLUMNS)
    return normalize_metrics(pd.concat(frames, ignore_index=True))


def normalize_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize cleaned metric data for plotting."""

    if df.empty or not has_columns(df, METRICS_COLUMNS):
        return pd.DataFrame(columns=METRICS_COLUMNS)

    normalized = df.loc[:, METRICS_COLUMNS].copy()
    normalized["timestamp"] = parse_timestamp(normalized["timestamp"])
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
    normalized["timestamp"] = parse_timestamp(normalized["timestamp"])
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

    if not has_columns(df, ["cmdb_id", "kpi_name"]):
        return df.copy()
    labeled = df.copy()
    labeled["series_label"] = labeled["cmdb_id"].astype(str) + " | " + labeled["kpi_name"].astype(str)
    return labeled


def prepare_series_profile(profile: pd.DataFrame) -> pd.DataFrame:
    """Normalize profile fields used by the Demo filters."""

    if profile.empty or not has_columns(profile, ["cmdb_id", "kpi_name"]):
        return pd.DataFrame()

    normalized = add_series_label(profile)
    for column in ["count", "mean", "std"]:
        if column in normalized.columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized


def zero_constant_series_labels(profile: pd.DataFrame) -> set[str]:
    """Return series labels whose profile indicates all observed values are zero."""

    if profile.empty or not has_columns(profile, ["series_label", "mean", "std"]):
        return set()
    zero_mask = profile["mean"].abs().le(ZERO_SERIES_EPS) & profile["std"].fillna(0).abs().le(ZERO_SERIES_EPS)
    return set(profile.loc[zero_mask, "series_label"].dropna().astype(str))


def filter_zero_constant_series(df: pd.DataFrame, zero_labels: set[str]) -> pd.DataFrame:
    """Filter constant-zero series from a DataFrame with cmdb_id/kpi_name columns."""

    if df.empty or not zero_labels:
        return df
    labeled = add_series_label(df)
    if "series_label" not in labeled.columns:
        return df
    return labeled.loc[~labeled["series_label"].astype(str).isin(zero_labels)].copy()


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


def list_anomaly_csv_files(directory: Path) -> list[Path]:
    """List local anomaly CSV files without reading their content."""

    if not directory.exists():
        return []
    files = list(directory.glob("anomaly_*.csv"))
    files.extend(directory.glob("local_*_full/anomaly_*.csv"))
    return sorted(path for path in files if path.is_file())


@st.cache_data(ttl=30, show_spinner=False)
def load_demo_cases(directory_text: str) -> pd.DataFrame:
    """Load small demo case files produced by local anomaly jobs."""

    directory = Path(directory_text)
    if not directory.exists():
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    demo_case_files = list(directory.glob("demo_cases.csv"))
    demo_case_files.extend(directory.glob("local_*_full/demo_cases.csv"))
    for case_file in sorted(path for path in demo_case_files if path.is_file()):
        frame = load_csv(str(case_file))
        if frame.empty or not has_columns(frame, ["cmdb_id", "kpi_name", "method"]):
            continue
        frames.append(frame.copy())

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def has_full_anomaly_csv(directory: Path, method: str) -> bool:
    """Return whether a method-specific full anomaly CSV is available."""

    return any(file_size_mb(path) > MAX_DIRECT_ANOMALY_FILE_MB for path in list_anomaly_csv_files(directory) if method_matches_path(path, method))


@st.cache_data(ttl=300, show_spinner=True)
def load_anomaly_series_from_full_files(directory_text: str, method: str, cmdb_id: str, kpi_name: str) -> pd.DataFrame:
    """Load one series from method-specific full anomaly CSV files in chunks."""

    directory = Path(directory_text)
    frames: list[pd.DataFrame] = []
    target_method = canonical_method_key(method)

    for anomaly_file in list_anomaly_csv_files(directory):
        if not method_matches_path(anomaly_file, method):
            continue
        if file_size_mb(anomaly_file) <= MAX_DIRECT_ANOMALY_FILE_MB:
            continue

        try:
            chunks = pd.read_csv(anomaly_file, usecols=ANOMALY_COLUMNS, chunksize=ANOMALY_CHUNK_SIZE)
            for chunk in chunks:
                chunk["cmdb_id"] = chunk["cmdb_id"].astype(str)
                chunk["kpi_name"] = chunk["kpi_name"].astype(str)
                chunk["method"] = chunk["method"].astype(str)
                selected = chunk[
                    (chunk["cmdb_id"] == cmdb_id)
                    & (chunk["kpi_name"] == kpi_name)
                    & (chunk["method"].map(canonical_method_key) == target_method)
                ]
                if not selected.empty:
                    frames.append(selected.loc[:, ANOMALY_COLUMNS])
        except Exception:
            continue

    if not frames:
        return pd.DataFrame(columns=ANOMALY_COLUMNS)
    return normalize_anomalies(pd.concat(frames, ignore_index=True))


@st.cache_data(ttl=30, show_spinner=False)
def load_anomaly_files(directory_text: str) -> pd.DataFrame:
    """Load local anomaly_*.csv files and Hadoop part-* files."""

    directory = Path(directory_text)
    frames: list[pd.DataFrame] = []

    package_sample = ANALYSIS_PACKAGE / "anomaly_sample.csv"
    if package_sample.exists():
        try:
            frame = pd.read_csv(package_sample)
        except Exception:
            frame = pd.DataFrame()
        if has_columns(frame, ANOMALY_COLUMNS):
            frames.append(frame.loc[:, ANOMALY_COLUMNS])

    if directory.exists():
        anomaly_files = list(directory.glob("anomaly_*.csv"))
        anomaly_files.extend(directory.glob("local_*_full/anomaly_*.csv"))
        for anomaly_file in sorted(anomaly_files):
            if file_size_mb(anomaly_file) > MAX_DIRECT_ANOMALY_FILE_MB:
                continue
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


@st.cache_data(ttl=30, show_spinner=False)
def load_algorithm_summary() -> pd.DataFrame:
    """Load algorithm-level anomaly summary from the compact analysis package."""

    package_summary = load_csv(str(ANALYSIS_PACKAGE / "anomaly_method_summary.csv"))
    if not package_summary.empty and has_columns(package_summary, ANALYSIS_METHOD_COLUMNS):
        summary = package_summary.copy()
        summary["total_points"] = pd.to_numeric(summary["total_points"], errors="coerce")
        summary["anomaly_points"] = pd.to_numeric(summary["anomaly_points"], errors="coerce")
        summary["anomaly_rate"] = pd.to_numeric(summary["anomaly_rate"], errors="coerce")

        series_topn = load_csv(str(ANALYSIS_PACKAGE / "anomaly_series_topn.csv"))
        if not series_topn.empty and has_columns(series_topn, ["method", "cmdb_id", "kpi_name"]):
            counts = (
                series_topn[["method", "cmdb_id", "kpi_name"]]
                .drop_duplicates()
                .groupby("method")
                .size()
                .reset_index(name="top_anomaly_series")
            )
            summary = summary.merge(counts, on="method", how="left")
        return summary

    frames: list[pd.DataFrame] = []
    for summary_file in sorted(ANOMALIES.glob("local_*_full/*_summary.csv")):
        frame = load_csv(str(summary_file))
        if frame.empty or not has_columns(frame, ["method", "record_count", "anomaly_count", "anomaly_rate"]):
            continue
        frame = frame.rename(columns={"record_count": "total_points", "anomaly_count": "anomaly_points"})
        frames.append(frame)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def available_anomaly_methods(anomalies: pd.DataFrame) -> list[str]:
    """Collect available anomaly methods from summaries, loaded samples and file names."""

    methods: list[str] = []
    summary = load_algorithm_summary()
    if not summary.empty and "method" in summary.columns:
        methods.extend(summary["method"].dropna().astype(str).tolist())
    demo_cases = load_demo_cases(str(ANOMALIES))
    if not demo_cases.empty and "method" in demo_cases.columns:
        methods.extend(demo_cases["method"].dropna().astype(str).tolist())
    if not anomalies.empty and "method" in anomalies.columns:
        methods.extend(anomalies["method"].dropna().astype(str).tolist())
    for anomaly_file in list_anomaly_csv_files(ANOMALIES):
        inferred = infer_method_from_path(anomaly_file)
        if inferred:
            methods.append(inferred)

    unique: dict[str, str] = {}
    for method in methods:
        normalized = canonical_method_key(method)
        if normalized and normalized not in unique:
            unique[normalized] = method
    return sorted(unique.values(), key=str.lower)


@st.cache_data(ttl=30, show_spinner=False)
def load_performance_report() -> pd.DataFrame:
    """Load either the original performance report or the full comparison report."""

    path = first_existing_path(PERFORMANCE_REPORTS)
    if path is None:
        return pd.DataFrame()
    performance = load_csv(str(path))
    if performance.empty:
        return pd.DataFrame()
    if has_columns(performance, PERFORMANCE_COLUMNS):
        return performance.loc[:, PERFORMANCE_COLUMNS].copy()
    if has_columns(performance, FULL_PERFORMANCE_COLUMNS):
        performance = performance.copy()
        performance["series_count"] = np.nan
        return performance.loc[:, ["method", "mode", "server_num", "series_count", "data_count", "runtime_sec", "throughput"]]
    return pd.DataFrame()


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
        render_plotly_chart(fig)
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
            render_plotly_chart(fig)
        else:
            st.info("暂无缺失率统计文件。")

    with right:
        if not profile.empty and has_columns(profile, ["count"]):
            st.markdown("#### 序列长度分布")
            fig = px.histogram(profile, x="count", nbins=30, title="时间序列点数分布")
            fig.update_layout(xaxis_title="序列点数", yaxis_title="序列数量")
            render_plotly_chart(fig)
        else:
            st.info("暂无序列画像文件。")

    if not profile.empty:
        st.markdown("#### 序列画像样例")
        render_dataframe(profile.head(50))


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

    fig = px.line(selected, x="timestamp", y="value", title=f"原始时间序列：{selected_series}", line_shape="hv")
    fig.update_traces(line={"shape": "hv"})
    fig.update_layout(xaxis_title="时间", yaxis_title="指标值", xaxis={"type": "date", "rangeslider": {"visible": False}})
    render_plotly_chart(fig)

    st.caption(f"当前序列共有 {len(selected):,} 个点。")
    render_dataframe(selected[METRICS_COLUMNS].head(100))


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
    render_plotly_chart(fig)

    st.markdown("#### 异常点列表")
    anomaly_points = selected.loc[selected["is_anomaly"] > 0, ANOMALY_COLUMNS]
    if anomaly_points.empty:
        st.info("当前序列没有检测到异常点。")
    else:
        render_dataframe(anomaly_points.head(100))


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
            render_plotly_chart(fig)
        with chart_cols[1]:
            fig = px.bar(summary, x="method", y="anomaly_series", title="各算法异常序列数量")
            fig.update_layout(xaxis_title="算法", yaxis_title="异常序列数")
            render_plotly_chart(fig)
        render_dataframe(summary)

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
        render_plotly_chart(fig)
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
        render_plotly_chart(fig)

    render_dataframe(performance)


def render_series_browser() -> None:
    """Render cleaned metrics by loading only the selected series."""

    st.subheader("时间序列浏览")

    profile = load_csv(str(PROFILES / "series_profile.csv"))
    if profile.empty or not has_columns(profile, ["cmdb_id", "kpi_name"]):
        st.info("缺少 `results/profiles/series_profile.csv`，无法列出时间序列。")
        return
    if not CLEANED_METRICS.exists():
        st.info("缺少 `data/cleaned/metrics_cleaned.csv`，无法展示原始曲线。")
        return

    profile = prepare_series_profile(profile)
    zero_labels = zero_constant_series_labels(profile)
    filter_zero = st.checkbox("过滤 mean=0 且 std=0 的常量零序列", value=True, key="series_filter_zero")
    if filter_zero and zero_labels:
        before_count = len(profile)
        profile = profile.loc[~profile["series_label"].astype(str).isin(zero_labels)].copy()
        st.caption(f"已隐藏 {before_count - len(profile):,} 条全程为 0 且无波动的序列；关闭开关可查看全部序列。")

    if profile.empty:
        st.info("过滤后没有可展示的时间序列，可以关闭过滤开关查看全部序列。")
        return

    if "count" in profile.columns:
        profile = profile.sort_values("count", ascending=False)

    series_options = profile["series_label"].dropna().drop_duplicates().tolist()
    if not series_options:
        st.info("当前没有可展示的时间序列。")
        return

    selected_series = st.selectbox("选择时间序列", series_options, key="series_browser_select_v2")
    selected_meta = profile.loc[profile["series_label"] == selected_series].iloc[0]
    selected = load_metric_series(str(CLEANED_METRICS), str(selected_meta["cmdb_id"]), str(selected_meta["kpi_name"]))

    if selected.empty:
        st.warning("清洗数据中没有找到该序列，请换一个序列。")
        return

    fig = px.line(selected, x="timestamp", y="value", title=f"原始时间序列：{selected_series}")
    fig.update_layout(xaxis_title="时间", yaxis_title="指标值")
    render_plotly_chart(fig)

    st.caption(f"当前序列共有 {len(selected):,} 个点；该序列按需从 1.8GB 清洗文件中分块读取。")
    render_dataframe(selected[METRICS_COLUMNS].head(100))


def align_anomaly_points_to_metrics(metrics_series: pd.DataFrame, anomaly_points: pd.DataFrame) -> pd.DataFrame:
    """Place anomaly markers on the cleaned metric curve when timestamps match."""

    if metrics_series.empty or anomaly_points.empty:
        return anomaly_points

    metric_values = (
        metrics_series[["timestamp", "value"]]
        .dropna(subset=["timestamp", "value"])
        .sort_values("timestamp")
        .rename(columns={"value": "curve_value"})
    )
    if metric_values.empty:
        return anomaly_points

    points = anomaly_points.sort_values("timestamp").copy()
    interval = metric_values["timestamp"].diff().dropna().median()
    tolerance = interval / 2 if pd.notna(interval) and interval > pd.Timedelta(0) else pd.Timedelta(seconds=30)

    aligned = pd.merge_asof(
        points,
        metric_values,
        on="timestamp",
        direction="nearest",
        tolerance=tolerance,
    )
    aligned["plot_value"] = aligned["curve_value"].where(aligned["curve_value"].notna(), aligned["value"])
    return aligned


def build_anomaly_figure(metrics_series: pd.DataFrame, anomaly_rows: pd.DataFrame, title: str, anomaly_label: str) -> go.Figure:
    """Build a line chart from cleaned metrics and overlay anomaly points."""

    fig = go.Figure()
    if not metrics_series.empty:
        metrics_series = metrics_series.sort_values("timestamp")
        fig.add_trace(
            go.Scatter(
                x=metrics_series["timestamp"],
                y=metrics_series["value"],
                mode="lines",
                name="原始曲线",
                line={"color": "#1f77b4", "shape": "hv"},
            )
        )

    anomaly_points = pd.DataFrame(columns=ANOMALY_COLUMNS)
    if not anomaly_rows.empty:
        anomaly_rows = anomaly_rows.sort_values("timestamp")
        if "is_anomaly" in anomaly_rows.columns:
            anomaly_points = anomaly_rows.loc[anomaly_rows["is_anomaly"] > 0].copy()
        else:
            anomaly_points = anomaly_rows.copy()

    if not anomaly_points.empty:
        anomaly_points = align_anomaly_points_to_metrics(metrics_series, anomaly_points)
        fig.add_trace(
            go.Scatter(
                x=anomaly_points["timestamp"],
                y=anomaly_points["plot_value"] if "plot_value" in anomaly_points.columns else anomaly_points["value"],
                mode="markers",
                name=anomaly_label,
                marker={"color": "red", "size": 9, "line": {"color": "white", "width": 1}},
                hovertemplate="时间=%{x}<br>指标值=%{y}<extra>" + anomaly_label + "</extra>",
            )
        )

    threshold_frame = anomaly_rows if not anomaly_rows.empty else anomaly_points
    if not threshold_frame.empty:
        for column, name, color in [
            ("threshold_low", "下阈值", "#ff7f0e"),
            ("threshold_high", "上阈值", "#2ca02c"),
        ]:
            threshold = threshold_frame[column].dropna()
            if threshold.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=threshold_frame["timestamp"],
                    y=threshold_frame[column],
                    mode="lines" if len(threshold_frame) > 1 else "markers",
                    name=name,
                    line={"dash": "dash", "color": color, "shape": "hv"},
                    marker={"symbol": "line-ew", "size": 10, "color": color},
                    connectgaps=True,
                )
            )

    fig.update_layout(
        title=title,
        xaxis_title="时间",
        yaxis_title="指标值",
        hovermode="x unified",
        xaxis={"type": "date", "rangeslider": {"visible": False}},
    )
    return fig


def render_anomaly_view(anomalies: pd.DataFrame) -> None:
    """Render anomaly detection with full CSVs when available and samples as fallback."""

    st.subheader("异常检测展示")

    anomalies = add_series_label(anomalies)
    methods = available_anomaly_methods(anomalies)
    if not methods:
        st.info("缺少可展示的异常结果。当前 Demo 支持全量 `local_*_full/anomaly_*.csv`、`analysis_package/anomaly_sample.csv` 或小型 `anomaly_*.csv`。")
        return

    left, right = st.columns([1, 2])
    selected_method = left.selectbox("选择算法", methods, key="anomaly_method_select_v2")
    use_analysis_package = left.checkbox(
        "使用 analysis_package 轻量模式",
        value=DEFAULT_ANALYSIS_PACKAGE_MODE,
        help="开启后只使用分析包 Top-N 和异常样本展示，不扫描 2-3GB 的全量异常 CSV；云端演示建议开启。",
        key="anomaly_use_analysis_package",
    )
    filter_zero = left.checkbox("过滤 mean=0 且 std=0 的常量零序列", value=True, key="anomaly_filter_zero")
    selected_method_key = canonical_method_key(selected_method)
    method_data = anomalies.loc[anomalies["method"].map(canonical_method_key) == selected_method_key].copy()

    option_source = pd.DataFrame()
    if use_analysis_package and not method_data.empty:
        option_source = method_data.loc[method_data["is_anomaly"] > 0].copy()
        if "score" in option_source.columns:
            option_source["score"] = pd.to_numeric(option_source["score"], errors="coerce")
            option_source = option_source.sort_values("score", ascending=False)

    topn = load_csv(str(ANALYSIS_PACKAGE / "anomaly_series_topn.csv"))
    if option_source.empty and use_analysis_package and not topn.empty and has_columns(topn, ["method", "cmdb_id", "kpi_name"]):
        option_source = add_series_label(
            topn.loc[topn["method"].map(canonical_method_key) == selected_method_key]
        )
        if "anomaly_points" in option_source.columns:
            option_source["anomaly_points"] = pd.to_numeric(option_source["anomaly_points"], errors="coerce")
            option_source = option_source.sort_values("anomaly_points", ascending=False)

    if option_source.empty:
        demo_cases = load_demo_cases(str(ANOMALIES))
        if not demo_cases.empty and has_columns(demo_cases, ["method", "cmdb_id", "kpi_name"]):
            option_source = add_series_label(
                demo_cases.loc[demo_cases["method"].map(canonical_method_key) == selected_method_key]
            )
            if "anomaly_count" in option_source.columns:
                option_source["anomaly_count"] = pd.to_numeric(option_source["anomaly_count"], errors="coerce")
                option_source = option_source.sort_values("anomaly_count", ascending=False)

    if option_source.empty:
        option_source = method_data

    option_source = add_series_label(option_source)
    profile = prepare_series_profile(load_csv(str(PROFILES / "series_profile.csv")))
    zero_labels = zero_constant_series_labels(profile)
    if filter_zero and zero_labels:
        before_count = len(option_source)
        option_source = filter_zero_constant_series(option_source, zero_labels)
        if before_count > len(option_source):
            st.caption(f"已隐藏 {before_count - len(option_source):,} 条全程为 0 且无波动的候选序列；关闭开关可查看全部候选。")

    series_options = option_source["series_label"].dropna().drop_duplicates().tolist()
    if not series_options:
        st.info("当前算法过滤后没有可展示的时间序列，可以关闭过滤开关查看全部候选。")
        return

    selected_series = right.selectbox("选择时间序列", series_options, key="anomaly_series_select_v2")
    selected_meta = option_source.loc[option_source["series_label"] == selected_series].iloc[0]
    cmdb_id = str(selected_meta["cmdb_id"])
    kpi_name = str(selected_meta["kpi_name"])

    metric_series = load_metric_series(str(CLEANED_METRICS), cmdb_id, kpi_name)
    if use_analysis_package:
        full_anomaly_rows = pd.DataFrame(columns=ANOMALY_COLUMNS)
    else:
        full_anomaly_rows = load_anomaly_series_from_full_files(str(ANOMALIES), selected_method, cmdb_id, kpi_name)
    using_full_csv = not full_anomaly_rows.empty

    sample_anomalies = method_data.loc[
        (method_data["cmdb_id"].astype(str) == cmdb_id)
        & (method_data["kpi_name"].astype(str) == kpi_name)
        & (method_data["is_anomaly"] > 0)
    ].copy()
    anomaly_rows = full_anomaly_rows if using_full_csv else sample_anomalies
    anomaly_points = anomaly_rows.loc[anomaly_rows["is_anomaly"] > 0].copy() if "is_anomaly" in anomaly_rows.columns else anomaly_rows

    metric_cols = st.columns(4)
    metric_cols[0].metric("算法", selected_method)
    metric_cols[1].metric("曲线点数", f"{len(metric_series):,}")
    metric_cols[2].metric("异常结果点数", f"{len(anomaly_rows):,}")
    metric_cols[3].metric("异常点数", f"{len(anomaly_points):,}")

    if metric_series.empty and anomaly_rows.empty:
        st.warning("清洗数据和异常结果中都没有找到该序列。")
        return

    anomaly_label = "异常点" if using_full_csv else "异常点样本"
    fig = build_anomaly_figure(metric_series, anomaly_rows, f"{selected_method} 异常检测：{selected_series}", anomaly_label)
    render_plotly_chart(fig)

    if use_analysis_package:
        st.caption("轻量模式已开启：当前使用 `results/analysis_package` 的 Top-N 和异常样本叠加原始曲线，不扫描四个全量异常 CSV。")
    elif using_full_csv:
        st.caption("已从云端全量异常 CSV 中按算法和序列分块读取当前结果；未在启动时全量加载 2-3GB 文件。")
    elif has_full_anomaly_csv(ANOMALIES, selected_method):
        st.caption("云端存在该算法的全量异常 CSV，但当前序列未匹配到全量结果，已退回使用 analysis_package 或小型异常文件中的样本。")
    else:
        st.caption("未发现该算法的全量异常 CSV，当前使用 analysis_package 或小型异常文件中的样本展示。")

    if anomaly_points.empty:
        st.info("当前序列没有检测到异常点；可以换一个 Top-N 序列。")
    else:
        render_dataframe(anomaly_points[ANOMALY_COLUMNS].head(100))


def render_algorithm_and_performance(anomalies: pd.DataFrame) -> None:
    """Render algorithm and performance comparison from summary files."""

    st.subheader("算法与性能对比")

    summary = load_algorithm_summary()
    if summary.empty and not anomalies.empty:
        anomalies = add_series_label(anomalies)
        anomalies["is_anomaly"] = pd.to_numeric(anomalies["is_anomaly"], errors="coerce").fillna(0).astype(int)
        summary = anomalies.groupby("method", as_index=False).agg(
            total_points=("is_anomaly", "size"),
            anomaly_points=("is_anomaly", "sum"),
        )
        summary["anomaly_rate"] = summary["anomaly_points"] / summary["total_points"].replace(0, np.nan)

    if summary.empty:
        st.info("暂无算法汇总结果。")
    else:
        summary = summary.copy()
        summary["anomaly_rate_percent"] = pd.to_numeric(summary["anomaly_rate"], errors="coerce") * 100
        st.markdown("#### 异常检测结果汇总")
        chart_cols = st.columns(2)
        with chart_cols[0]:
            fig = px.bar(summary, x="method", y="anomaly_points", title="各算法异常点数量")
            fig.update_layout(xaxis_title="算法", yaxis_title="异常点数")
            render_plotly_chart(fig)
        with chart_cols[1]:
            fig = px.bar(summary, x="method", y="anomaly_rate_percent", title="各算法异常率")
            fig.update_layout(xaxis_title="算法", yaxis_title="异常率（%）")
            render_plotly_chart(fig)
        render_dataframe(summary)

    performance = load_performance_report()
    if performance.empty:
        st.info("暂无性能测试结果。支持 `performance_report.csv` 或 `full_comparison_report.csv`。")
        return

    performance = performance.copy()
    performance["runtime_sec"] = pd.to_numeric(performance["runtime_sec"], errors="coerce")
    performance["throughput"] = pd.to_numeric(performance["throughput"], errors="coerce")
    performance["server_num"] = performance["server_num"].astype(str)
    if "mode" not in performance.columns:
        performance["mode"] = "unknown"

    st.markdown("#### 单机 / Hadoop 性能对比")
    perf_cols = st.columns(2)
    with perf_cols[0]:
        fig = px.bar(
            performance,
            x="method",
            y="runtime_sec",
            color="mode",
            barmode="group",
            hover_data=["server_num", "data_count"],
            title="运行时间对比",
        )
        fig.update_layout(xaxis_title="算法", yaxis_title="运行时间（秒）", legend_title="模式")
        render_plotly_chart(fig)
    with perf_cols[1]:
        fig = px.bar(
            performance,
            x="method",
            y="throughput",
            color="mode",
            barmode="group",
            hover_data=["server_num", "data_count"],
            title="吞吐量对比",
        )
        fig.update_layout(xaxis_title="算法", yaxis_title="吞吐量（records/s）", legend_title="模式")
        render_plotly_chart(fig)

    render_dataframe(performance)


def main() -> None:
    """Render the Streamlit app."""

    st.title("时间序列异常检测 Demo")
    st.caption("面向运维监控指标的时间序列异常检测与 Hadoop 分布式处理展示")

    anomalies = normalize_anomalies(load_anomaly_files(str(ANOMALIES)))

    tabs = st.tabs(["项目概览", "数据统计", "时间序列浏览", "异常检测展示", "算法与性能对比"])

    with tabs[0]:
        render_project_overview()
    with tabs[1]:
        render_data_statistics()
    with tabs[2]:
        render_series_browser()
    with tabs[3]:
        render_anomaly_view(anomalies)
    with tabs[4]:
        render_algorithm_and_performance(anomalies)


if __name__ == "__main__":
    main()

