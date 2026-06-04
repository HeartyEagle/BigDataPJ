"""Clean raw performance metric data into the project contract.

成员 3 主要修改本文件：
1. 对接成员 2 导入后的原始数据路径。
2. 把不同目录下的 node/container/jvm/istio 指标清洗成统一字段。
3. 输出 data/cleaned/metrics_cleaned.csv 或 .parquet。

输入接口（支持两种来源）：
    A. 已归一化格式： timestamp, cmdb_id, kpi_name, value
    B. 原始格式：     timestamp（字符串或 Unix 秒）+ cmdb_id + kpi_name + value

输出接口：
    timestamp（datetime），cmdb_id（string），kpi_name（string），value（float64）
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from src.utils.data_contract import METRICS_COLUMNS
from src.utils.io import ensure_columns, read_table, write_table

# 成员 2 导出的原始列名可能与项目规范不同，在这里做别名映射
_COLUMN_ALIASES: dict[str, str] = {
    "time": "timestamp",
    "ts": "timestamp",
    "host": "cmdb_id",
    "machine_id": "cmdb_id",
    "node": "cmdb_id",
    "metric": "kpi_name",
    "kpi": "kpi_name",
    "metric_name": "kpi_name",
    "val": "value",
    "metric_value": "value",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """尝试把常见别名列名统一成项目标准列名。"""
    renamed = {col: _COLUMN_ALIASES[col] for col in df.columns if col in _COLUMN_ALIASES}
    return df.rename(columns=renamed) if renamed else df


def _parse_timestamps(series: pd.Series) -> pd.Series:
    """自动识别时间戳格式，优先尝试 Unix 秒，再回退到字符串解析。"""
    numeric = pd.to_numeric(series, errors="coerce")
    numeric_ratio = numeric.notna().sum() / max(len(series), 1)

    if numeric_ratio > 0.5:
        # Unix 秒（10位）还是毫秒（13位）？
        median_val = numeric.median()
        if median_val > 1e12:
            return pd.to_datetime(numeric, unit="ms", errors="coerce")
        return pd.to_datetime(numeric, unit="s", errors="coerce")

    return pd.to_datetime(series, errors="coerce")


def clean_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """返回清洗后的性能指标 DataFrame。"""
    df = _normalize_columns(df)
    ensure_columns(df, METRICS_COLUMNS, "raw metrics")

    cleaned = df.loc[:, METRICS_COLUMNS].copy()

    # --- 字符串字段 ---
    cleaned["cmdb_id"] = cleaned["cmdb_id"].astype("string").str.strip()
    cleaned["kpi_name"] = cleaned["kpi_name"].astype("string").str.strip()

    # --- 时间戳 ---
    cleaned["timestamp"] = _parse_timestamps(cleaned["timestamp"])

    # --- value 转数值，过滤 inf ---
    cleaned["value"] = pd.to_numeric(cleaned["value"], errors="coerce")
    cleaned["value"] = cleaned["value"].replace([np.inf, -np.inf], np.nan)

    n_raw = len(cleaned)

    # 丢弃任意关键字段为空的行
    cleaned = cleaned.dropna(subset=METRICS_COLUMNS)

    # 去重（保留最后一条）
    cleaned = cleaned.drop_duplicates(subset=["timestamp", "cmdb_id", "kpi_name"], keep="last")

    # 排序
    cleaned = cleaned.sort_values(["cmdb_id", "kpi_name", "timestamp"]).reset_index(drop=True)

    n_cleaned = len(cleaned)
    print(f"  raw rows={n_raw}  cleaned rows={n_cleaned}  dropped={n_raw - n_cleaned}")
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/raw", help="Raw csv/parquet file or directory.")
    parser.add_argument("--output", default="data/cleaned/metrics_cleaned.csv")
    args = parser.parse_args()

    raw = read_table(args.input)
    cleaned = clean_metrics(raw)
    write_table(cleaned, args.output)
    print(f"Cleaned data saved to {args.output}")


if __name__ == "__main__":
    main()
