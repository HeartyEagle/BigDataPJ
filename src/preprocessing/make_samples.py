"""Generate small and medium sample datasets from cleaned metrics for algorithm team.

成员 3 产出本文件。成员 4、5 优先使用样本数据调试算法，再跑全量。

输出：
    data/sample/sample_small.csv    -- 10 条序列，用于快速调试
    data/sample/sample_medium.csv   -- 100 条序列，用于算法验证
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

from src.utils.data_contract import SERIES_KEY
from src.utils.io import read_table, write_table

_SEED = 42


def _filter_by_series(df: pd.DataFrame, keys: list[tuple[str, str]]) -> pd.DataFrame:
    key_set = set(keys)
    mask = pd.Series(
        [row in key_set for row in zip(df["cmdb_id"], df["kpi_name"])],
        index=df.index,
    )
    return df[mask].reset_index(drop=True)


def make_samples(
    input_path: str | Path,
    small_path: str | Path = "data/sample/sample_small.csv",
    medium_path: str | Path = "data/sample/sample_medium.csv",
    n_small: int = 10,
    n_medium: int = 100,
) -> None:
    df = read_table(input_path)

    all_keys: list[tuple[str, str]] = list(
        df.groupby(SERIES_KEY, sort=False).groups.keys()
    )
    total = len(all_keys)

    rng = random.Random(_SEED)
    n_medium = min(n_medium, total)
    n_small = min(n_small, n_medium)

    selected_medium = rng.sample(all_keys, n_medium)
    selected_small = selected_medium[:n_small]

    small_df = _filter_by_series(df, selected_small)
    medium_df = _filter_by_series(df, selected_medium)

    write_table(small_df, small_path)
    write_table(medium_df, medium_path)

    print(f"  small:  {n_small} series, {len(small_df)} rows  -> {small_path}")
    print(f"  medium: {n_medium} series, {len(medium_df)} rows -> {medium_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/cleaned/metrics_cleaned.csv")
    parser.add_argument("--small-output", default="data/sample/sample_small.csv")
    parser.add_argument("--medium-output", default="data/sample/sample_medium.csv")
    parser.add_argument("--n-small", type=int, default=10)
    parser.add_argument("--n-medium", type=int, default=100)
    args = parser.parse_args()

    make_samples(
        args.input,
        small_path=args.small_output,
        medium_path=args.medium_output,
        n_small=args.n_small,
        n_medium=args.n_medium,
    )
    print("Samples written.")


if __name__ == "__main__":
    main()
