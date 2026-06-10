#!/usr/bin/env python3
"""Hadoop Streaming mapper — 成员 3 统计画像阶段。

输入：cleaned CSV 行，格式 timestamp,cmdb_id,kpi_name,value
输出：cmdb_id|kpi_name <TAB> timestamp,value

与 mapper_clean.py 逻辑相同，独立存放便于单独运行画像作业。
"""

from __future__ import annotations

import sys


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("timestamp,"):
            continue
        parts = line.split(",", 3)
        if len(parts) != 4:
            continue
        ts_raw, cmdb_id, kpi_name, val_raw = parts
        cmdb_id = cmdb_id.strip()
        kpi_name = kpi_name.strip()
        if not cmdb_id or not kpi_name:
            continue
        try:
            ts = int(ts_raw.strip())
            v = float(val_raw.strip())
        except ValueError:
            continue
        print(f"{cmdb_id}|{kpi_name}\t{ts},{v}")


if __name__ == "__main__":
    main()
