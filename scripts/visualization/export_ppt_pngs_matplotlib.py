"""Export PPT-ready PNG figures with pandas and matplotlib only.

This script is useful when Plotly is unavailable in the selected environment.
It reads the compact results already copied locally and creates static PNG
figures that can be inserted into PowerPoint directly.
"""

from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442"]
DPI = 200


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or not path.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def has_columns(df: pd.DataFrame, columns: list[str]) -> bool:
    return all(column in df.columns for column in columns)


def setup_ax(ax: plt.Axes, title: str, xlabel: str = "", ylabel: str = "") -> None:
    ax.set_title(title, fontsize=13, pad=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.25, linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def shorten(value: object, width: int = 72) -> str:
    return textwrap.shorten(str(value), width=width, placeholder="...")


def save(fig: plt.Figure, output_dir: Path, stem: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def bar_vertical(df: pd.DataFrame, x: str, y: str, title: str, xlabel: str, ylabel: str, output_dir: Path, stem: str) -> Path:
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(df[x].astype(str), pd.to_numeric(df[y], errors="coerce"), color=PALETTE[0])
    setup_ax(ax, title, xlabel, ylabel)
    ax.tick_params(axis="x", labelrotation=60, labelsize=8)
    for label in ax.get_xticklabels():
        label.set_horizontalalignment("right")
    return save(fig, output_dir, stem)


def bar_horizontal(
    df: pd.DataFrame,
    label: str,
    value: str,
    title: str,
    xlabel: str,
    ylabel: str,
    output_dir: Path,
    stem: str,
    width: int = 80,
) -> Path:
    plot = df.copy()
    plot[label] = plot[label].map(lambda item: shorten(item, width))
    plot[value] = pd.to_numeric(plot[value], errors="coerce")
    plot = plot.dropna(subset=[value]).sort_values(value)

    height = max(4.8, min(10, 0.35 * len(plot) + 2.0))
    fig, ax = plt.subplots(figsize=(12, height))
    ax.barh(plot[label], plot[value], color=PALETTE[1])
    setup_ax(ax, title, xlabel, ylabel)
    ax.grid(axis="x", alpha=0.25, linewidth=0.8)
    ax.grid(axis="y", alpha=0)
    return save(fig, output_dir, stem)


def export_profile_figures(root: Path, output_dir: Path) -> list[Path]:
    profiles = root / "results" / "profiles"
    exported: list[Path] = []

    kpi = read_csv(profiles / "kpi_distribution.csv")
    if not kpi.empty and has_columns(kpi, ["kpi_name", "record_count"]):
        plot = kpi.sort_values("record_count", ascending=False).head(30)
        exported.append(
            bar_vertical(plot, "kpi_name", "record_count", "Top 30 KPI Record Count", "KPI", "Record Count", output_dir, "kpi_distribution_top30")
        )

    missing = read_csv(profiles / "missing_topn.csv")
    if not missing.empty and has_columns(missing, ["cmdb_id", "kpi_name", "missing_rate"]):
        plot = missing.copy()
        plot["series_label"] = plot["cmdb_id"].astype(str) + " | " + plot["kpi_name"].astype(str)
        plot = plot.sort_values("missing_rate", ascending=False).head(10)
        exported.append(
            bar_horizontal(plot, "series_label", "missing_rate", "Missing Rate Top 10", "Missing Rate", "Series", output_dir, "missing_rate_top10")
        )

    profile = read_csv(profiles / "series_profile.csv")
    if not profile.empty and has_columns(profile, ["count"]):
        fig, ax = plt.subplots(figsize=(9, 5.5))
        counts = pd.to_numeric(profile["count"], errors="coerce").dropna()
        ax.hist(counts, bins=30, color=PALETTE[2], edgecolor="white")
        setup_ax(ax, "Series Length Distribution", "Point Count", "Series Count")
        exported.append(save(fig, output_dir, "series_length_distribution"))

    if not profile.empty and has_columns(profile, ["mean", "std", "kpi_name"]):
        plot = profile.copy()
        plot["mean"] = pd.to_numeric(plot["mean"], errors="coerce")
        plot["std"] = pd.to_numeric(plot["std"], errors="coerce")
        plot = plot.dropna(subset=["mean", "std"])
        if not plot.empty:
            fig, ax = plt.subplots(figsize=(9, 6))
            ax.scatter(plot["mean"], plot["std"], s=10, alpha=0.55, color=PALETTE[0], edgecolors="none")
            setup_ax(ax, "Series Mean and Std Distribution", "Mean", "Std")
            ax.set_xscale("symlog", linthresh=1)
            ax.set_yscale("symlog", linthresh=1)
            exported.append(save(fig, output_dir, "series_mean_std_scatter"))

    return exported


def export_anomaly_figures(root: Path, output_dir: Path) -> list[Path]:
    package = root / "results" / "analysis_package"
    exported: list[Path] = []

    summary = read_csv(package / "anomaly_method_summary.csv")
    if not summary.empty and has_columns(summary, ["method", "anomaly_points", "anomaly_rate"]):
        summary = summary.copy()
        summary["anomaly_rate_percent"] = pd.to_numeric(summary["anomaly_rate"], errors="coerce") * 100
        exported.append(
            bar_vertical(summary, "method", "anomaly_points", "Anomaly Points by Algorithm", "Algorithm", "Anomaly Points", output_dir, "algorithm_anomaly_points")
        )
        exported.append(
            bar_vertical(summary, "method", "anomaly_rate_percent", "Anomaly Rate by Algorithm", "Algorithm", "Anomaly Rate (%)", output_dir, "algorithm_anomaly_rate")
        )

    series = read_csv(package / "anomaly_series_topn.csv")
    if not series.empty and has_columns(series, ["method", "cmdb_id", "kpi_name", "anomaly_points"]):
        series_counts = series.groupby("method", as_index=False).size().rename(columns={"size": "top_anomaly_series"})
        if not series_counts.empty:
            exported.append(
                bar_vertical(
                    series_counts,
                    "method",
                    "top_anomaly_series",
                    "Top-N Anomaly Series by Algorithm",
                    "Algorithm",
                    "Series Count",
                    output_dir,
                    "algorithm_anomaly_series",
                )
            )

        plot = series.sort_values("anomaly_points", ascending=False).head(20).copy()
        plot["label"] = plot["method"].astype(str) + " | " + plot["cmdb_id"].astype(str) + " | " + plot["kpi_name"].astype(str)
        exported.append(
            bar_horizontal(plot, "label", "anomaly_points", "Top 20 Anomaly Series", "Anomaly Points", "Method | Series", output_dir, "anomaly_series_top20")
        )

    kpi = read_csv(package / "anomaly_kpi_topn.csv")
    if not kpi.empty and has_columns(kpi, ["method", "kpi_name", "anomaly_points"]):
        plot = kpi.sort_values("anomaly_points", ascending=False).head(20).copy()
        plot["label"] = plot["method"].astype(str) + " | " + plot["kpi_name"].astype(str)
        exported.append(
            bar_horizontal(plot, "label", "anomaly_points", "Top 20 Anomaly KPI", "Anomaly Points", "Method | KPI", output_dir, "anomaly_kpi_top20")
        )

    return exported


def performance_path(root: Path) -> Path | None:
    for path in [
        root / "results" / "performance" / "performance_report.csv",
        root / "results" / "performance" / "full_comparison_report.csv",
    ]:
        if path.exists() and path.is_file():
            return path
    return None


def export_performance_figures(root: Path, output_dir: Path) -> list[Path]:
    path = performance_path(root)
    if path is None:
        return []

    performance = read_csv(path)
    if performance.empty or not has_columns(performance, ["method", "server_num", "runtime_sec", "throughput"]):
        return []

    performance = performance.copy()
    performance["method_label"] = performance["method"].astype(str)
    if "mode" in performance.columns:
        performance["method_label"] = performance["method"].astype(str) + " | " + performance["mode"].astype(str)

    exported: list[Path] = []
    plot = performance.sort_values(["method", "server_num"])
    exported.append(
        bar_vertical(plot, "method_label", "runtime_sec", "Runtime Comparison", "Method | Mode", "Runtime Seconds", output_dir, "performance_runtime")
    )
    exported.append(
        bar_vertical(plot, "method_label", "throughput", "Throughput Comparison", "Method | Mode", "Throughput", output_dir, "performance_throughput")
    )
    return exported


def main() -> None:
    parser = argparse.ArgumentParser(description="Export PPT-ready PNG figures with matplotlib.")
    parser.add_argument("--root", default=str(ROOT), help="Project root. Default: repository root.")
    parser.add_argument("--output-dir", default="results/figures_png", help="Output directory for PNG figures.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir

    exported: list[Path] = []
    exported.extend(export_profile_figures(root, output_dir))
    exported.extend(export_anomaly_figures(root, output_dir))
    exported.extend(export_performance_figures(root, output_dir))

    if not exported:
        print("No PNG figures exported.")
        return

    print("Exported PNG files:")
    for path in exported:
        print(f"- {path.as_posix()}")


if __name__ == "__main__":
    main()
