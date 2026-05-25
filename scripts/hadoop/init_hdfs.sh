#!/usr/bin/env bash
set -euo pipefail

BASE="/bigdatapj"

usage() {
  cat <<'USAGE'
Usage: scripts/hadoop/init_hdfs.sh [options]

Create the HDFS project directories used by BigDataPJ.

Options:
  --base PATH   HDFS base directory. Default: /bigdatapj
  -h, --help    Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)
      BASE="${2:?--base requires a path}"
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

hdfs dfs -mkdir -p "${BASE}/raw"
hdfs dfs -mkdir -p "${BASE}/cleaned"
hdfs dfs -mkdir -p "${BASE}/results/profiles"
hdfs dfs -mkdir -p "${BASE}/results/anomalies"
hdfs dfs -mkdir -p "${BASE}/results/performance"

hdfs dfs -ls "${BASE}"
