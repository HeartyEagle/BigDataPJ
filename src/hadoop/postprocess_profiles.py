#!/usr/bin/env python3
"""将 reducer_profile 的 HDFS 输出转换成项目标准文件。

输入：从 HDFS 下载的 part-* 文件目录（TAB 分隔，每行一条序列统计）
输出（写入 --output-dir）：
    series_index.csv
    series_profile.csv
    kpi_distribution.csv
    missing_topn.csv
    data_overview.json

用法：
    python3 src/hadoop/postprocess_profiles.py \\
        --input  /tmp/member3_profiles \\
        --output-dir results/profiles
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


_COLS = [
    "cmdb_id", "kpi_name", "count", "ts_min", "ts_max",
    "missing_rate", "v_min", "v_max", "mean", "std",
]


def _ts_to_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_reducer_output(input_dir: Path) -> pd.DataFrame:
    frames = []
    for f in sorted(input_dir.glob("part-*")):
        if not f.is_file():
            continue
        df = pd.read_csv(f, sep="\t", header=None, names=_COLS)
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No part-* files found in {input_dir}")
    return pd.concat(frames, ignore_index=True)


def build(df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    df = df.sort_values(["cmdb_id", "kpi_name"]).reset_index(drop=True)
    df.insert(0, "series_id", range(1, len(df) + 1))

    # series_index.csv
    series_index = df[["series_id", "cmdb_id", "kpi_name", "ts_min", "ts_max", "count"]].copy()
    series_index["start_time"] = series_index["ts_min"].apply(_ts_to_dt)
    series_index["end_time"] = series_index["ts_max"].apply(_ts_to_dt)
    series_index = series_index.rename(columns={"count": "point_count"})
    series_index = series_index[["series_id", "cmdb_id", "kpi_name", "start_time", "end_time", "point_count"]]
    series_index.to_csv(output_dir / "series_index.csv", index=False)

    # series_profile.csv
    profile = df[["series_id", "cmdb_id", "kpi_name", "count", "missing_rate",
                   "v_min", "v_max", "mean", "std"]].copy()
    profile = profile.rename(columns={"v_min": "min", "v_max": "max"})
    profile.to_csv(output_dir / "series_profile.csv", index=False)

    # kpi_distribution.csv
    kpi_dist = (
        df.groupby("kpi_name")
        .agg(series_count=("cmdb_id", "nunique"), record_count=("count", "sum"))
        .reset_index()
    )
    kpi_dist.to_csv(output_dir / "kpi_distribution.csv", index=False)

    # missing_topn.csv (top 20)
    missing_topn = (
        df[["series_id", "cmdb_id", "kpi_name", "missing_rate"]]
        .sort_values("missing_rate", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )
    missing_topn.to_csv(output_dir / "missing_topn.csv", index=False)

    # data_overview.json
    overview = {
        "record_count": int(df["count"].sum()),
        "cmdb_count": int(df["cmdb_id"].nunique()),
        "kpi_count": int(df["kpi_name"].nunique()),
        "series_count": int(len(df)),
        "start_time": _ts_to_dt(int(df["ts_min"].min())),
        "end_time": _ts_to_dt(int(df["ts_max"].max())),
        "sampling_interval_sec": 60,
    }
    (output_dir / "data_overview.json").write_text(
        json.dumps(overview, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"series={overview['series_count']}  kpi={overview['kpi_count']}  cmdb={overview['cmdb_count']}")
    print(f"Profiles written to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Local directory with HDFS part-* files")
    parser.add_argument("--output-dir", default="results/profiles")
    args = parser.parse_args()

    df = load_reducer_output(Path(args.input))
    build(df, Path(args.output_dir))


if __name__ == "__main__":
    main()
