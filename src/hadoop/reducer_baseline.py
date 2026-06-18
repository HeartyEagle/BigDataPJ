#!/usr/bin/env python3
"""Hadoop Streaming reducer for baseline anomaly detection.

输入来自 mapper_baseline.py，同一条时间序列的数据会被 Hadoop 聚到一起。
输出字段严格对齐项目异常结果接口：
timestamp,cmdb_id,kpi_name,value,method,is_anomaly,score,threshold_low,threshold_high

说明：
    支持 IQR、全局 K-Sigma、Range，对齐本地 baseline.py。
"""

from __future__ import annotations

import argparse
import math
import sys

import pandas as pd


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    fraction = pos - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, math.sqrt(variance)


def point_sort_key(point: tuple[str, float]) -> tuple[int, float | str]:
    timestamp = point[0]
    try:
        return (0, float(timestamp))
    except ValueError:
        return (1, timestamp)


def numeric_points(points: list[tuple[str, str]]) -> list[tuple[str, float]]:
    if not points:
        return []
    values = pd.to_numeric(pd.Series([value for _, value in points]), errors="coerce")
    return [
        (timestamp, float(value))
        for (timestamp, _), value in zip(points, values)
        if not pd.isna(value)
    ]


def emit_iqr_series(key: str, raw_points: list[tuple[str, str]]) -> None:
    points = numeric_points(raw_points)
    if not points:
        return
    cmdb_id, kpi_name = key.split("|", 1)
    values = [value for _, value in points]
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    iqr = q3 - q1
    threshold_low = q1 - 1.5 * iqr
    threshold_high = q3 + 1.5 * iqr

    for timestamp, value in sorted(points, key=point_sort_key):
        low_gap = threshold_low - value
        high_gap = value - threshold_high
        score = max(low_gap, high_gap, 0.0)
        is_anomaly = int(value < threshold_low or value > threshold_high)
        print(
            f"{timestamp},{cmdb_id},{kpi_name},{value},Hadoop-IQR,"
            f"{is_anomaly},{score},{threshold_low},{threshold_high}"
        )


def emit_ksigma_series(key: str, raw_points: list[tuple[str, str]], k: float) -> None:
    points = numeric_points(raw_points)
    if not points:
        return
    cmdb_id, kpi_name = key.split("|", 1)
    values = [value for _, value in points]
    mean, std = mean_std(values)
    threshold_low = mean - k * std
    threshold_high = mean + k * std

    for timestamp, value in sorted(points, key=point_sort_key):
        diff = abs(value - mean)
        if std and std != 0:
            score = diff / std
            is_anomaly = int(value < threshold_low or value > threshold_high)
        else:
            score = 0.0
            is_anomaly = 0
        print(
            f"{timestamp},{cmdb_id},{kpi_name},{value},Hadoop-K-Sigma,"
            f"{is_anomaly},{score},{threshold_low},{threshold_high}"
        )


def range_thresholds(kpi_name: str, values: list[float]) -> tuple[float, float]:
    lower_name = kpi_name.lower()
    value_min = min(values) if values else 0.0
    if any(token in lower_name for token in ["pct", "percent", "percentage"]):
        return 0.0, 100.0
    if any(token in lower_name for token in ["rate", "ratio", "sr", "rr", "success", "failure", "error"]):
        return 0.0, math.inf
    if any(token in lower_name for token in ["cpu", "memory", "disk", "latency", "mrt", "time", "delay"]):
        return 0.0, math.inf
    if value_min >= 0:
        return 0.0, math.inf
    return -math.inf, math.inf


def emit_range_series(key: str, raw_points: list[tuple[str, str]]) -> None:
    points = numeric_points(raw_points)
    if not points:
        return
    cmdb_id, kpi_name = key.split("|", 1)
    values = [value for _, value in points]
    threshold_low, threshold_high = range_thresholds(kpi_name, values)

    for timestamp, value in sorted(points, key=point_sort_key):
        low_gap = threshold_low - value
        high_gap = value - threshold_high
        score = max(low_gap, high_gap, 0.0)
        is_anomaly = int(value < threshold_low or value > threshold_high)
        print(
            f"{timestamp},{cmdb_id},{kpi_name},{value},Hadoop-Range,"
            f"{is_anomaly},{score},{threshold_low},{threshold_high}"
        )


def emit_series(
    key: str,
    points: list[tuple[str, str]],
    method: str,
    k: float,
) -> None:
    if method == "iqr":
        emit_iqr_series(key, points)
        return
    if method == "ksigma":
        emit_ksigma_series(key, points, k)
        return
    if method == "range":
        emit_range_series(key, points)
        return
    raise ValueError(f"Unsupported method: {method}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=["iqr", "ksigma", "range"], default="iqr")
    parser.add_argument("--k", type=float, default=3.0)
    args = parser.parse_args()

    current_key: str | None = None
    current_points: list[tuple[str, str]] = []

    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line or "\t" not in line:
            continue
        key, raw_value = line.split("\t", 1)
        try:
            timestamp, value_text = raw_value.rsplit(",", 1)
        except ValueError:
            continue
        point = (timestamp, value_text.strip())

        if current_key is not None and key != current_key:
            emit_series(current_key, current_points, args.method, args.k)
            current_points = []
        current_key = key
        current_points.append(point)

    if current_key is not None:
        emit_series(current_key, current_points, args.method, args.k)


if __name__ == "__main__":
    main()
