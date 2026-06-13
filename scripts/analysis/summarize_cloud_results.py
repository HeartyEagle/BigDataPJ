"""Build a small analysis package from large cloud result files.

The script is designed for server-side use. It scans large anomaly CSV files in
chunks and writes compact summaries that are practical to transfer back for
review, PPT preparation, and Streamlit demo debugging.
"""

from __future__ import annotations

import argparse
import csv
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
EXPECTED_ANOMALY_FIELD_COUNT = len(ANOMALY_COLUMNS)
RANGE_METHOD_TOKEN = "range"
POTENTIALLY_UNIT_SENSITIVE_TOKENS = [
    "usage",
    "memory",
    "bytes",
    "byte",
    "_mb",
    ".mb",
    "gc",
    "heap",
    "space",
]


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


def looks_like_headerless_anomaly_file(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                if not row:
                    continue
                return len(row) == EXPECTED_ANOMALY_FIELD_COUNT and row != ANOMALY_COLUMNS
    except OSError:
        return False
    return False


def detect_anomaly_layout(path: Path) -> str | None:
    """Return 'header' or 'headerless' for supported anomaly result files."""
    if has_columns(path, ANOMALY_COLUMNS):
        return "header"
    if looks_like_headerless_anomaly_file(path):
        return "headerless"
    return None


def expand_anomaly_path(root: Path, value: str) -> list[Path]:
    path = resolve_path(root, value)
    if path.is_dir():
        part_files = sorted(path.glob("part-*"))
        if part_files:
            return part_files
        return sorted(path.glob("*.csv"))
    return [path]


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    output: list[Path] = []
    for path in paths:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        output.append(path)
    return output


def find_anomaly_files(root: Path, explicit_files: list[str], explicit_dirs: list[str]) -> list[Path]:
    if explicit_files or explicit_dirs:
        files: list[Path] = []
        for item in explicit_dirs:
            files.extend(expand_anomaly_path(root, item))
        for item in explicit_files:
            files.extend(expand_anomaly_path(root, item))
        return unique_paths(files)

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
    hadoop_parent = root / "results" / "anomalies"
    if hadoop_parent.exists():
        for hadoop_dir in sorted(hadoop_parent.glob("hadoop*")):
            if hadoop_dir.is_dir():
                candidates.extend(sorted(hadoop_dir.glob("part-*")))
    return unique_paths([path for path in candidates if path.exists() and path.is_file()])


def read_anomaly_chunks(path: Path, layout: str, chunk_size: int):
    common_kwargs = {
        "chunksize": chunk_size,
        "on_bad_lines": "skip",
    }
    if layout == "header":
        return pd.read_csv(path, usecols=ANOMALY_COLUMNS, **common_kwargs)
    if layout == "headerless":
        return pd.read_csv(path, header=None, names=ANOMALY_COLUMNS, **common_kwargs)
    raise ValueError(f"Unsupported anomaly file layout: {layout}")


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
            score_sum=("score", "sum"),
            max_score=("score", "max"),
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
            score_sum=("score_sum", "sum"),
            max_score=("max_score", "max"),
            min_value=("min_value", "min"),
            max_value=("max_value", "max"),
        )
        .reset_index()
    )
    summary["mean_score"] = summary["score_sum"] / summary["total_points"]
    summary["anomaly_rate"] = summary["anomaly_points"] / summary["total_points"]
    output_columns = keys + [
        "total_points",
        "anomaly_points",
        "anomaly_rate",
        "max_score",
        "mean_score",
        "min_value",
        "max_value",
    ]
    return summary.loc[:, output_columns].sort_values(["anomaly_points", "max_score"], ascending=False)


def append_range_threshold_summary(container: list[pd.DataFrame], chunk: pd.DataFrame) -> None:
    range_chunk = chunk[chunk["method"].str.lower().str.contains(RANGE_METHOD_TOKEN, na=False)]
    if range_chunk.empty:
        return
    grouped = (
        range_chunk.groupby(["method", "kpi_name", "threshold_low", "threshold_high"], dropna=False)
        .agg(
            total_points=("is_anomaly", "size"),
            anomaly_points=("is_anomaly", "sum"),
            max_score=("score", "max"),
            min_value=("value", "min"),
            max_value=("value", "max"),
        )
        .reset_index()
    )
    container.append(grouped)


def merge_range_threshold_summaries(parts: list[pd.DataFrame]) -> pd.DataFrame:
    if not parts:
        return pd.DataFrame()
    data = pd.concat(parts, ignore_index=True)
    summary = (
        data.groupby(["method", "kpi_name", "threshold_low", "threshold_high"], dropna=False)
        .agg(
            total_points=("total_points", "sum"),
            anomaly_points=("anomaly_points", "sum"),
            max_score=("max_score", "max"),
            min_value=("min_value", "min"),
            max_value=("max_value", "max"),
        )
        .reset_index()
    )
    summary["anomaly_rate"] = summary["anomaly_points"] / summary["total_points"]
    return summary.sort_values(["anomaly_points", "max_score"], ascending=False)


def write_range_diagnostics(range_summary: pd.DataFrame, output_dir: Path) -> list[str]:
    if range_summary.empty:
        return []

    outputs: list[str] = []
    range_summary.to_csv(output_dir / "range_threshold_diagnostics.csv", index=False)
    outputs.append("range_threshold_diagnostics.csv")

    high = pd.to_numeric(range_summary["threshold_high"], errors="coerce")
    max_value = pd.to_numeric(range_summary["max_value"], errors="coerce")
    capped_100 = range_summary[high.le(100)]
    if not capped_100.empty:
        capped_100.to_csv(output_dir / "range_upper_100_kpis.csv", index=False)
        outputs.append("range_upper_100_kpis.csv")

    suspicious = range_summary[high.le(100) & max_value.gt(100)]
    if not suspicious.empty:
        suspicious.to_csv(output_dir / "range_suspicious_thresholds.csv", index=False)
        outputs.append("range_suspicious_thresholds.csv")

    lower_name = range_summary["kpi_name"].astype(str).str.lower()
    unit_sensitive = lower_name.apply(
        lambda value: any(token in value for token in POTENTIALLY_UNIT_SENSITIVE_TOKENS)
    )
    usage_threshold_check = range_summary[unit_sensitive & high.le(100)]
    if not usage_threshold_check.empty:
        usage_threshold_check.to_csv(output_dir / "range_usage_threshold_check.csv", index=False)
        outputs.append("range_usage_threshold_check.csv")

    return outputs


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
    range_threshold_parts: list[pd.DataFrame] = []
    hourly_parts: list[pd.DataFrame] = []
    samples: list[pd.DataFrame] = []
    manifest: list[dict[str, object]] = []

    output_dir.mkdir(parents=True, exist_ok=True)

    for path in files:
        if not path.exists() or not path.is_file():
            manifest.append({"path": path.as_posix(), "status": "missing", "size_mb": None})
            continue
        layout = detect_anomaly_layout(path)
        if layout is None:
            manifest.append(
                {
                    "path": path.as_posix(),
                    "status": "bad_columns",
                    "layout": None,
                    "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
                }
            )
            continue

        rows_seen = 0
        anomaly_rows_seen = 0
        sample_parts: list[pd.DataFrame] = []
        for chunk in read_anomaly_chunks(path, layout, chunk_size):
            chunk = normalize_chunk(chunk)
            if chunk.empty:
                continue
            rows_seen += len(chunk)
            anomaly_rows_seen += int(chunk["is_anomaly"].sum())

            append_group_summary(method_parts, chunk, ["method"])
            append_group_summary(kpi_parts, chunk, ["method", "kpi_name"])
            append_group_summary(series_parts, chunk, ["method", "cmdb_id", "kpi_name"])
            append_range_threshold_summary(range_threshold_parts, chunk)

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
                "layout": layout,
                "size_mb": round(path.stat().st_size / 1024 / 1024, 3),
                "rows_seen": rows_seen,
                "anomaly_rows_seen": anomaly_rows_seen,
            }
        )

    pd.DataFrame(manifest).to_csv(output_dir / "file_manifest.csv", index=False)

    method_summary = merge_summaries(method_parts, ["method"])
    kpi_summary = merge_summaries(kpi_parts, ["method", "kpi_name"])
    series_summary = merge_summaries(series_parts, ["method", "cmdb_id", "kpi_name"])
    range_threshold_summary = merge_range_threshold_summaries(range_threshold_parts)

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

    range_outputs = write_range_diagnostics(range_threshold_summary, output_dir)
    write_markdown_report(output_dir, method_summary, kpi_summary, series_summary, range_threshold_summary)

    return {
        "input_files": len(files),
        "ok_files": sum(1 for item in manifest if item["status"] == "ok"),
        "total_rows_seen": int(sum(int(item.get("rows_seen", 0) or 0) for item in manifest)),
        "total_anomaly_rows_seen": int(sum(int(item.get("anomaly_rows_seen", 0) or 0) for item in manifest)),
        "range_diagnostic_outputs": range_outputs,
        "outputs": sorted(path.name for path in output_dir.glob("*") if path.is_file()),
    }


def format_int(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return ""


def format_pct(value: object) -> str:
    try:
        return f"{float(value) * 100:.4f}%"
    except (TypeError, ValueError):
        return ""


def markdown_table(data: pd.DataFrame, columns: list[str], rename: dict[str, str] | None = None) -> list[str]:
    if data.empty:
        return ["无可用数据。"]
    rename = rename or {}
    lines = []
    headers = [rename.get(column, column) for column in columns]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for _, row in data.loc[:, columns].iterrows():
        values: list[str] = []
        for column in columns:
            value = row[column]
            if column in {"total_points", "anomaly_points", "anomaly_series"}:
                values.append(format_int(value))
            elif column == "anomaly_rate":
                values.append(format_pct(value))
            elif column in {"max_score", "mean_score", "min_value", "max_value", "threshold_low", "threshold_high"}:
                try:
                    values.append(f"{float(value):.6g}")
                except (TypeError, ValueError):
                    values.append(str(value))
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def write_markdown_report(
    output_dir: Path,
    method_summary: pd.DataFrame,
    kpi_summary: pd.DataFrame,
    series_summary: pd.DataFrame,
    range_threshold_summary: pd.DataFrame,
) -> None:
    lines: list[str] = [
        "# Range 修复结果分析摘要",
        "",
        "本报告由 `scripts/analysis/summarize_cloud_results.py` 在云端流式扫描大文件生成，适合传回本地用于 PPT 和 Demo 素材更新。",
        "",
        "## 1. 总体异常结果",
        "",
    ]
    method_columns = [
        column
        for column in ["method", "total_points", "anomaly_points", "anomaly_rate", "anomaly_series", "max_score"]
        if column in method_summary.columns
    ]
    lines.extend(
        markdown_table(
            method_summary,
            method_columns,
            {
                "method": "算法",
                "total_points": "总点数",
                "anomaly_points": "异常点数",
                "anomaly_rate": "异常率",
                "anomaly_series": "有异常序列数",
                "max_score": "最大分数",
            },
        )
    )

    lines.extend(["", "## 2. Range 修复检查", ""])
    if range_threshold_summary.empty:
        lines.append("没有发现 method 包含 `range` 的记录；如果本次只分析 Range 文件，请检查输入文件路径或 method 字段。")
    else:
        high = pd.to_numeric(range_threshold_summary["threshold_high"], errors="coerce")
        max_value = pd.to_numeric(range_threshold_summary["max_value"], errors="coerce")
        capped_100 = range_threshold_summary[high.le(100)]
        suspicious = range_threshold_summary[high.le(100) & max_value.gt(100)]
        lines.append(f"- Range 相关 KPI/阈值组合数：{len(range_threshold_summary):,}")
        lines.append(f"- 上界仍为 100 或更低的组合数：{len(capped_100):,}")
        lines.append(f"- 上界为 100 或更低、但实际最大值超过 100 的疑似单位误判组合数：{len(suspicious):,}")
        if suspicious.empty:
            lines.append("- 结论：从阈值分布看，之前 `usage` 类指标被误判为百分比上限 100 的问题没有明显残留。")
        else:
            lines.append("- 结论：仍存在疑似单位误判，请优先查看 `range_suspicious_thresholds.csv`。")

    lines.extend(["", "## 3. 异常最多的 KPI Top 20", ""])
    kpi_top = topn_per_method(kpi_summary, 20)
    kpi_columns = [
        column
        for column in ["method", "kpi_name", "total_points", "anomaly_points", "anomaly_rate", "max_score"]
        if column in kpi_top.columns
    ]
    lines.extend(
        markdown_table(
            kpi_top.head(20),
            kpi_columns,
            {
                "method": "算法",
                "kpi_name": "KPI",
                "total_points": "总点数",
                "anomaly_points": "异常点数",
                "anomaly_rate": "异常率",
                "max_score": "最大分数",
            },
        )
    )

    lines.extend(["", "## 4. 异常最多的序列 Top 20", ""])
    series_top = topn_per_method(series_summary, 20)
    series_columns = [
        column
        for column in ["method", "cmdb_id", "kpi_name", "total_points", "anomaly_points", "anomaly_rate", "max_score"]
        if column in series_top.columns
    ]
    lines.extend(
        markdown_table(
            series_top.head(20),
            series_columns,
            {
                "method": "算法",
                "cmdb_id": "对象",
                "kpi_name": "KPI",
                "total_points": "总点数",
                "anomaly_points": "异常点数",
                "anomaly_rate": "异常率",
                "max_score": "最大分数",
            },
        )
    )

    lines.extend(
        [
            "",
            "## 5. PPT 使用建议",
            "",
            "- 如果 Range 的异常点数明显低于旧结果 `1,153,040`，建议更新总结果页和算法差异页中的 Range 数字。",
            "- 如果 `range_suspicious_thresholds.csv` 为空，可以在答辩中说明 Range 已修正为只对明确百分比指标使用 0-100 上界。",
            "- 如果 Top 序列不再被 JVM memoryUsage 类指标刷屏，可以重新使用 Range 的 Top KPI/Top 序列作为结果展示素材。",
            "- `anomaly_sample.csv` 可作为 Demo 快速加载样本，不需要把 600MB 级 part 文件拉回本地。",
            "",
        ]
    )
    (output_dir / "range_fix_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize large cloud anomaly results into a small transfer package.")
    parser.add_argument("--root", default=str(ROOT), help="Project root, for example /opt/bigdatapj/app.")
    parser.add_argument(
        "--anomaly-file",
        action="append",
        default=[],
        help=(
            "Anomaly CSV, Hadoop part file, or directory to summarize. "
            "Can be provided multiple times. Directories are expanded to part-* files."
        ),
    )
    parser.add_argument(
        "--anomaly-dir",
        action="append",
        default=[],
        help="Directory containing Hadoop part-* files. Can be provided multiple times.",
    )
    parser.add_argument("--output-dir", default="results/analysis_package", help="Output directory.")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="CSV rows per chunk.")
    parser.add_argument("--topn", type=int, default=200, help="Rows kept per method for KPI and series Top-N summaries.")
    parser.add_argument("--sample-per-file", type=int, default=2000, help="Rows kept in anomaly_sample.csv per input file.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = resolve_path(root, args.output_dir)
    files = find_anomaly_files(root, args.anomaly_file, args.anomaly_dir)

    if not files:
        print("No anomaly result files found. Pass --anomaly-dir or --anomaly-file with the exact path.")
        raise SystemExit(1)

    copied = copy_small_context_files(root, output_dir)
    summary = summarize_files(files, output_dir, args.chunk_size, args.topn, args.sample_per_file)
    summary["context_files"] = copied
    (output_dir / "package_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Analysis package written to: {output_dir.as_posix()}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
