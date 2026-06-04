"""Export result figures for PPT or report use.

The script reads only cleaned data summaries and result files. It does not
recompute profiles or anomaly detection from raw data.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.data_contract import ANOMALY_COLUMNS, PERFORMANCE_COLUMNS  # noqa: E402


CHUNK_SIZE = 100_000


def has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def read_csv_if_exists(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def anomaly_files(anomalies_dir: Path) -> list[Path]:
    files: list[Path] = []
    if anomalies_dir.exists():
        files.extend(sorted(anomalies_dir.glob("anomaly_*.csv")))
        files.extend(sorted((anomalies_dir / "hadoop_iqr").glob("part-*")))
    return files


def load_anomaly_summary(anomalies_dir: Path) -> pd.DataFrame:
    """Build an algorithm summary without loading all anomaly files at once."""

    totals: dict[str, int] = defaultdict(int)
    anomaly_points: dict[str, int] = defaultdict(int)
    anomaly_series: dict[str, set[str]] = defaultdict(set)

    for path in anomaly_files(anomalies_dir):
        try:
            header = pd.read_csv(path, nrows=0)
        except Exception:
            continue
        if not has_columns(header, ANOMALY_COLUMNS):
            continue

        for chunk in pd.read_csv(path, usecols=ANOMALY_COLUMNS, chunksize=CHUNK_SIZE):
            chunk = chunk[chunk["timestamp"].astype(str) != "timestamp"].copy()
            if chunk.empty:
                continue
            chunk["is_anomaly"] = pd.to_numeric(chunk["is_anomaly"], errors="coerce").fillna(0).astype(int)
            chunk["method"] = chunk["method"].astype(str)
            chunk["series_label"] = chunk["cmdb_id"].astype(str) + " | " + chunk["kpi_name"].astype(str)

            grouped = chunk.groupby("method")["is_anomaly"].agg(["size", "sum"])
            for method, row in grouped.iterrows():
                totals[str(method)] += int(row["size"])
                anomaly_points[str(method)] += int(row["sum"])

            anomalous = chunk.loc[chunk["is_anomaly"] > 0, ["method", "series_label"]].drop_duplicates()
            for method, method_series in anomalous.groupby("method"):
                anomaly_series[str(method)].update(method_series["series_label"].astype(str).tolist())

    rows = []
    for method in sorted(totals):
        rows.append(
            {
                "method": method,
                "total_points": totals[method],
                "anomaly_points": anomaly_points[method],
                "anomaly_series": len(anomaly_series[method]),
                "anomaly_rate": anomaly_points[method] / totals[method] if totals[method] else np.nan,
            }
        )
    return pd.DataFrame(rows)


def save_figure(fig, output_dir: Path, stem: str, output_format: str) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.{output_format}"
    if output_format == "html":
        fig.write_html(path, include_plotlyjs="cdn")
        return path

    try:
        fig.write_image(path)
        return path
    except Exception as exc:
        fallback = output_dir / f"{stem}.html"
        fig.write_html(fallback, include_plotlyjs="cdn")
        print(f"[WARN] {stem}: cannot export {output_format}: {exc}")
        print(f"[WARN] {stem}: wrote HTML fallback {fallback.as_posix()}")
        return fallback


def export_profile_figures(root: Path, output_dir: Path, output_format: str) -> list[Path]:
    profiles = root / "results" / "profiles"
    exported: list[Path] = []

    kpi = read_csv_if_exists(profiles / "kpi_distribution.csv")
    if not kpi.empty and has_columns(kpi, ["kpi_name", "record_count"]):
        plot = kpi.sort_values("record_count", ascending=False).head(30)
        fig = px.bar(plot, x="kpi_name", y="record_count", title="Top 30 KPI Record Count")
        fig.update_layout(xaxis_title="KPI", yaxis_title="Record Count")
        path = save_figure(fig, output_dir, "kpi_distribution_top30", output_format)
        if path:
            exported.append(path)

    missing = read_csv_if_exists(profiles / "missing_topn.csv")
    if not missing.empty and has_columns(missing, ["cmdb_id", "kpi_name", "missing_rate"]):
        plot = missing.copy()
        plot["series_label"] = plot["cmdb_id"].astype(str) + " | " + plot["kpi_name"].astype(str)
        plot = plot.sort_values("missing_rate", ascending=False).head(10)
        fig = px.bar(
            plot.sort_values("missing_rate"),
            x="missing_rate",
            y="series_label",
            orientation="h",
            title="Missing Rate Top 10",
        )
        fig.update_layout(xaxis_title="Missing Rate", yaxis_title="Series")
        path = save_figure(fig, output_dir, "missing_rate_top10", output_format)
        if path:
            exported.append(path)

    profile = read_csv_if_exists(profiles / "series_profile.csv")
    if not profile.empty and has_columns(profile, ["count"]):
        fig = px.histogram(profile, x="count", nbins=30, title="Series Length Distribution")
        fig.update_layout(xaxis_title="Point Count", yaxis_title="Series Count")
        path = save_figure(fig, output_dir, "series_length_distribution", output_format)
        if path:
            exported.append(path)

    if not profile.empty and has_columns(profile, ["mean", "std", "kpi_name"]):
        plot = profile.copy()
        plot["mean"] = pd.to_numeric(plot["mean"], errors="coerce")
        plot["std"] = pd.to_numeric(plot["std"], errors="coerce")
        plot = plot.dropna(subset=["mean", "std"])
        if not plot.empty:
            fig = px.scatter(
                plot,
                x="mean",
                y="std",
                color="kpi_name",
                title="Series Mean and Std Distribution",
                hover_data=["cmdb_id", "kpi_name"],
            )
            fig.update_layout(xaxis_title="Mean", yaxis_title="Std")
            path = save_figure(fig, output_dir, "series_mean_std_scatter", output_format)
            if path:
                exported.append(path)

    return exported


def export_anomaly_figures(root: Path, output_dir: Path, output_format: str) -> list[Path]:
    summary = load_anomaly_summary(root / "results" / "anomalies")
    if summary.empty:
        return []

    exported: list[Path] = []
    fig = px.bar(summary, x="method", y="anomaly_points", title="Anomaly Points by Algorithm")
    fig.update_layout(xaxis_title="Algorithm", yaxis_title="Anomaly Points")
    path = save_figure(fig, output_dir, "algorithm_anomaly_points", output_format)
    if path:
        exported.append(path)

    fig = px.bar(summary, x="method", y="anomaly_series", title="Anomaly Series by Algorithm")
    fig.update_layout(xaxis_title="Algorithm", yaxis_title="Anomaly Series")
    path = save_figure(fig, output_dir, "algorithm_anomaly_series", output_format)
    if path:
        exported.append(path)

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "algorithm_anomaly_summary.csv"
    summary.to_csv(summary_path, index=False)
    exported.append(summary_path)
    return exported


def export_performance_figures(root: Path, output_dir: Path, output_format: str) -> list[Path]:
    performance = read_csv_if_exists(root / "results" / "performance" / "performance_report.csv")
    if performance.empty or not has_columns(performance, PERFORMANCE_COLUMNS):
        return []

    performance = performance.loc[:, PERFORMANCE_COLUMNS].copy()
    performance["runtime_sec"] = pd.to_numeric(performance["runtime_sec"], errors="coerce")
    performance["throughput"] = pd.to_numeric(performance["throughput"], errors="coerce")
    performance["server_num"] = performance["server_num"].astype(str)

    exported: list[Path] = []
    fig = px.bar(
        performance,
        x="method",
        y="runtime_sec",
        color="server_num",
        barmode="group",
        title="Runtime Comparison",
    )
    fig.update_layout(xaxis_title="Method", yaxis_title="Runtime Seconds", legend_title="Server Count")
    path = save_figure(fig, output_dir, "performance_runtime", output_format)
    if path:
        exported.append(path)

    fig = px.bar(
        performance,
        x="method",
        y="throughput",
        color="server_num",
        barmode="group",
        title="Throughput Comparison",
    )
    fig.update_layout(xaxis_title="Method", yaxis_title="Throughput", legend_title="Server Count")
    path = save_figure(fig, output_dir, "performance_throughput", output_format)
    if path:
        exported.append(path)

    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Export PPT-ready figures from results files.")
    parser.add_argument("--root", default=str(ROOT), help="Project root. Default: repository root.")
    parser.add_argument("--output-dir", default="results/figures", help="Output directory for exported figures.")
    parser.add_argument(
        "--format",
        choices=["html", "png"],
        default="html",
        help="Output format. PNG requires kaleido; HTML works with the current requirements.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    exported: list[Path] = []
    exported.extend(export_profile_figures(root, output_dir, args.format))
    exported.extend(export_anomaly_figures(root, output_dir, args.format))
    exported.extend(export_performance_figures(root, output_dir, args.format))

    if not exported:
        print("No figures exported. Generate results/profiles, results/anomalies, or results/performance first.")
        return

    print("Exported files:")
    for path in exported:
        print(f"- {path.as_posix()}")


if __name__ == "__main__":
    main()
