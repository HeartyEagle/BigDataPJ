#!/usr/bin/env python3
"""Hadoop Streaming reducer for advanced anomaly detection.

Input comes from mapper_baseline.py:
    key<TAB>timestamp,value

Each key is one cmdb_id + kpi_name time series. The reducer applies the same
rolling robust z-score idea as src.algorithms.advanced, but stays self-contained
so Hadoop Streaming can ship it as a single reducer file.
"""

from __future__ import annotations

import argparse
import bisect
import math
import sys


METHOD_NAME = "Hadoop-Rolling-Robust-ZScore"
EPS = 1e-12


def percentile(ordered_values: list[float], q: float) -> float:
    if not ordered_values:
        return 0.0
    pos = (len(ordered_values) - 1) * q
    low = int(pos)
    high = min(low + 1, len(ordered_values) - 1)
    fraction = pos - low
    return ordered_values[low] * (1 - fraction) + ordered_values[high] * fraction


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


def remove_sorted_value(values: list[float], value: float) -> None:
    index = bisect.bisect_left(values, value)
    if index < len(values) and values[index] == value:
        values.pop(index)


def emit_series(
    key: str,
    points: list[tuple[str, float]],
    window: int,
    min_periods: int,
    z_threshold: float,
) -> None:
    if not points:
        return

    cmdb_id, kpi_name = key.split("|", 1)
    points = sorted(points, key=point_sort_key)
    values = [value for _, value in points]
    if not values:
        return

    ordered_values = sorted(values)
    global_center = percentile(ordered_values, 0.5)
    global_iqr_scale = (percentile(ordered_values, 0.75) - percentile(ordered_values, 0.25)) / 1.349
    _, global_std = mean_std(values)
    global_scale = max(global_iqr_scale, global_std)

    history_order: list[float] = []
    history_sorted: list[float] = []

    for timestamp, value in points:
        if len(history_sorted) >= min_periods:
            center = percentile(history_sorted, 0.5)
            q1 = percentile(history_sorted, 0.25)
            q3 = percentile(history_sorted, 0.75)
            scale = (q3 - q1) / 1.349
        else:
            center = global_center
            scale = global_scale if global_scale > EPS else 0.0

        if global_scale > EPS and scale <= EPS:
            scale = global_scale

        diff = abs(value - center)
        threshold_low = center - z_threshold * scale
        threshold_high = center + z_threshold * scale
        if scale > EPS:
            score = diff / scale
            is_anomaly = int(diff > z_threshold * scale)
        else:
            score = diff
            is_anomaly = int(diff > EPS)

        print(
            f"{timestamp},{cmdb_id},{kpi_name},{value},{METHOD_NAME},"
            f"{is_anomaly},{score},{threshold_low},{threshold_high}"
        )

        history_order.append(value)
        bisect.insort(history_sorted, value)
        if len(history_order) > window:
            remove_sorted_value(history_sorted, history_order.pop(0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", type=int, default=60)
    parser.add_argument("--min-periods", type=int, default=30)
    parser.add_argument("--z-threshold", type=float, default=3.5)
    args = parser.parse_args()

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
            emit_series(current_key, current_points, args.window, args.min_periods, args.z_threshold)
            current_points = []
        current_key = key
        current_points.append(point)

    if current_key is not None:
        emit_series(current_key, current_points, args.window, args.min_periods, args.z_threshold)


if __name__ == "__main__":
    main()
