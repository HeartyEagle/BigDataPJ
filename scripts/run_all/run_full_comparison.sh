#!/usr/bin/env bash
set -euo pipefail

LOCAL_INPUT="data/cleaned/metrics_cleaned.csv"
HDFS_INPUT="/bigdatapj/data/cleaned"
PYTHON_BIN="/opt/miniconda3/envs/bigdatapj/bin/python"
REPORT_PATH="results/performance/full_comparison_report.csv"
TIME_LOG=""
LOCAL_OUTPUT_BASE="results/anomalies"
LOCAL_ADVANCED_DIR="${LOCAL_OUTPUT_BASE}/local_advanced_full"
LOCAL_ADVANCED_OUTPUT="${LOCAL_ADVANCED_DIR}/anomaly_advanced.csv"
HDFS_OUTPUT_BASE="/bigdatapj/results/anomalies"
HADOOP_REDUCERS=2
RUN_LOCAL_BASELINE=1
RUN_HADOOP_BASELINE=1
RUN_LOCAL_ADVANCED=1
RUN_HADOOP_ADVANCED=1

usage() {
  cat <<'USAGE'
Usage: scripts/run_all/run_full_comparison.sh [options]

Run full-data comparisons:
  Local IQR/K-Sigma/Range vs Hadoop IQR/K-Sigma/Range
  Local Advanced vs Hadoop Advanced

Options:
  --local-input PATH           Local full cleaned CSV. Default: data/cleaned/metrics_cleaned.csv
  --hdfs-input PATH            HDFS full cleaned directory. Default: /bigdatapj/data/cleaned
  --python-bin PATH            Local Python interpreter. Default: /opt/miniconda3/envs/bigdatapj/bin/python
  --report PATH                CSV summary output. Default: results/performance/full_comparison_report.csv
  --time-log PATH              Optional text summary output. Default: disabled
  --local-output-base PATH     Local anomaly output parent. Default: results/anomalies
  --hdfs-output-base PATH      HDFS output parent. Default: /bigdatapj/results/anomalies
  --hadoop-reducers N          Reducer tasks for all Hadoop jobs. Default: 2
  --skip-local-baseline        Do not run Local IQR/K-Sigma/Range.
  --skip-hadoop-baseline       Do not run Hadoop IQR/K-Sigma/Range.
  --skip-local-advanced        Do not run Local Advanced.
  --skip-hadoop-advanced       Do not run Hadoop Advanced.
  -h, --help                   Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local-input)
      LOCAL_INPUT="${2:?--local-input requires a path}"
      shift 2
      ;;
    --hdfs-input)
      HDFS_INPUT="${2:?--hdfs-input requires a path}"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="${2:?--python-bin requires a path}"
      shift 2
      ;;
    --report)
      REPORT_PATH="${2:?--report requires a path}"
      shift 2
      ;;
    --time-log)
      TIME_LOG="${2:?--time-log requires a path}"
      shift 2
      ;;
    --local-output-base)
      LOCAL_OUTPUT_BASE="${2:?--local-output-base requires a path}"
      LOCAL_ADVANCED_DIR="${LOCAL_OUTPUT_BASE}/local_advanced_full"
      LOCAL_ADVANCED_OUTPUT="${LOCAL_ADVANCED_DIR}/anomaly_advanced.csv"
      shift 2
      ;;
    --hdfs-output-base)
      HDFS_OUTPUT_BASE="${2:?--hdfs-output-base requires a path}"
      shift 2
      ;;
    --hadoop-reducers)
      HADOOP_REDUCERS="${2:?--hadoop-reducers requires a number}"
      shift 2
      ;;
    --skip-local-baseline)
      RUN_LOCAL_BASELINE=0
      shift
      ;;
    --skip-hadoop-baseline)
      RUN_HADOOP_BASELINE=0
      shift
      ;;
    --skip-local-advanced)
      RUN_LOCAL_ADVANCED=0
      shift
      ;;
    --skip-hadoop-advanced)
      RUN_HADOOP_ADVANCED=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

mkdir -p "$(dirname "${REPORT_PATH}")" "${LOCAL_OUTPUT_BASE}"
if [[ -n "${TIME_LOG}" ]]; then
  mkdir -p "$(dirname "${TIME_LOG}")"
fi

printf "method,mode,server_num,data_count,anomaly_count,runtime_sec,throughput,output_path\n" > "${REPORT_PATH}"
if [[ -n "${TIME_LOG}" ]]; then
  {
    echo "Full comparison started at $(date '+%F %T')"
    echo "local_input=${LOCAL_INPUT}"
    echo "hdfs_input=${HDFS_INPUT}"
    echo
  } > "${TIME_LOG}"
fi

csv_stats() {
  local path="$1"
  awk -F, '
    $1=="timestamp" {next}
    {rows++; anomalies+=$6}
    END {printf "%d,%d", rows+0, anomalies+0}
  ' "${path}"
}

hdfs_stats() {
  local path="$1"
  hdfs dfs -cat "${path}"/part-* 2>/dev/null | awk -F, '
    $1=="timestamp" {next}
    {rows++; anomalies+=$6}
    END {printf "%d,%d", rows+0, anomalies+0}
  '
}

reset_local_output_dir() {
  local path="$1"
  case "${path}" in
    ""|"/"|".")
      echo "Refusing to remove unsafe output directory: ${path}" >&2
      exit 2
      ;;
  esac
  rm -rf "${path}"
  mkdir -p "${path}"
}

append_report() {
  local method="$1"
  local mode="$2"
  local server_num="$3"
  local data_count="$4"
  local anomaly_count="$5"
  local runtime_sec="$6"
  local output_path="$7"
  "${PYTHON_BIN}" - "$method" "$mode" "$server_num" "$data_count" "$anomaly_count" "$runtime_sec" "$output_path" "${REPORT_PATH}" <<'PY'
import csv
import sys

method, mode, server_num, data_count, anomaly_count, runtime_sec, output_path, report_path = sys.argv[1:]
data_count_i = int(data_count)
runtime_f = float(runtime_sec)
throughput = data_count_i / runtime_f if runtime_f > 0 else 0.0
with open(report_path, "a", newline="") as fh:
    writer = csv.writer(fh)
    writer.writerow([method, mode, server_num, data_count_i, int(anomaly_count), f"{runtime_f:.6f}", f"{throughput:.6f}", output_path])
PY
}

run_timed() {
  local label="$1"
  shift
  echo "== ${label} =="
  if [[ -n "${TIME_LOG}" ]]; then
    echo "== ${label} ==" >> "${TIME_LOG}"
  fi
  local start
  local end
  start="$(date +%s)"
  "$@"
  end="$(date +%s)"
  local elapsed=$((end - start))
  echo "${label} seconds=${elapsed}"
  if [[ -n "${TIME_LOG}" ]]; then
    echo "${label} seconds=${elapsed}" >> "${TIME_LOG}"
  fi
  RUNTIME_SEC="${elapsed}"
}

record_local_result() {
  local method="$1"
  local output_file="$2"
  local runtime="$3"
  local stats
  stats="$(csv_stats "${output_file}")"
  local rows="${stats%,*}"
  local anomalies="${stats#*,}"
  append_report "${method}" "local" "1" "${rows}" "${anomalies}" "${runtime}" "${output_file}"
  if [[ -n "${TIME_LOG}" ]]; then
    echo "${method} local rows=${rows} anomalies=${anomalies}" >> "${TIME_LOG}"
  fi
}

record_hadoop_result() {
  local method="$1"
  local output_dir="$2"
  local runtime="$3"
  local stats
  stats="$(hdfs_stats "${output_dir}")"
  local rows="${stats%,*}"
  local anomalies="${stats#*,}"
  append_report "${method}" "hadoop" "3" "${rows}" "${anomalies}" "${runtime}" "${output_dir}"
  if [[ -n "${TIME_LOG}" ]]; then
    echo "${method} hadoop rows=${rows} anomalies=${anomalies}" >> "${TIME_LOG}"
  fi
}

if [[ "${RUN_LOCAL_BASELINE}" -eq 1 ]]; then
  for method in iqr ksigma range; do
    out_dir="${LOCAL_OUTPUT_BASE}/local_${method}_full"
    reset_local_output_dir "${out_dir}"
    run_timed "Local-${method}" \
      "${PYTHON_BIN}" -m src.algorithms.baseline \
        --input "${LOCAL_INPUT}" \
        --output-dir "${out_dir}" \
        --method "${method}"
    case "${method}" in
      iqr) output_file="${out_dir}/anomaly_iqr.csv" ;;
      ksigma) output_file="${out_dir}/anomaly_ksigma.csv" ;;
      range) output_file="${out_dir}/anomaly_range.csv" ;;
    esac
    record_local_result "${method}" "${output_file}" "${RUNTIME_SEC}"
  done
fi

if [[ "${RUN_HADOOP_BASELINE}" -eq 1 ]]; then
  for method in iqr ksigma range; do
    output_dir="${HDFS_OUTPUT_BASE}/hadoop_${method}_full"
    run_timed "Hadoop-${method}" \
      bash scripts/hadoop/run_streaming_baseline.sh \
        --input "${HDFS_INPUT}" \
        --output "${output_dir}" \
        --method "${method}" \
        --reducers "${HADOOP_REDUCERS}"
    record_hadoop_result "${method}" "${output_dir}" "${RUNTIME_SEC}"
  done
fi

if [[ "${RUN_LOCAL_ADVANCED}" -eq 1 ]]; then
  reset_local_output_dir "${LOCAL_ADVANCED_DIR}"
  run_timed "Local-advanced" \
    "${PYTHON_BIN}" -m src.algorithms.advanced \
      --input "${LOCAL_INPUT}" \
      --output-dir "${LOCAL_ADVANCED_DIR}"
  record_local_result "advanced" "${LOCAL_ADVANCED_OUTPUT}" "${RUNTIME_SEC}"
fi

if [[ "${RUN_HADOOP_ADVANCED}" -eq 1 ]]; then
  output_dir="${HDFS_OUTPUT_BASE}/hadoop_advanced_full"
  run_timed "Hadoop-advanced" \
    bash scripts/hadoop/run_streaming_advanced.sh \
      --input "${HDFS_INPUT}" \
      --output "${output_dir}" \
      --reducers "${HADOOP_REDUCERS}"
  record_hadoop_result "advanced" "${output_dir}" "${RUNTIME_SEC}"
fi

if [[ -n "${TIME_LOG}" ]]; then
  {
    echo
    echo "CSV report: ${REPORT_PATH}"
    echo "Finished at $(date '+%F %T')"
  } >> "${TIME_LOG}"
fi

echo "Full comparison finished."
echo "Report: ${REPORT_PATH}"
if [[ -n "${TIME_LOG}" ]]; then
  echo "Time log: ${TIME_LOG}"
fi
