#!/usr/bin/env bash
set -euo pipefail

INPUT="/bigdatapj/data/cleaned"
OUTPUT="/bigdatapj/results/anomalies/hadoop_advanced"
STREAMING_JAR="/opt/hadoop/share/hadoop/tools/lib/hadoop-streaming-3.3.6.jar"
PYTHON_BIN="/opt/miniconda3/envs/bigdatapj/bin/python"
WINDOW=60
MIN_PERIODS=30
Z_THRESHOLD=3.5
REDUCERS=2

usage() {
  cat <<'USAGE'
Usage: scripts/hadoop/run_streaming_advanced.sh [options]

Run the Hadoop Streaming advanced anomaly detection job.

Options:
  --input PATH           HDFS cleaned input file or directory. Default: /bigdatapj/data/cleaned
  --output PATH          HDFS output directory. Default: /bigdatapj/results/anomalies/hadoop_advanced
  --streaming-jar PATH   Hadoop streaming jar path. Default: /opt/hadoop/share/hadoop/tools/lib/hadoop-streaming-3.3.6.jar
  --python-bin PATH      Python interpreter on every Hadoop node. Default: /opt/miniconda3/envs/bigdatapj/bin/python
  --window N             Rolling window size. Default: 60
  --min-periods N        Minimum historical points before local thresholds. Default: 30
  --z-threshold FLOAT    Robust z-score threshold. Default: 3.5
  --reducers N           Number of reducer tasks. Default: 2
  -h, --help             Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUT="${2:?--input requires a path}"
      shift 2
      ;;
    --output)
      OUTPUT="${2:?--output requires a path}"
      shift 2
      ;;
    --streaming-jar)
      STREAMING_JAR="${2:?--streaming-jar requires a path}"
      shift 2
      ;;
    --python-bin)
      PYTHON_BIN="${2:?--python-bin requires a path}"
      shift 2
      ;;
    --window)
      WINDOW="${2:?--window requires a number}"
      shift 2
      ;;
    --min-periods)
      MIN_PERIODS="${2:?--min-periods requires a number}"
      shift 2
      ;;
    --z-threshold)
      Z_THRESHOLD="${2:?--z-threshold requires a number}"
      shift 2
      ;;
    --reducers)
      REDUCERS="${2:?--reducers requires a number}"
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

hdfs dfs -rm -r -f "${OUTPUT}"

hadoop jar "${STREAMING_JAR}" \
  -D mapreduce.job.name=BigDataPJ-Hadoop-Advanced \
  -D mapreduce.job.reduces="${REDUCERS}" \
  -files src/hadoop/mapper_baseline.py,src/hadoop/reducer_advanced.py \
  -mapper "${PYTHON_BIN} mapper_baseline.py" \
  -reducer "${PYTHON_BIN} reducer_advanced.py --window ${WINDOW} --min-periods ${MIN_PERIODS} --z-threshold ${Z_THRESHOLD}" \
  -input "${INPUT}" \
  -output "${OUTPUT}"

hdfs dfs -ls "${OUTPUT}"
