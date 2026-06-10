#!/opt/miniconda3/bin/python3
"""Hadoop Streaming reducer — 成员 3 数据清洗阶段。

输入：mapper_clean.py 的输出，Hadoop 已按 key 排序。
处理：同一 (cmdb_id, kpi_name) 内按时间戳去重（保留最后一条），升序排列。
输出：timestamp,cmdb_id,kpi_name,value（无 header，纯数据行）
"""

from __future__ import annotations

import sys


def flush(key: str, points: dict[int, float]) -> None:
    if not points:
        return
    cmdb_id, kpi_name = key.split("|", 1)
    for ts in sorted(points):
        print(f"{ts},{cmdb_id},{kpi_name},{points[ts]}")


def main() -> None:
    current_key: str | None = None
    points: dict[int, float] = {}

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
                flush(current_key, points)
            current_key = key
            points = {}
        points[ts] = v  # 同一时间戳保留最后一条

    if current_key is not None:
        flush(current_key, points)


if __name__ == "__main__":
    main()
