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

## Hadoop 主流程

集群上使用：

```bash
bash scripts/run_all/run_pipeline.sh --input-path data/raw/metrics_raw.csv --run-hadoop
```

Hadoop 相关文件：

- `src/hadoop/mapper_baseline.py`
- `src/hadoop/reducer_baseline.py`
- `scripts/hadoop/run_streaming_iqr.sh`

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
