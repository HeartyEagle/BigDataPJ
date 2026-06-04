"""Build data statistics used by algorithms, Demo, PPT, and project docs.

成员 3 主要修改本文件，成员 6 只读取输出文件做图，不要再从 3GB 原始数据
重复统计。

输出文件：
    results/profiles/data_overview.json
    results/profiles/kpi_distribution.csv
    results/profiles/series_index.csv
    results/profiles/series_profile.csv
    results/profiles/missing_topn.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.utils.data_contract import METRICS_COLUMNS, SERIES_KEY
from src.utils.io import ensure_columns, read_table, write_table

_SAMPLING_INTERVAL_SEC = 60


def _compute_missing_rate(start: pd.Timestamp, end: pd.Timestamp, count: int) -> float:
    """缺失率 = 1 - 实际点数 / 理论点数（按 60s 采样间隔估算）。"""
    if pd.isna(start) or pd.isna(end):
        return 0.0
    delta_sec = (end - start).total_seconds()
    if delta_sec <= 0:
        return 0.0
    expected = delta_sec / _SAMPLING_INTERVAL_SEC + 1
    return max(0.0, min(1.0, 1.0 - count / expected))


def build_profiles(df: pd.DataFrame, output_dir: str | Path = "results/profiles",
                   input_path: str | Path | None = None) -> None:
    ensure_columns(df, METRICS_COLUMNS, "cleaned metrics")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    grouped = df.groupby(SERIES_KEY, dropna=False)

    # --- 序列索引 ---
    series_index = grouped.agg(
        start_time=("timestamp", "min"),
        end_time=("timestamp", "max"),
        point_count=("value", "size"),
    ).reset_index()
    series_index.insert(0, "series_id", range(1, len(series_index) + 1))

    # --- 序列画像（含正确 missing_rate）---
    value_stats = grouped["value"].agg(["count", "min", "max", "mean", "std"]).reset_index()
    profile = series_index.merge(value_stats, on=SERIES_KEY, how="left")
    profile["missing_rate"] = profile.apply(
        lambda r: _compute_missing_rate(r["start_time"], r["end_time"], r["count"]),
        axis=1,
    )
    profile = profile[["series_id", *SERIES_KEY, "count", "missing_rate", "min", "max", "mean", "std"]]

    # --- KPI 分布 ---
    kpi_distribution = (
        grouped.size()
        .reset_index(name="record_count")
        .groupby("kpi_name")
        .agg(series_count=("cmdb_id", "nunique"), record_count=("record_count", "sum"))
        .reset_index()
    )

    # --- 缺失率 Top-20（只保留必要字段，方便成员 6 / PPT 使用）---
    missing_topn = (
        profile.sort_values("missing_rate", ascending=False)
        .head(20)[["series_id", *SERIES_KEY, "missing_rate"]]
        .reset_index(drop=True)
    )

    # --- 数据总览 ---
    file_size_mb = round(Path(input_path).stat().st_size / 1024 / 1024, 2) if input_path and Path(input_path).is_file() else None
    overview: dict = {
        "record_count": int(len(df)),
        "cmdb_count": int(df["cmdb_id"].nunique()),
        "kpi_count": int(df["kpi_name"].nunique()),
        "series_count": int(len(series_index)),
        "start_time": str(df["timestamp"].min()),
        "end_time": str(df["timestamp"].max()),
        "sampling_interval_sec": _SAMPLING_INTERVAL_SEC,
    }
    if file_size_mb is not None:
        overview["file_size_mb"] = file_size_mb

    # --- 写入 ---
    write_table(series_index, output_dir / "series_index.csv")
    write_table(profile, output_dir / "series_profile.csv")
    write_table(kpi_distribution, output_dir / "kpi_distribution.csv")
    write_table(missing_topn, output_dir / "missing_topn.csv")
    (output_dir / "data_overview.json").write_text(
        json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  series={overview['series_count']}  kpi={overview['kpi_count']}  cmdb={overview['cmdb_count']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/cleaned/metrics_cleaned.csv")
    parser.add_argument("--output-dir", default="results/profiles")
    args = parser.parse_args()

    build_profiles(read_table(args.input), args.output_dir, input_path=args.input)
    print(f"Profiles written to {args.output_dir}")


if __name__ == "__main__":
    main()
