"""Clean raw performance metric data into the project contract.

成员 3 主要修改本文件：
1. 对接成员 2 导入后的原始数据路径。
2. 把不同目录下的 node/container/jvm/istio 指标清洗成统一字段。
3. 输出 data/cleaned/metrics_cleaned.csv 或 .parquet。

输入接口：
    timestamp, cmdb_id, kpi_name, value

输出接口：
    timestamp, cmdb_id, kpi_name, value
"""

from __future__ import annotations

import argparse

import pandas as pd

from src.utils.data_contract import METRICS_COLUMNS
from src.utils.io import ensure_columns, read_table, write_table


def clean_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Return cleaned performance metrics."""

    ensure_columns(df, METRICS_COLUMNS, "raw metrics")
    cleaned = df.loc[:, METRICS_COLUMNS].copy()
    cleaned["timestamp"] = pd.to_datetime(cleaned["timestamp"], unit="s", errors="coerce")
    cleaned["value"] = pd.to_numeric(cleaned["value"], errors="coerce")
    cleaned["cmdb_id"] = cleaned["cmdb_id"].astype("string").str.strip()
    cleaned["kpi_name"] = cleaned["kpi_name"].astype("string").str.strip()

    cleaned = cleaned.dropna(subset=METRICS_COLUMNS)
    cleaned = cleaned.drop_duplicates(subset=["timestamp", "cmdb_id", "kpi_name"], keep="last")
    cleaned = cleaned.sort_values(["cmdb_id", "kpi_name", "timestamp"]).reset_index(drop=True)
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/raw", help="Raw csv/parquet file or directory.")
    parser.add_argument("--output", default="data/cleaned/metrics_cleaned.csv")
    args = parser.parse_args()

    raw = read_table(args.input)
    cleaned = clean_metrics(raw)
    write_table(cleaned, args.output)
    print(f"cleaned rows={len(cleaned)} output={args.output}")


if __name__ == "__main__":
    main()
