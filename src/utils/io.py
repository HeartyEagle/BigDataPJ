"""Small IO helpers shared by all modules."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_table(path: str | Path) -> pd.DataFrame:
    """Read a CSV or Parquet file.

    成员 2/3/4/5/6 都应通过这个函数读表，后续如果统一改成 Parquet 或
    IoTDB 导出文件，只需要在这里扩展。
    """

    path = Path(path)
    if path.is_dir():
        frames = [
            read_table(child)
            for child in sorted(path.rglob("*"))
            if child.is_file() and child.suffix in {".csv", ".parquet"}
        ]
        if not frames:
            raise FileNotFoundError(f"No csv/parquet files found in {path}")
        return pd.concat(frames, ignore_index=True)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported table format: {path}")


def write_table(df: pd.DataFrame, path: str | Path) -> None:
    """Write CSV or Parquet according to file suffix."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        df.to_csv(path, index=False)
        return
    if path.suffix == ".parquet":
        df.to_parquet(path, index=False)
        return
    raise ValueError(f"Unsupported table format: {path}")


def ensure_columns(df: pd.DataFrame, required: list[str], source: str) -> None:
    """Fail early when a teammate hands over a file with mismatched columns."""

    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{source} missing required columns: {missing}")
