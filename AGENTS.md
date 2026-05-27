# AGENTS.md

本文件给后续 Codex / 开发代理提供项目上下文与协作约定。请在修改代码前先阅读本文件以及 `README.md`、`docs/分工任务清单.md`。

## 项目概览

本项目是“大数据平台技术”课程项目：面向运维监控指标的时间序列异常检测系统。

目标链路：

```text
原始监控数据
  -> Python 数据清洗与统计画像
  -> HDFS 存储
  -> Hadoop Streaming / MapReduce 异常检测
  -> results/ 结果汇总
  -> Streamlit Demo 可视化展示
```

项目要求重点：

- 5000+ 条时间序列
- 3GB+ 数据规模
- 60 秒采样频率
- 三台服务器 Hadoop 集群
- 15–30 分钟报告与系统演示

## 核心数据约定

性能指标统一字段：

```text
timestamp, cmdb_id, kpi_name, value
```

一条时间序列定义为：

```text
cmdb_id + kpi_name
```

异常检测结果统一字段：

```text
timestamp, cmdb_id, kpi_name, value, method, is_anomaly, score, threshold_low, threshold_high
```

字段常量维护在：

```text
src/utils/data_contract.py
```

修改字段前必须同步文档、Demo 和上下游代码。

## 目录说明

```text
configs/                 全局配置
data/raw/                原始/导入后的数据，小样本可放这里，大数据不要提交 Git
data/cleaned/            清洗后数据
data/sample/             调试样本
src/preprocessing/       数据清洗、序列构造、统计画像
src/algorithms/          IQR / K-Sigma / Range 等算法
src/hadoop/              Hadoop Streaming mapper/reducer
src/distributed/         分片与并行辅助逻辑
src/utils/               公共字段和 IO 工具
scripts/deploy/          环境检查脚本
scripts/hadoop/          HDFS / Hadoop 作业脚本
scripts/run_all/         主流程脚本
results/profiles/        数据统计画像输出
results/anomalies/       异常检测结果输出
results/performance/     性能测试输出
demo/                    Streamlit 可视化 Demo
docs/                    项目文档
```

## 常用命令

本地最小流程：

```bash
python -m src.preprocessing.clean_metrics --input data/raw --output data/cleaned/metrics_cleaned.csv
python -m src.preprocessing.build_profiles --input data/cleaned/metrics_cleaned.csv
python -m src.algorithms.baseline --input data/cleaned/metrics_cleaned.csv --method all
streamlit run demo/app.py
```

Linux/Hadoop 集群流程：

```bash
bash scripts/run_all/run_pipeline.sh --input-path data/raw/metrics_raw.csv --run-hadoop
```

只启动 Demo：

```bash
streamlit run demo/app.py
```

## 代码现状提醒

- 当前仓库主要是项目骨架。
- `data/` 和 `results/` 下默认只有 `.gitkeep`，真实数据和结果通常不在仓库里。
- Demo 必须对缺失结果文件做容错提示，不能因为某个 CSV/JSON 不存在就崩溃。
- Hadoop 脚本主要面向 Linux 集群环境；Windows 本地一般只做 Python 和 Streamlit 调试。

## 成员 6 相关重点

当前用户负责成员 6：Demo / 可视化 / PPT / 文档。

成员 6 主要修改：

```text
demo/app.py
demo/assets/
docs/使用说明.md
docs/项目文档.md
README.md（必要时）
PPT 文件（如在仓库中出现）
```

Demo 应读取：

```text
results/profiles/data_overview.json
results/profiles/kpi_distribution.csv
results/profiles/series_profile.csv
results/profiles/missing_topn.csv
results/anomalies/anomaly_iqr.csv
results/anomalies/anomaly_ksigma.csv
results/anomalies/anomaly_range.csv
results/anomalies/hadoop_iqr/part-*
results/performance/performance_report.csv
data/cleaned/metrics_cleaned.csv
```

Demo 建议结构：

```text
1. 项目概览
2. 数据统计
3. 时间序列浏览
4. 异常检测展示
5. 算法与性能对比
```

展示目标：

- 数据概览指标卡片
- KPI 分布柱状图
- 缺失率 Top-N
- 序列长度分布
- 原始时间序列曲线
- 异常点标红
- 阈值线展示
- 算法异常数量对比
- 单机 / Hadoop 性能对比

## 开发约定

- 优先复用 `src/utils/io.py` 中的 `read_table`、`write_table`、`ensure_columns`。
- 不要在 Demo 中重新处理 3GB 原始数据；Demo 只读取清洗后数据和 `results/` 下结果。
- 结果文件字段必须和 `src/utils/data_contract.py` 保持一致。
- 大数据文件、临时输出、真实集群日志不要提交 Git。
- 修改文档时保持中文表述清晰，尽量说明命令、输入文件、输出文件和成功标志。

