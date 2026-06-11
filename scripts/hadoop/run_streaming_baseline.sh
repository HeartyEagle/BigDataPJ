#!/usr/bin/env bash
set -euo pipefail

INPUT="/bigdatapj/data/cleaned"
OUTPUT="/bigdatapj/results/anomalies/hadoop_iqr"
STREAMING_JAR="/opt/hadoop/share/hadoop/tools/lib/hadoop-streaming-3.3.6.jar"
PYTHON_BIN="/opt/miniconda3/envs/bigdatapj/bin/python"
METHOD="iqr"
K_SIGMA=3.0
REDUCERS=2

usage() {
  cat <<'USAGE'
Usage: scripts/hadoop/run_streaming_baseline.sh [options]

Run a Hadoop Streaming baseline anomaly detection job.

Options:
  --input PATH           HDFS cleaned input file or directory. Default: /bigdatapj/data/cleaned
  --output PATH          HDFS output directory. Default: /bigdatapj/results/anomalies/hadoop_iqr
  --streaming-jar PATH   Hadoop streaming jar path. Default: /opt/hadoop/share/hadoop/tools/lib/hadoop-streaming-3.3.6.jar
  --python-bin PATH      Python interpreter on every Hadoop node. Default: /opt/miniconda3/envs/bigdatapj/bin/python
  --method METHOD        Reducer method: iqr, ksigma, or range. Default: iqr
  --k FLOAT              K value for ksigma. Default: 3.0
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
    --method)
      METHOD="${2:?--method requires a value}"
      shift 2
      ;;
    --k)
      K_SIGMA="${2:?--k requires a number}"
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
  -D mapreduce.job.name="BigDataPJ-Hadoop-${METHOD}" \
  -D mapreduce.job.reduces="${REDUCERS}" \
  -files src/hadoop/mapper_baseline.py,src/hadoop/reducer_baseline.py \
  -mapper "${PYTHON_BIN} mapper_baseline.py" \
  -reducer "${PYTHON_BIN} reducer_baseline.py --method ${METHOD} --k ${K_SIGMA}" \
  -input "${INPUT}" \
  -output "${OUTPUT}"

hdfs dfs -ls "${OUTPUT}"
