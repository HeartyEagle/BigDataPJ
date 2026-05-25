#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"

echo "Python:"
python --version

echo "Hadoop:"
hadoop version

echo "HDFS root check:"
hdfs dfs -ls /

echo "Required paths:"
for path in \
  "data/raw" \
  "data/cleaned" \
  "results/profiles" \
  "results/anomalies" \
  "results/performance"
do
  if [[ -e "${path}" ]]; then
    echo "[OK] ${path}"
  else
    echo "[MISS] ${path}"
  fi
done
