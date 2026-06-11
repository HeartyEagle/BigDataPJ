"""Check whether the Streamlit demo has the input files it needs.

This script is intended for member 6 before a presentation. It validates file
existence and required columns without scanning large CSV files fully.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.data_contract import (  # noqa: E402
    ANOMALY_COLUMNS,
    METRICS_COLUMNS,
    PERFORMANCE_COLUMNS,
    SERIES_PROFILE_COLUMNS,
)


KPI_DISTRIBUTION_COLUMNS = ["kpi_name", "series_count", "record_count"]
MISSING_TOPN_COLUMNS = ["cmdb_id", "kpi_name", "missing_rate"]
OVERVIEW_KEYS = [
    "record_count",
    "cmdb_count",
    "kpi_count",
    "series_count",
    "start_time",
    "end_time",
    "sampling_interval_sec",
]
DEMO_CASE_COLUMNS = ["cmdb_id", "kpi_name"]
ANALYSIS_METHOD_COLUMNS = ["method", "total_points", "anomaly_points", "anomaly_rate"]
ANALYSIS_SAMPLE_COLUMNS = ANOMALY_COLUMNS
BASELINE_SUMMARY_COLUMNS = ["method", "series_count", "record_count", "anomaly_count", "anomaly_rate"]
FULL_PERFORMANCE_COLUMNS = ["method", "mode", "server_num", "data_count", "anomaly_count", "runtime_sec", "throughput"]
ANOMALY_EVENT_COLUMNS = [
    "event_id",
    "cmdb_id",
    "kpi_name",
    "method",
    "start_time",
    "end_time",
    "duration",
    "anomaly_count",
    "max_score",
]


@dataclass(frozen=True)
class CheckResult:
    status: str
    label: str
    path: str
    detail: str


def display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def check_csv(path: Path, columns: list[str], label: str, required: bool, root: Path) -> CheckResult:
    relative = display_path(path, root)
    if not path.exists():
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, "missing")
    if not path.is_file():
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, "not a file")

    try:
        header = pd.read_csv(path, nrows=0)
    except Exception as exc:  # pragma: no cover - depends on corrupt local files
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, f"cannot read csv: {exc}")

    missing = [column for column in columns if column not in header.columns]
    if missing:
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, f"missing columns: {missing}")

    return CheckResult("OK", label, relative, "columns ok")


def check_any_csv(candidates: list[Path], columns: list[str], label: str, required: bool, root: Path) -> CheckResult:
    errors: list[str] = []
    for path in candidates:
        result = check_csv(path, columns, label, False, root)
        if result.status == "OK":
            return CheckResult("OK", label, result.path, result.detail)
        errors.append(f"{result.path}: {result.detail}")

    status = "FAIL" if required else "WARN"
    detail = "no usable file; " + "; ".join(errors[:4])
    if len(errors) > 4:
        detail += f"; ... {len(errors) - 4} more"
    return CheckResult(status, label, " | ".join(display_path(path, root) for path in candidates), detail)


def check_json(path: Path, keys: list[str], label: str, required: bool, root: Path) -> CheckResult:
    relative = display_path(path, root)
    if not path.exists():
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, "missing")
    if not path.is_file():
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, "not a file")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - depends on corrupt local files
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, f"cannot read json: {exc}")

    missing = [key for key in keys if key not in payload]
    if missing:
        status = "FAIL" if required else "WARN"
        return CheckResult(status, label, relative, f"missing keys: {missing}")

    return CheckResult("OK", label, relative, "keys ok")


def check_hadoop_parts(directory: Path, required: bool, root: Path) -> CheckResult:
    relative = display_path(directory, root)
    if not directory.exists():
        status = "FAIL" if required else "WARN"
        return CheckResult(status, "Hadoop part files", relative, "missing directory")

    part_files = sorted(directory.glob("part-*"))
    if not part_files:
        status = "FAIL" if required else "WARN"
        return CheckResult(status, "Hadoop part files", relative, "no part-* files")

    invalid: list[str] = []
    for part_file in part_files:
        try:
            header = pd.read_csv(part_file, nrows=0)
        except Exception as exc:  # pragma: no cover - depends on corrupt local files
            invalid.append(f"{part_file.name}: {exc}")
            continue
        missing = [column for column in ANOMALY_COLUMNS if column not in header.columns]
        if missing:
            invalid.append(f"{part_file.name}: missing {missing}")

    if invalid:
        status = "FAIL" if required else "WARN"
        return CheckResult(status, "Hadoop part files", relative, "; ".join(invalid[:3]))

    return CheckResult("OK", "Hadoop part files", relative, f"{len(part_files)} part files")


def check_anomaly_source(anomalies: Path, root: Path) -> CheckResult:
    candidates = [
        root / "results" / "analysis_package" / "anomaly_sample.csv",
        anomalies / "anomaly_iqr.csv",
        anomalies / "anomaly_ksigma.csv",
        anomalies / "anomaly_range.csv",
        anomalies / "anomaly_advanced.csv",
        anomalies / "local_iqr_full" / "anomaly_iqr.csv",
        anomalies / "local_ksigma_full" / "anomaly_ksigma.csv",
        anomalies / "local_range_full" / "anomaly_range.csv",
        anomalies / "local_advanced_full" / "anomaly_advanced.csv",
    ]
    return check_any_csv(candidates, ANALYSIS_SAMPLE_COLUMNS, "Demo anomaly source", True, root)


def check_algorithm_summary(anomalies: Path, root: Path) -> CheckResult:
    package_summary = root / "results" / "analysis_package" / "anomaly_method_summary.csv"
    package_result = check_csv(package_summary, ANALYSIS_METHOD_COLUMNS, "Algorithm summary", False, root)
    if package_result.status == "OK":
        return CheckResult("OK", "Algorithm summary", package_result.path, "analysis package summary ok")

    candidates = [
        anomalies / "local_iqr_full" / "baseline_summary.csv",
        anomalies / "local_ksigma_full" / "baseline_summary.csv",
        anomalies / "local_range_full" / "baseline_summary.csv",
        anomalies / "local_advanced_full" / "advanced_summary.csv",
        anomalies / "baseline_summary.csv",
        anomalies / "advanced_summary.csv",
    ]
    return check_any_csv(candidates, BASELINE_SUMMARY_COLUMNS, "Algorithm summary", True, root)


def check_performance_report(performance: Path, root: Path) -> CheckResult:
    standard = performance / "performance_report.csv"
    standard_result = check_csv(standard, PERFORMANCE_COLUMNS, "Performance report", False, root)
    if standard_result.status == "OK":
        return CheckResult("OK", "Performance report", standard_result.path, "standard performance report ok")

    full = performance / "full_comparison_report.csv"
    full_result = check_csv(full, FULL_PERFORMANCE_COLUMNS, "Performance report", False, root)
    if full_result.status == "OK":
        return CheckResult("OK", "Performance report", full_result.path, "full comparison report ok")

    return CheckResult(
        "FAIL",
        "Performance report",
        f"{display_path(standard, root)} | {display_path(full, root)}",
        f"no usable file; {standard_result.detail}; {full_result.detail}",
    )


def build_checks(root: Path, include_optional_as_required: bool) -> list[CheckResult]:
    profiles = root / "results" / "profiles"
    anomalies = root / "results" / "anomalies"
    performance = root / "results" / "performance"
    advanced_dir = anomalies / "local_advanced_full"
    advanced_base = advanced_dir if advanced_dir.exists() else anomalies

    optional_required = include_optional_as_required
    checks = [
        check_csv(root / "data" / "cleaned" / "metrics_cleaned.csv", METRICS_COLUMNS, "Cleaned metrics", True, root),
        check_json(profiles / "data_overview.json", OVERVIEW_KEYS, "Data overview", True, root),
        check_csv(profiles / "kpi_distribution.csv", KPI_DISTRIBUTION_COLUMNS, "KPI distribution", True, root),
        check_csv(profiles / "series_profile.csv", SERIES_PROFILE_COLUMNS, "Series profile", True, root),
        check_csv(profiles / "missing_topn.csv", MISSING_TOPN_COLUMNS, "Missing Top-N", True, root),
        check_anomaly_source(anomalies, root),
        check_algorithm_summary(anomalies, root),
        check_performance_report(performance, root),
        check_hadoop_parts(anomalies / "hadoop_iqr", optional_required, root),
        check_csv(advanced_base / "anomaly_advanced.csv", ANOMALY_COLUMNS, "Advanced anomalies", optional_required, root),
        check_csv(advanced_base / "advanced_summary.csv", ["method", "series_count", "record_count", "anomaly_count", "anomaly_rate"], "Advanced summary", optional_required, root),
        check_any_csv(
            [
                anomalies / "demo_cases.csv",
                anomalies / "local_iqr_full" / "demo_cases.csv",
                anomalies / "local_ksigma_full" / "demo_cases.csv",
                anomalies / "local_range_full" / "demo_cases.csv",
                anomalies / "local_advanced_full" / "demo_cases.csv",
                root / "results" / "analysis_package" / "context" / "demo_cases.csv",
            ],
            DEMO_CASE_COLUMNS,
            "Demo cases",
            optional_required,
            root,
        ),
        check_csv(advanced_base / "demo_cases.csv", DEMO_CASE_COLUMNS, "Advanced demo cases", optional_required, root),
    ]
    return checks


def print_report(results: list[CheckResult]) -> None:
    for result in results:
        print(f"[{result.status}] {result.label}: {result.path} - {result.detail}")

    counts = {status: sum(1 for result in results if result.status == status) for status in ["OK", "WARN", "FAIL"]}
    print(
        "Summary: "
        f"ok={counts['OK']} "
        f"warn={counts['WARN']} "
        f"fail={counts['FAIL']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check input files required by demo/app.py.")
    parser.add_argument("--root", default=str(ROOT), help="Project root. Default: repository root.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat optional advanced/Hadoop/performance files as required.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    results = build_checks(root, args.strict)
    print_report(results)

    if any(result.status == "FAIL" for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
