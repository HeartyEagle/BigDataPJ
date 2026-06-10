#!/opt/miniconda3/bin/python3
"""Hadoop Streaming reducer — 成员 3 统计画像阶段。

输入：mapper_profile.py 的输出，Hadoop 已按 key 排序。
输出：每条时间序列一行，TAB 分隔：
    cmdb_id  kpi_name  count  ts_min  ts_max  missing_rate  v_min  v_max  mean  std

下载到本地后由 scripts/hadoop/postprocess_profiles.py 生成最终 CSV / JSON 文件。
"""

from __future__ import annotations

import math
import sys

_SAMPLING_SEC = 60


def emit(key: str, timestamps: list[int], values: list[float]) -> None:
    if not values:
        return
    cmdb_id, kpi_name = key.split("|", 1)
    n = len(values)
    ts_min = min(timestamps)
    ts_max = max(timestamps)
    expected = (ts_max - ts_min) / _SAMPLING_SEC + 1 if ts_max > ts_min else 1
    missing_rate = max(0.0, min(1.0, 1.0 - n / expected))
    v_min = min(values)
    v_max = max(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance)
    print(
        f"{cmdb_id}\t{kpi_name}\t{n}\t{ts_min}\t{ts_max}"
        f"\t{missing_rate:.6f}\t{v_min}\t{v_max}\t{mean:.6f}\t{std:.6f}"
    )


def main() -> None:
    current_key: str | None = None
    timestamps: list[int] = []
    values: list[float] = []

    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").rstrip("\n")
        if not line or "\t" not in line:
            continue
        key, val = line.split("\t", 1)
        try:
            ts_str, v_str = val.split(",", 1)
            ts = int(ts_str)
            v = float(v_str)
        except ValueError:
            continue

        if key != current_key:
            if current_key is not None:
                emit(current_key, timestamps, values)
            current_key = key
            timestamps = []
            values = []
        timestamps.append(ts)
        values.append(v)

    if current_key is not None:
        emit(current_key, timestamps, values)


if __name__ == "__main__":
    main()
