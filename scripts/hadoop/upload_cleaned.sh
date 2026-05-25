#!/usr/bin/env bash
set -euo pipefail

LOCAL_CLEANED="data/cleaned/metrics_cleaned.csv"
HDFS_CLEANED="/bigdatapj/cleaned/metrics_cleaned.csv"

usage() {
  cat <<'USAGE'
Usage: scripts/hadoop/upload_cleaned.sh [options]

Upload the cleaned metrics CSV to HDFS for Hadoop Streaming.

Options:
  --local-cleaned PATH   Local cleaned CSV. Default: data/cleaned/metrics_cleaned.csv
  --hdfs-cleaned PATH    HDFS destination CSV. Default: /bigdatapj/cleaned/metrics_cleaned.csv
  -h, --help             Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --local-cleaned)
      LOCAL_CLEANED="${2:?--local-cleaned requires a path}"
      shift 2
      ;;
    --hdfs-cleaned)
      HDFS_CLEANED="${2:?--hdfs-cleaned requires a path}"
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

hdfs dfs -mkdir -p "$(dirname "${HDFS_CLEANED}")"
hdfs dfs -put -f "${LOCAL_CLEANED}" "${HDFS_CLEANED}"
hdfs dfs -ls "${HDFS_CLEANED}"
