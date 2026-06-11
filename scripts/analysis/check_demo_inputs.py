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
        check_csv(anomalies / "anomaly_iqr.csv", ANOMALY_COLUMNS, "IQR anomalies", True, root),
        check_csv(anomalies / "anomaly_ksigma.csv", ANOMALY_COLUMNS, "K-Sigma anomalies", True, root),
        check_csv(anomalies / "anomaly_range.csv", ANOMALY_COLUMNS, "Range anomalies", True, root),
        check_hadoop_parts(anomalies / "hadoop_iqr", optional_required, root),
        check_csv(performance / "performance_report.csv", PERFORMANCE_COLUMNS, "Performance report", optional_required, root),
        check_csv(advanced_base / "anomaly_advanced.csv", ANOMALY_COLUMNS, "Advanced anomalies", optional_required, root),
        check_csv(advanced_base / "advanced_summary.csv", ["method", "series_count", "record_count", "anomaly_count", "anomaly_rate"], "Advanced summary", optional_required, root),
        check_csv(anomalies / "demo_cases.csv", DEMO_CASE_COLUMNS, "Demo cases", optional_required, root),
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
