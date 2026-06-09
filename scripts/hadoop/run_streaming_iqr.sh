#!/usr/bin/env bash
set -euo pipefail

INPUT="/bigdatapj/data/cleaned/metrics_cleaned.csv"
OUTPUT="/bigdatapj/results/anomalies/hadoop_iqr"
STREAMING_JAR="/usr/local/hadoop/share/hadoop/tools/lib/hadoop-streaming.jar"

usage() {
  cat <<'USAGE'
Usage: scripts/hadoop/run_streaming_iqr.sh [options]

Run the Hadoop Streaming IQR anomaly detection job.

Options:
  --input PATH           HDFS input CSV. Default: /bigdatapj/data/cleaned/metrics_cleaned.csv
  --output PATH          HDFS output directory. Default: /bigdatapj/results/anomalies/hadoop_iqr
  --streaming-jar PATH   Hadoop streaming jar path. Default: /usr/local/hadoop/share/hadoop/tools/lib/hadoop-streaming.jar
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
  -D mapreduce.job.name=BigDataPJ-Hadoop-IQR \
  -D mapreduce.job.reduces=2 \
  -files src/hadoop/mapper_baseline.py,src/hadoop/reducer_baseline.py \
  -mapper "python3 mapper_baseline.py" \
  -reducer "python3 reducer_baseline.py" \
  -input "${INPUT}" \
  -output "${OUTPUT}"

hdfs dfs -ls "${OUTPUT}"
