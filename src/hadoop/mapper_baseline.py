#!/usr/bin/env python3
"""Hadoop Streaming mapper for baseline anomaly detection.

成员 5 负责 Hadoop/并行部分时主要看这里和 reducer_baseline.py。

输入：
    清洗后的 CSV 行，字段为 timestamp,cmdb_id,kpi_name,value

输出：
    key<TAB>value
    key = cmdb_id|kpi_name
    value = timestamp,value

Hadoop 会自动按 key 分组，把同一条时间序列的数据送给 reducer。
"""

from __future__ import annotations

import sys


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("timestamp,"):
            continue
        try:
            timestamp, cmdb_id, kpi_name, value_text = line.split(",", 3)
            timestamp = timestamp.strip()
            cmdb_id = cmdb_id.strip()
            kpi_name = kpi_name.strip()
            value_text = value_text.strip()
            float(value_text)
        except ValueError:
            continue

        key = f"{cmdb_id}|{kpi_name}"
        print(f"{key}\t{timestamp},{value_text}")


if __name__ == "__main__":
    main()
