# BigDataPJ

时间序列异常检测课程项目骨架。项目目标是把原始监控指标数据清洗成统一时间序列，基于 Hadoop/HDFS/MapReduce 批量运行异常检测算法，并输出 Demo/PPT 可直接读取的统计与异常结果。

## 技术路线

```text
原始监控数据
  -> Python 清洗和统计
  -> HDFS 存储
  -> Hadoop Streaming MapReduce 按 cmdb_id + kpi_name 分组检测异常
  -> HDFS/本地 results 输出
  -> Streamlit Demo 展示
```

## 一键主流程

```bash
python -m src.preprocessing.clean_metrics --input data/raw --output data/cleaned/metrics_cleaned.csv
python -m src.preprocessing.build_profiles --input data/cleaned/metrics_cleaned.csv
python -m src.preprocessing.make_samples --input data/cleaned/metrics_cleaned.csv
python -m src.algorithms.baseline --input data/cleaned/metrics_cleaned.csv --method all
```

Baseline 脚本会生成：

```text
results/anomalies/anomaly_iqr.csv
results/anomalies/anomaly_ksigma.csv
results/anomalies/anomaly_range.csv
results/anomalies/baseline_summary.csv
results/anomalies/demo_cases.csv
```

成员 5 本地高级算法使用滚动 Robust Z-Score，按序列用历史滑动窗口 median + IQR 生成局部阈值：

```bash
python -m src.algorithms.advanced \
  --input data/sample/sample_medium.csv \
  --output-dir results/anomalies/local_advanced_full
```

Advanced 会在输出目录生成：

```text
anomaly_advanced.csv
advanced_summary.csv
demo_cases.csv
```

当前本地测试结果：

```text
input: data/sample/sample_medium.csv
series=100 rows=280811 anomalies=3873
```

## Hadoop 主流程

集群上使用。全量 cleaned 数据在 HDFS 上按 Hadoop 输出目录保存，当前约定为 `/bigdatapj/data/cleaned`，目录内包含 `_SUCCESS` 和 `part-*`：

```bash
bash scripts/hadoop/run_streaming_baseline.sh \
  --input /bigdatapj/data/cleaned \
  --output /bigdatapj/results/anomalies/hadoop_iqr
```

如果需要给单机 baseline 或性能对比使用，已将同一份 HDFS cleaned 合并成本地 CSV：

```text
data/cleaned/metrics_cleaned.csv
```

复现合并命令：

```bash
mkdir -p data/cleaned
{ printf "timestamp,cmdb_id,kpi_name,value\n"; hdfs dfs -cat /bigdatapj/data/cleaned/part-* | sed 's/\t$//'; } > data/cleaned/metrics_cleaned.csv
```

调试样本由 `make_samples.py` 分块扫描生成，不会一次性读入 1.9G 全量 CSV：

```bash
python -m src.preprocessing.make_samples --input data/cleaned/metrics_cleaned.csv --chunksize 500000
```

当前样本：

```text
data/sample/sample_small.csv   10 series, 27060 rows
data/sample/sample_medium.csv  100 series, 280811 rows
```

Hadoop 相关文件：

- `src/hadoop/mapper_baseline.py`
- `src/hadoop/reducer_baseline.py`
- `src/hadoop/reducer_advanced.py`
- `scripts/hadoop/run_streaming_baseline.sh`
- `scripts/hadoop/run_streaming_advanced.sh`

Hadoop-IQR 和 Hadoop-Advanced 复用同一个 mapper；区别在 reducer：

```text
Local IQR       -> src.algorithms.baseline --method iqr
Hadoop Baseline -> mapper_baseline.py + reducer_baseline.py --method iqr|ksigma|range
Local Advanced  -> src.algorithms.advanced
Hadoop Advanced -> mapper_baseline.py + reducer_advanced.py
```

Hadoop baseline 也可以切换方法：

```bash
bash scripts/hadoop/run_streaming_baseline.sh \
  --input /bigdatapj/data/cleaned \
  --output /bigdatapj/results/anomalies/hadoop_ksigma \
  --method ksigma
```

一键跑完整全量对比：

```bash
bash scripts/run_all/run_full_comparison.sh
```

输出汇总：

```text
results/performance/full_comparison_report.csv
```

如果需要额外文本日志，可加 `--time-log results/performance/full_comparison_summary.txt`。

## 核心数据接口

性能指标清洗后统一为：

```text
timestamp, cmdb_id, kpi_name, value
```

业务指标清洗后统一为：

```text
timestamp, service, rr, sr, count, mrt
```

异常结果统一为：

```text
timestamp, cmdb_id, kpi_name, value, method, is_anomaly, score, threshold_low, threshold_high
```

详细分工、每个人需要修改的文件、交付物和验收标准见：

- docs/组长交付说明.md
- docs/分工任务清单.md
- docs/环境部署.md
- docs/使用说明.md
- docs/项目文档.md
- 分工2.md
