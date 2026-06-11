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

from src.utils.data_contract import METRICS_COLUMNS, SERIES_KEY
from src.utils.io import ensure_columns, read_table, write_table

_SEED = 42


def _filter_by_series(df: pd.DataFrame, keys: list[tuple[str, str]]) -> pd.DataFrame:
    key_set = set(keys)
    mask = pd.Series(
        [row in key_set for row in zip(df["cmdb_id"], df["kpi_name"])],
        index=df.index,
    )
    return df[mask].reset_index(drop=True)


def _iter_csv_chunks(path: Path, chunksize: int) -> pd.io.parsers.TextFileReader:
    return pd.read_csv(path, chunksize=chunksize)


def _collect_series_keys_csv(path: Path, chunksize: int) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    keys: list[tuple[str, str]] = []
    for chunk in pd.read_csv(path, usecols=SERIES_KEY, chunksize=chunksize):
        ensure_columns(chunk, SERIES_KEY, "cleaned metrics")
        for cmdb_id, kpi_name in chunk.drop_duplicates(SERIES_KEY).itertuples(index=False, name=None):
            key = (str(cmdb_id), str(kpi_name))
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _write_sample_chunks_csv(
    input_path: Path,
    small_path: Path,
    medium_path: Path,
    selected_small: list[tuple[str, str]],
    selected_medium: list[tuple[str, str]],
    chunksize: int,
) -> tuple[int, int]:
    small_path.parent.mkdir(parents=True, exist_ok=True)
    medium_path.parent.mkdir(parents=True, exist_ok=True)

    small_set = set(selected_small)
    medium_set = set(selected_medium)
    small_rows = 0
    medium_rows = 0
    first_small = True
    first_medium = True

    for chunk in _iter_csv_chunks(input_path, chunksize):
        ensure_columns(chunk, METRICS_COLUMNS, "cleaned metrics")
        row_keys = pd.Series(
            zip(chunk["cmdb_id"].astype(str), chunk["kpi_name"].astype(str)),
            index=chunk.index,
        )

        medium_chunk = chunk.loc[row_keys.isin(medium_set), METRICS_COLUMNS]
        if not medium_chunk.empty:
            medium_chunk.to_csv(medium_path, mode="w" if first_medium else "a", header=first_medium, index=False)
            first_medium = False
            medium_rows += len(medium_chunk)

        small_chunk = chunk.loc[row_keys.isin(small_set), METRICS_COLUMNS]
        if not small_chunk.empty:
            small_chunk.to_csv(small_path, mode="w" if first_small else "a", header=first_small, index=False)
            first_small = False
            small_rows += len(small_chunk)

    if first_small:
        pd.DataFrame(columns=METRICS_COLUMNS).to_csv(small_path, index=False)
    if first_medium:
        pd.DataFrame(columns=METRICS_COLUMNS).to_csv(medium_path, index=False)
    return small_rows, medium_rows


def _make_samples_streaming_csv(
    input_path: Path,
    small_path: str | Path,
    medium_path: str | Path,
    n_small: int,
    n_medium: int,
    chunksize: int,
) -> None:
    all_keys = _collect_series_keys_csv(input_path, chunksize)
    total = len(all_keys)

    rng = random.Random(_SEED)
    n_medium = min(n_medium, total)
    n_small = min(n_small, n_medium)

    selected_medium = rng.sample(all_keys, n_medium)
    selected_small = selected_medium[:n_small]

    small_rows, medium_rows = _write_sample_chunks_csv(
        input_path,
        Path(small_path),
        Path(medium_path),
        selected_small,
        selected_medium,
        chunksize,
    )

    print(f"  total series: {total}")
    print(f"  small:  {n_small} series, {small_rows} rows  -> {small_path}")
    print(f"  medium: {n_medium} series, {medium_rows} rows -> {medium_path}")


def make_samples(
    input_path: str | Path,
    small_path: str | Path = "data/sample/sample_small.csv",
    medium_path: str | Path = "data/sample/sample_medium.csv",
    n_small: int = 10,
    n_medium: int = 100,
    chunksize: int = 500_000,
) -> None:
    input_path = Path(input_path)
    if input_path.is_file() and input_path.suffix == ".csv":
        _make_samples_streaming_csv(input_path, small_path, medium_path, n_small, n_medium, chunksize)
        return

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
    parser.add_argument("--chunksize", type=int, default=500_000)
    args = parser.parse_args()

    make_samples(
        args.input,
        small_path=args.small_output,
        medium_path=args.medium_output,
        n_small=args.n_small,
        n_medium=args.n_medium,
        chunksize=args.chunksize,
    )
    print("Samples written.")


if __name__ == "__main__":
    main()
