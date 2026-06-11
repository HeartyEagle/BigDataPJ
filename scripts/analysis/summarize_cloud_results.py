"""Build a small analysis package from large cloud result files.

The script is designed for server-side use. It scans large anomaly CSV files in
chunks and writes compact summaries that are practical to transfer back for
review, PPT preparation, and Streamlit demo debugging.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.data_contract import ANOMALY_COLUMNS  # noqa: E402


DEFAULT_CHUNK_SIZE = 200_000
SUMMARY_SMALL_FILE_LIMIT_MB = 100


def resolve_path(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def has_columns(path: Path, columns: list[str]) -> bool:
    try:
        header = pd.read_csv(path, nrows=0)
    except Exception:
        return False
    return all(column in header.columns for column in columns)


def find_anomaly_files(root: Path, explicit_files: list[str]) -> list[Path]:
    if explicit_files:
        return [resolve_path(root, item) for item in explicit_files]

    candidates = [
        root / "results" / "anomalies" / "local_advanced_full" / "anomaly_advanced.csv",
        root / "results" / "anomalies" / "local_iqr_full" / "anomaly_iqr.csv",
        root / "results" / "anomalies" / "local_ksigma_full" / "anomaly_ksigma.csv",
        root / "results" / "anomalies" / "local_range_full" / "anomaly_range.csv",
        root / "results" / "anomalies" / "anomaly_advanced.csv",
        root / "results" / "anomalies" / "anomaly_iqr.csv",
        root / "results" / "anomalies" / "anomaly_ksigma.csv",
        root / "results" / "anomalies" / "anomaly_range.csv",
    ]
    hadoop_dir = root / "results" / "anomalies" / "hadoop_iqr"
    if hadoop_dir.exists():
        candidates.extend(sorted(hadoop_dir.glob("part-*")))
    return [path for path in candidates if path.exists() and path.is_file()]


def safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def parse_timestamp(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.notna().mean() >= 0.8:
        median = numeric.dropna().abs().median()
        if median > 1e14:
            unit = "ns"
        elif median > 1e11:
            unit = "ms"
        else:
            unit = "s"
        return pd.to_datetime(numeric, unit=unit, errors="coerce")
    return pd.to_datetime(values, errors="coerce")


def normalize_chunk(chunk: pd.DataFrame) -> pd.DataFrame:
    chunk = chunk.loc[:, ANOMALY_COLUMNS].copy()
    chunk = chunk[chunk["timestamp"].astype(str) != "timestamp"]
    chunk["value"] = safe_numeric(chunk["value"])
    chunk["is_anomaly"] = safe_numeric(chunk["is_anomaly"]).fillna(0).astype(int)
    chunk["score"] = safe_numeric(chunk["score"])
    chunk["threshold_low"] = safe_numeric(chunk["threshold_low"])
    chunk["threshold_high"] = safe_numeric(chunk["threshold_high"])
    chunk["method"] = chunk["method"].astype(str)
    chunk["cmdb_id"] = chunk["cmdb_id"].astype(str)
    chunk["kpi_name"] = chunk["kpi_name"].astype(str)
    return chunk


def append_group_summary(container: list[pd.DataFrame], chunk: pd.DataFrame, keys: list[str]) -> None:
    grouped = (
        chunk.groupby(keys, dropna=False)
        .agg(
            total_points=("is_anomaly", "size"),
            anomaly_points=("is_anomaly", "sum"),
            max_score=("score", "max"),
            mean_score=("score", "mean"),
            min_value=("value", "min"),
            max_value=("value", "max"),
        )
        .reset_index()
    )
    container.append(grouped)


def merge_summaries(parts: list[pd.DataFrame], keys: list[str]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    data = pd.concat(parts, ignore_index=True)
    summary = (
        data.groupby(keys, dropna=False)
        .agg(
            total_points=("total_points", "sum"),
            anomaly_points=("anomaly_points", "sum"),
            max_score=("max_score", "max"),
            mean_score=("mean_score", "mean"),
            min_value=("min_value", "min"),
            max_value=("max_value", "max"),
        )
        .reset_index()
    )
    summary["anomaly_rate"] = summary["anomaly_points"] / summary["total_points"]
    return summary.sort_values(["anomaly_points", "max_score"], ascending=False)


def topn_per_method(summary: pd.DataFrame, topn: int) -> pd.DataFrame:
    if summary.empty or "method" not in summary.columns:
        return summary
    summary = summary.loc[summary["anomaly_points"] > 0].copy()
    summary = summary.sort_values(["method", "anomaly_points", "max_score"], ascending=[True, False, False])
    return summary.groupby("method", group_keys=False).head(topn).reset_index(drop=True)


def copy_small_context_files(root: Path, output_dir: Path) -> list[str]:
    copied: list[str] = []
    targets = [
        root / "results" / "profiles" / "data_overview.json",
        root / "results" / "profiles" / "kpi_distribution.csv",
        root / "results" / "profiles" / "series_profile.csv",
        root / "results" / "profiles" / "missing_topn.csv",
        root / "results" / "performance" / "performance_report.csv",
        root / "results" / "anomalies" / "baseline_summary.csv",
        root / "results" / "anomalies" / "demo_cases.csv",
        root / "results" / "anomalies" / "local_advanced_full" / "advanced_summary.csv",
        root / "results" / "anomalies" / "local_advanced_full" / "demo_cases.csv",
    ]
    context_dir = output_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    for source in targets:
        if not source.exists() or not source.is_file():
            continue
        size_mb = source.stat().st_size / 1024 / 1024
        if size_mb > SUMMARY_SMALL_FILE_LIMIT_MB:
            continue
        destination = context_dir / source.name
        if destination.exists():
            destination = context_dir / f"{source.parent.name}_{source.name}"
        shutil.copy2(source, destination)
        copied.append(destination.relative_to(output_dir).as_posix())
    return copied


def summarize_files(
    files: list[Path],
    output_dir: Path,
    chunk_size: int,
    topn: int,
    sample_per_file: int,
) -> dict[str, object]:
    method_parts: list[pd.DataFrame] = []
    kpi_parts: list[pd.DataFrame] = []
    series_parts: list[pd.DataFrame] = []
    hourly_parts: list[pd.DataFrame] = []
    samples: list[pd.DataFrame] = []
    manifest: list[dict[str, object]] = []

    for path in files:
        if not path.exists() or not path.is_file():
            manifest.append({"path": path.as_posix(), "status": "missing", "size_mb": None})
            continue
        if not has_columns(path, ANOMALY_COLUMNS):
            manifest.append({"path": path.as_posix(), "status": "bad_columns", "size_mb": path.stat().st_size / 1024 / 1024})
            continue

        rows_seen = 0
        sample_parts: list[pd.DataFrame] = []
        for chunk in pd.read_csv(path, usecols=ANOMALY_COLUMNS, chunksize=chunk_size):
            chunk = normalize_chunk(chunk)
            if chunk.empty:
                continue
            rows_seen += len(chunk)

            append_group_summary(method_parts, chunk, ["method"])
            append_group_summary(kpi_parts, chunk, ["method", "kpi_name"])
            append_group_summary(series_parts, chunk, ["method", "cmdb_id", "kpi_name"])

            parsed_time = parse_timestamp(chunk["timestamp"])
            hourly = chunk.assign(hour=parsed_time.dt.floor("h")).dropna(subset=["hour"])
            if not hourly.empty:
                hourly_group = (
                    hourly.groupby(["method", "hour"], dropna=False)["is_anomaly"]
                    .agg(total_points="size", anomaly_points="sum")
                    .reset_index()
                )
                hourly_parts.append(hourly_group)

            anomalous = chunk[chunk["is_anomaly"] > 0].copy()
            if not anomalous.empty:
                top = anomalous.sort_values("score", ascending=False).head(max(1, sample_per_file // 4))
                sample_parts.append(top)
            sample_parts.append(chunk.sample(n=min(200, len(chunk)), random_state=42))

        if sample_parts:
            file_sample = pd.concat(sample_parts, ignore_index=True)
            file_sample = file_sample.sort_values(["is_anomaly", "score"], ascending=False).head(sample_per_file)
            file_sample.insert(0, "source_file", path.name)
            samples.append(file_sample)

        manifest.append(
            {
                "path": path.as_posix(),
                "status": "ok",
                "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
                "rows_seen": rows_seen,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(manifest).to_csv(output_dir / "file_manifest.csv", index=False)

    method_summary = merge_summaries(method_parts, ["method"])
    kpi_summary = merge_summaries(kpi_parts, ["method", "kpi_name"])
    series_summary = merge_summaries(series_parts, ["method", "cmdb_id", "kpi_name"])

    if not method_summary.empty and not series_summary.empty:
        anomaly_series = (
            series_summary.loc[series_summary["anomaly_points"] > 0]
            .groupby("method", dropna=False)
            .size()
            .reset_index(name="anomaly_series")
        )
        method_summary = method_summary.merge(anomaly_series, on="method", how="left")
        method_summary["anomaly_series"] = method_summary["anomaly_series"].fillna(0).astype(int)

    method_summary.to_csv(output_dir / "anomaly_method_summary.csv", index=False)
    topn_per_method(kpi_summary, topn).to_csv(output_dir / "anomaly_kpi_topn.csv", index=False)
    topn_per_method(series_summary, topn).to_csv(output_dir / "anomaly_series_topn.csv", index=False)

    if hourly_parts:
        hourly = pd.concat(hourly_parts, ignore_index=True)
        hourly = (
            hourly.groupby(["method", "hour"], dropna=False)
            .agg(total_points=("total_points", "sum"), anomaly_points=("anomaly_points", "sum"))
            .reset_index()
            .sort_values(["method", "hour"])
        )
        hourly["anomaly_rate"] = hourly["anomaly_points"] / hourly["total_points"]
        hourly.to_csv(output_dir / "anomaly_hourly_counts.csv", index=False)

    if samples:
        sample = pd.concat(samples, ignore_index=True).head(sample_per_file * max(1, len(files)))
        sample.to_csv(output_dir / "anomaly_sample.csv", index=False)

    return {
        "input_files": len(files),
        "ok_files": sum(1 for item in manifest if item["status"] == "ok"),
        "total_rows_seen": int(sum(int(item.get("rows_seen", 0) or 0) for item in manifest)),
        "outputs": sorted(path.name for path in output_dir.glob("*") if path.is_file()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize large cloud anomaly results into a small transfer package.")
    parser.add_argument("--root", default=str(ROOT), help="Project root, for example /opt/bigdatapj/app.")
    parser.add_argument(
        "--anomaly-file",
        action="append",
        default=[],
        help="Anomaly CSV or Hadoop part file to summarize. Can be provided multiple times.",
    )
    parser.add_argument("--output-dir", default="results/analysis_package", help="Output directory.")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="CSV rows per chunk.")
    parser.add_argument("--topn", type=int, default=200, help="Rows kept per method for KPI and series Top-N summaries.")
    parser.add_argument("--sample-per-file", type=int, default=2000, help="Rows kept in anomaly_sample.csv per input file.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = resolve_path(root, args.output_dir)
    files = find_anomaly_files(root, args.anomaly_file)

    if not files:
        print("No anomaly result files found. Pass --anomaly-file with the exact CSV path.")
        raise SystemExit(1)

    copied = copy_small_context_files(root, output_dir)
    summary = summarize_files(files, output_dir, args.chunk_size, args.topn, args.sample_per_file)
    summary["context_files"] = copied
    (output_dir / "package_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Analysis package written to: {output_dir.as_posix()}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
