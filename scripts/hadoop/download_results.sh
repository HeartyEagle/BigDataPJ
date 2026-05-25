#!/usr/bin/env bash
set -euo pipefail

HDFS_OUTPUT="/bigdatapj/results/anomalies/hadoop_iqr"
LOCAL_OUTPUT_DIR="results/anomalies/hadoop_iqr"

usage() {
  cat <<'USAGE'
Usage: scripts/hadoop/download_results.sh [options]

Download Hadoop Streaming part files from HDFS to a local results directory.

Options:
  --hdfs-output PATH        HDFS output directory. Default: /bigdatapj/results/anomalies/hadoop_iqr
  --local-output-dir PATH   Local output directory. Default: results/anomalies/hadoop_iqr
  -h, --help                Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hdfs-output)
      HDFS_OUTPUT="${2:?--hdfs-output requires a path}"
      shift 2
      ;;
    --local-output-dir)
      LOCAL_OUTPUT_DIR="${2:?--local-output-dir requires a path}"
      shift 2
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

mkdir -p "${LOCAL_OUTPUT_DIR}"
hdfs dfs -get -f "${HDFS_OUTPUT}/part-*" "${LOCAL_OUTPUT_DIR}"

echo "Downloaded Hadoop result parts to ${LOCAL_OUTPUT_DIR}"
