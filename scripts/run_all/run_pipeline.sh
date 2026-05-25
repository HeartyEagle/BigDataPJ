#!/usr/bin/env bash
set -euo pipefail

INPUT_PATH="data/raw"
CLEANED_PATH="data/cleaned/metrics_cleaned.csv"
RUN_HADOOP=0

usage() {
  cat <<'USAGE'
Usage: scripts/run_all/run_pipeline.sh [options]

Run the BigDataPJ preprocessing, profiling, baseline detection, and optionally
the Hadoop Streaming flow.

Options:
  --input-path PATH     Raw input path. Default: data/raw
  --cleaned-path PATH   Cleaned CSV output path. Default: data/cleaned/metrics_cleaned.csv
  --run-hadoop          Also run the Hadoop/HDFS workflow.
  -h, --help            Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input-path)
      INPUT_PATH="${2:?--input-path requires a path}"
      shift 2
      ;;
    --cleaned-path)
      CLEANED_PATH="${2:?--cleaned-path requires a path}"
      shift 2
      ;;
    --run-hadoop)
      RUN_HADOOP=1
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

python -m src.preprocessing.clean_metrics --input "${INPUT_PATH}" --output "${CLEANED_PATH}"
python -m src.preprocessing.build_profiles --input "${CLEANED_PATH}"
python -m src.algorithms.baseline --input "${CLEANED_PATH}" --method all

if [[ "${RUN_HADOOP}" -eq 1 ]]; then
  bash scripts/hadoop/init_hdfs.sh
  bash scripts/hadoop/upload_cleaned.sh --local-cleaned "${CLEANED_PATH}"
  bash scripts/hadoop/run_streaming_iqr.sh
  bash scripts/hadoop/download_results.sh
fi

echo "Pipeline finished. Results are under results/."
