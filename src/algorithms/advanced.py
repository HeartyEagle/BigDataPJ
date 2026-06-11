"""Advanced anomaly detection algorithms.

成员 5 主要修改本文件：
1. 实现滚动 Robust Z-Score 高级算法。
2. 严格按 ANOMALY_COLUMNS 输出结果。
3. 输出与 baseline.py 对齐的 summary 和 demo cases。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.data_contract import ANOMALY_COLUMNS, METRICS_COLUMNS, SERIES_KEY
from src.utils.io import ensure_columns, read_table, write_table


METHOD_NAME = "Rolling-Robust-ZScore"
_EPS = 1e-12


def _timestamp_sort_key(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().any():
        return numeric
    return pd.to_datetime(series, errors="coerce").astype("int64")


def detect_rolling_robust_zscore(
    group: pd.DataFrame,
    window: int = 60,
    min_periods: int = 30,
    z_threshold: float = 3.5,
) -> pd.DataFrame:
    """Detect anomalies in one time series with rolling median and IQR."""

    ensure_columns(group, METRICS_COLUMNS, "cleaned metrics")
    df = group.loc[:, METRICS_COLUMNS].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["_sort_key"] = _timestamp_sort_key(df["timestamp"])
    df = df.dropna(subset=["timestamp", "cmdb_id", "kpi_name", "value", "_sort_key"])
    if df.empty:
        return pd.DataFrame(columns=ANOMALY_COLUMNS)

    df = df.sort_values("_sort_key", kind="mergesort").reset_index(drop=True)
    values = df["value"].astype(float)
    history = values.shift(1)

    rolling = history.rolling(window=window, min_periods=min_periods)
    center = rolling.median()
    q1 = rolling.quantile(0.25)
    q3 = rolling.quantile(0.75)

    global_center = float(values.median())
    global_iqr_scale = float((values.quantile(0.75) - values.quantile(0.25)) / 1.349)
    global_std = float(values.std(ddof=0)) if len(values) > 1 else 0.0
    global_scale = max(global_iqr_scale, global_std)

    center = center.fillna(global_center)
    scale = (q3 - q1) / 1.349
    if global_scale > _EPS:
        scale = scale.fillna(global_scale).mask(scale <= _EPS, global_scale)
    else:
        scale = scale.fillna(0.0)

    diff = (values - center).abs()
    threshold_low = center - z_threshold * scale
    threshold_high = center + z_threshold * scale
    has_scale = scale > _EPS
    score = pd.Series(np.where(has_scale, diff / scale.mask(~has_scale, np.nan), diff), index=df.index).fillna(0.0)
    is_anomaly = pd.Series(np.where(has_scale, diff > z_threshold * scale, diff > _EPS), index=df.index)

    result = df.loc[:, METRICS_COLUMNS].copy()
    result["method"] = METHOD_NAME
    result["is_anomaly"] = is_anomaly.astype(int)
    result["score"] = score.astype(float)
    result["threshold_low"] = threshold_low.astype(float)
    result["threshold_high"] = threshold_high.astype(float)
    return result.loc[:, ANOMALY_COLUMNS]


def summarize_advanced(result: pd.DataFrame) -> pd.DataFrame:
    total = len(result)
    anomalies = int(result["is_anomaly"].sum()) if not result.empty else 0
    series_count = int(result.drop_duplicates(SERIES_KEY).shape[0]) if not result.empty else 0
    return pd.DataFrame(
        [
            {
                "method": METHOD_NAME,
                "series_count": series_count,
                "record_count": total,
                "anomaly_count": anomalies,
                "anomaly_rate": anomalies / total if total else 0.0,
            }
        ],
        columns=["method", "series_count", "record_count", "anomaly_count", "anomaly_rate"],
    )


def select_demo_cases(result: pd.DataFrame, top_n: int = 5) -> pd.DataFrame:
    if result.empty:
        return pd.DataFrame(columns=["cmdb_id", "kpi_name", "method", "anomaly_count", "max_score"])

    anomalies = result.loc[result["is_anomaly"] > 0, ["cmdb_id", "kpi_name", "method", "score"]].copy()
    if anomalies.empty:
        return pd.DataFrame(columns=["cmdb_id", "kpi_name", "method", "anomaly_count", "max_score"])

    summary = (
        anomalies.groupby(["cmdb_id", "kpi_name", "method"], as_index=False)
        .agg(anomaly_count=("score", "count"), max_score=("score", "max"))
        .sort_values(["anomaly_count", "max_score"], ascending=[False, False])
    )
    return summary.head(top_n).reset_index(drop=True)


def run_advanced(
    df: pd.DataFrame,
    window: int = 60,
    min_periods: int = 30,
    z_threshold: float = 3.5,
) -> pd.DataFrame:
    ensure_columns(df, METRICS_COLUMNS, "cleaned metrics")
    df = df.copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=METRICS_COLUMNS)

    frames = [
        detect_rolling_robust_zscore(group, window=window, min_periods=min_periods, z_threshold=z_threshold)
        for _, group in df.groupby(SERIES_KEY, sort=False)
    ]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ANOMALY_COLUMNS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/cleaned/metrics_cleaned.csv")
    parser.add_argument("--output-dir", default="results/anomalies")
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--min-periods", type=int, default=30)
    parser.add_argument("--z-threshold", type=float, default=3.5)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result = run_advanced(
        read_table(args.input),
        window=args.window,
        min_periods=args.min_periods,
        z_threshold=args.z_threshold,
    )

    summary = summarize_advanced(result)
    write_table(summary, output_dir / "advanced_summary.csv")
    print("advanced_summary:", len(summary), "methods")

    demo_cases = select_demo_cases(result, top_n=5)
    if not demo_cases.empty:
        write_table(demo_cases, output_dir / "demo_cases.csv")
        print("demo_cases:", len(demo_cases), "series selected")
    else:
        write_table(demo_cases, output_dir / "demo_cases.csv")
        print("demo_cases: no anomalies found, empty file written")

    out = output_dir / "anomaly_advanced.csv"
    write_table(result, out)
    print(f"advanced: rows={len(result)} anomalies={int(result['is_anomaly'].sum())} output={out}")


if __name__ == "__main__":
    main()
