"""Baseline anomaly detection algorithms.

成员 4 主要修改本文件：
1. 完成 IQR、K-Sigma、Range 三个保底算法。
2. 严格按 ANOMALY_COLUMNS 输出结果。
3. 挑选典型异常案例给成员 6 做 Demo。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.data_contract import ANOMALY_COLUMNS, METRICS_COLUMNS, SERIES_KEY
from src.utils.io import ensure_columns, read_table, write_table


def _result_frame(df: pd.DataFrame, method: str, is_anomaly: pd.Series, score: pd.Series, low: float, high: float) -> pd.DataFrame:
    result = df.loc[:, METRICS_COLUMNS].copy()
    result["method"] = method
    result["is_anomaly"] = is_anomaly.astype(int)
    result["score"] = score
    result["threshold_low"] = low
    result["threshold_high"] = high
    return result.loc[:, ANOMALY_COLUMNS]


def detect_iqr(group: pd.DataFrame, multiplier: float = 1.5) -> pd.DataFrame:
    q1 = group["value"].quantile(0.25)
    q3 = group["value"].quantile(0.75)
    iqr = q3 - q1
    low = q1 - multiplier * iqr
    high = q3 + multiplier * iqr
    score = np.maximum(low - group["value"], group["value"] - high).clip(lower=0)
    return _result_frame(group, "IQR", (group["value"] < low) | (group["value"] > high), score, low, high)


def detect_ksigma(group: pd.DataFrame, k: float = 3.0) -> pd.DataFrame:
    mean = group["value"].mean()
    std = group["value"].std(ddof=0)
    low = mean - k * std
    high = mean + k * std
    score = ((group["value"] - mean).abs() / std) if std else pd.Series(0.0, index=group.index)
    return _result_frame(group, "K-Sigma", (group["value"] < low) | (group["value"] > high), score, low, high)


def detect_range(group: pd.DataFrame) -> pd.DataFrame:
    # 成员 4 可按 kpi_name 补充更细范围，例如 CPU/内存百分比为 0-100。
    kpi_name = str(group["kpi_name"].iloc[0]).lower()
    if "pct" in kpi_name or "percent" in kpi_name or "usage" in kpi_name:
        low, high = 0.0, 100.0
    else:
        low, high = -np.inf, np.inf
    score = np.maximum(low - group["value"], group["value"] - high).clip(lower=0)
    return _result_frame(group, "Range", (group["value"] < low) | (group["value"] > high), score, low, high)


def run_baseline(df: pd.DataFrame, method: str = "all") -> dict[str, pd.DataFrame]:
    ensure_columns(df, METRICS_COLUMNS, "cleaned metrics")
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=METRICS_COLUMNS)

    detectors = {
        "iqr": detect_iqr,
        "ksigma": detect_ksigma,
        "range": detect_range,
    }
    selected = detectors if method == "all" else {method: detectors[method]}
    outputs: dict[str, pd.DataFrame] = {}
    for name, detector in selected.items():
        frames = [detector(group) for _, group in df.groupby(SERIES_KEY, sort=False)]
        outputs[name] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=ANOMALY_COLUMNS)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/cleaned/metrics_cleaned.csv")
    parser.add_argument("--output-dir", default="results/anomalies")
    parser.add_argument("--method", choices=["all", "iqr", "ksigma", "range"], default="all")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = run_baseline(read_table(args.input), args.method)
    for name, result in outputs.items():
        out = output_dir / f"anomaly_{name}.csv"
        write_table(result, out)
        print(f"{name}: rows={len(result)} anomalies={int(result['is_anomaly'].sum())} output={out}")


if __name__ == "__main__":
    main()
