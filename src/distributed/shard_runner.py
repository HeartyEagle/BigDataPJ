"""Helpers for splitting series across workers.

成员 5 主要修改本文件：
1. 用 series_id 对 5000+ 条序列分片。
2. 在服务器 2/3 上分别运行算法。
3. 汇总性能测试结果到 results/performance/performance_report.csv。
"""

from __future__ import annotations

import argparse

import pandas as pd

from src.utils.data_contract import SERIES_KEY
from src.utils.io import read_table, write_table


def assign_series_shards(series_index: pd.DataFrame, worker_count: int) -> pd.DataFrame:
    """Assign each series to a worker by series_id modulo worker_count."""

    if "series_id" not in series_index.columns:
        raise ValueError("series_index must contain series_id")
    sharded = series_index.copy()
    sharded["worker_id"] = ((sharded["series_id"] - 1) % worker_count) + 1
    return sharded


def filter_data_for_worker(metrics: pd.DataFrame, sharded_index: pd.DataFrame, worker_id: int) -> pd.DataFrame:
    keys = sharded_index.loc[sharded_index["worker_id"] == worker_id, SERIES_KEY]
    return metrics.merge(keys, on=SERIES_KEY, how="inner")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--series-index", default="results/profiles/series_index.csv")
    parser.add_argument("--metrics", default="data/cleaned/metrics_cleaned.csv")
    parser.add_argument("--worker-count", type=int, default=2)
    parser.add_argument("--worker-id", type=int, default=1)
    parser.add_argument("--output", default="data/sample/worker_shard.csv")
    args = parser.parse_args()

    sharded = assign_series_shards(read_table(args.series_index), args.worker_count)
    worker_data = filter_data_for_worker(read_table(args.metrics), sharded, args.worker_id)
    write_table(worker_data, args.output)
    print(f"worker={args.worker_id} rows={len(worker_data)} output={args.output}")


if __name__ == "__main__":
    main()
