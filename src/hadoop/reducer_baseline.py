#!/usr/bin/env python3
"""Hadoop Streaming reducer for IQR baseline anomaly detection.

输入来自 mapper_baseline.py，同一条时间序列的数据会被 Hadoop 聚到一起。
输出字段严格对齐项目异常结果接口：
timestamp,cmdb_id,kpi_name,value,method,is_anomaly,score,threshold_low,threshold_high

说明：
    这里先实现 IQR，作为 Hadoop 分布式检测的保底版本。
    成员 5 可以在此基础上扩展 K-Sigma、滑动窗口 K-Sigma 或多 reducer 性能统计。
"""

from __future__ import annotations

import sys


HEADER = "timestamp,cmdb_id,kpi_name,value,method,is_anomaly,score,threshold_low,threshold_high"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    fraction = pos - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def emit_series(key: str, points: list[tuple[str, float]]) -> None:
    if not points:
        return
    cmdb_id, kpi_name = key.split("|", 1)
    values = [value for _, value in points]
    q1 = percentile(values, 0.25)
    q3 = percentile(values, 0.75)
    iqr = q3 - q1
    threshold_low = q1 - 1.5 * iqr
    threshold_high = q3 + 1.5 * iqr

    for timestamp, value in sorted(points):
        low_gap = threshold_low - value
        high_gap = value - threshold_high
        score = max(low_gap, high_gap, 0.0)
        is_anomaly = int(value < threshold_low or value > threshold_high)
        print(
            f"{timestamp},{cmdb_id},{kpi_name},{value},Hadoop-IQR,"
            f"{is_anomaly},{score},{threshold_low},{threshold_high}"
        )


def main() -> None:
    print(HEADER)
    current_key: str | None = None
    current_points: list[tuple[str, float]] = []

    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line or "\t" not in line:
            continue
        key, raw_value = line.split("\t", 1)
        try:
            timestamp, value_text = raw_value.rsplit(",", 1)
            point = (timestamp, float(value_text))
        except ValueError:
            continue

        if current_key is not None and key != current_key:
            emit_series(current_key, current_points)
            current_points = []
        current_key = key
        current_points.append(point)

    if current_key is not None:
        emit_series(current_key, current_points)


if __name__ == "__main__":
    main()
