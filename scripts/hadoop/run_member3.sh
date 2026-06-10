#!/usr/bin/env bash
# 成员 3 Hadoop 分布式流程：数据清洗 + 统计画像
#
# 用法（在 master 节点项目根目录执行）：
#   bash scripts/hadoop/run_member3.sh
#   bash scripts/hadoop/run_member3.sh --skip-clean   # 跳过清洗，复用已有 cleaned 数据
#
# HDFS 路径说明（与服务器现状对齐）：
#   RAW   -> /bigdatapj/timeseries/raw/metric/
#   CLEAN -> /bigdatapj/timeseries/preprocess/member3_cleaned/
#   PROF  -> /bigdatapj/timeseries/preprocess/member3_profiles/
# 结果下载到本地 results/profiles/

set -euo pipefail

# ── 默认参数 ──────────────────────────────────────────────────────────────────
HDFS_RAW="/bigdatapj/timeseries/raw/metric"
HDFS_EXISTING_CLEAN="/bigdatapj/timeseries/preprocess/cleaned_job/cleaned"
HDFS_CLEAN_OUT="/bigdatapj/timeseries/preprocess/member3_cleaned"
HDFS_PROFILE_OUT="/bigdatapj/timeseries/preprocess/member3_profiles"
LOCAL_PROFILE_RAW="/tmp/member3_profiles_raw"
LOCAL_PROFILE_FINAL="results/profiles"
SKIP_CLEAN=false
NUM_REDUCERS=4

# ── 参数解析 ──────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-clean)   SKIP_CLEAN=true ; shift ;;
    --reducers)     NUM_REDUCERS="${2:?}"; shift 2 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# //'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

# ── 定位 Streaming JAR ────────────────────────────────────────────────────────
STREAMING_JAR=""
for candidate in \
  "${HADOOP_HOME:-/opt/hadoop}/share/hadoop/tools/lib/hadoop-streaming-*.jar" \
  "/opt/module/hadoop/share/hadoop/tools/lib/hadoop-streaming-*.jar" \
  "/usr/hadoop/hadoop-3.3.6/share/hadoop/tools/lib/hadoop-streaming-*.jar"
do
  match=$(ls $candidate 2>/dev/null | grep -v sources | head -1 || true)
  if [[ -n "$match" ]]; then
    STREAMING_JAR="$match"
    break
  fi
done
if [[ -z "$STREAMING_JAR" ]]; then
  echo "[ERROR] hadoop-streaming jar not found. Set HADOOP_HOME or edit this script." >&2
  exit 1
fi
echo "[INFO] Streaming jar: $STREAMING_JAR"

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# ── STEP 1：数据清洗 MapReduce ─────────────────────────────────────────────────
if [[ "$SKIP_CLEAN" == "true" ]]; then
  echo "[INFO] --skip-clean: 使用已有 cleaned 数据 ${HDFS_EXISTING_CLEAN}"
  HDFS_CLEAN_INPUT="$HDFS_EXISTING_CLEAN"
else
  echo "[INFO] === STEP 1: 数据清洗 MapReduce ==="
  hdfs dfs -rm -r -f "${HDFS_CLEAN_OUT}" || true

  hadoop jar "${STREAMING_JAR}" \
    -D mapreduce.job.name="Member3-Clean" \
    -D mapreduce.job.reduces="${NUM_REDUCERS}" \
    -D mapreduce.input.fileinputformat.input.dir.recursive=true \
    -files src/hadoop/mapper_clean.py,src/hadoop/reducer_clean.py \
    -mapper  "python3 mapper_clean.py" \
    -reducer "python3 reducer_clean.py" \
    -input   "${HDFS_RAW}" \
    -output  "${HDFS_CLEAN_OUT}"

  echo "[INFO] 清洗完成，输出："
  hdfs dfs -ls "${HDFS_CLEAN_OUT}"
  HDFS_CLEAN_INPUT="$HDFS_CLEAN_OUT"
fi

# ── STEP 2：统计画像 MapReduce ─────────────────────────────────────────────────
echo "[INFO] === STEP 2: 统计画像 MapReduce ==="
hdfs dfs -rm -r -f "${HDFS_PROFILE_OUT}" || true

hadoop jar "${STREAMING_JAR}" \
  -D mapreduce.job.name="Member3-Profile" \
  -D mapreduce.job.reduces="${NUM_REDUCERS}" \
  -files src/hadoop/mapper_profile.py,src/hadoop/reducer_profile.py \
  -mapper  "python3 mapper_profile.py" \
  -reducer "python3 reducer_profile.py" \
  -input   "${HDFS_CLEAN_INPUT}" \
  -output  "${HDFS_PROFILE_OUT}"

echo "[INFO] 画像完成，输出："
hdfs dfs -ls "${HDFS_PROFILE_OUT}"

# ── STEP 3：下载 reducer 输出 ─────────────────────────────────────────────────
echo "[INFO] === STEP 3: 下载 profiles 到本地 ==="
rm -rf "${LOCAL_PROFILE_RAW}"
mkdir -p "${LOCAL_PROFILE_RAW}"
hdfs dfs -get "${HDFS_PROFILE_OUT}/part-*" "${LOCAL_PROFILE_RAW}/"
echo "[INFO] part 文件已下载到 ${LOCAL_PROFILE_RAW}"

# ── STEP 4：生成项目标准文件 ──────────────────────────────────────────────────
echo "[INFO] === STEP 4: 生成项目标准 profiles ==="
python3 src/hadoop/postprocess_profiles.py \
  --input      "${LOCAL_PROFILE_RAW}" \
  --output-dir "${LOCAL_PROFILE_FINAL}"

echo "[INFO] 全流程完成。结果在 ${LOCAL_PROFILE_FINAL}/"
ls "${LOCAL_PROFILE_FINAL}/"
