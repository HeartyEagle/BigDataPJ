# PPT 算法与结果整理

本文面向答辩 PPT，基于当前仓库中的代码、结果汇总和性能报告整理。重点服务于成员 6 的展示材料，不重新计算全量异常结果。

## 1. 项目与数据规模

本项目面向运维监控指标做时间序列异常检测。整体链路为：

```text
原始监控数据
  -> 数据清洗与统一字段
  -> HDFS 存储
  -> Hadoop Streaming / MapReduce 异常检测
  -> 结果汇总
  -> Streamlit Demo 与 PPT 可视化
```

清洗后的性能指标统一字段为：

```text
timestamp, cmdb_id, kpi_name, value
```

一条时间序列定义为：

```text
cmdb_id + kpi_name
```

当前全量实验数据规模：

| 指标 | 数值 |
| --- | ---: |
| 总记录数 | 24,337,047 |
| 时间序列数 | 8,666 |
| CMDB 实体数 | 282 |
| KPI 种类数 | 584 |
| 时间范围 | 2022-03-19 16:00:00 到 2022-03-21 15:59:00 |
| 采样间隔 | 60 秒 |

PPT 可用表述：

> 本项目处理约 2433 万条监控记录，覆盖 8666 条时间序列和 584 类 KPI 指标，数据按 60 秒粒度采样。系统将不同来源的监控数据统一为标准时间序列接口，并在本地与 Hadoop 分布式环境下分别完成异常检测。

## 2. 算法实现方法与实现详情

### 2.1 IQR 四分位距算法

代码位置：

```text
src/algorithms/baseline.py
src/hadoop/reducer_baseline.py
```

实现逻辑：

1. 按 `cmdb_id + kpi_name` 分组，每组对应一条时间序列。
2. 对每条序列计算第一四分位数 `Q1` 和第三四分位数 `Q3`。
3. 计算四分位距：

```text
IQR = Q3 - Q1
```

4. 设置上下界：

```text
threshold_low  = Q1 - 1.5 * IQR
threshold_high = Q3 + 1.5 * IQR
```

5. 若 `value < threshold_low` 或 `value > threshold_high`，标记为异常。
6. 输出统一异常结果字段：

```text
timestamp, cmdb_id, kpi_name, value, method, is_anomaly, score, threshold_low, threshold_high
```

算法特点：

| 维度 | 说明 |
| --- | --- |
| 优点 | 不依赖正态分布，对极端值相对鲁棒，适合作为稳定 baseline |
| 局限 | 使用整条序列的全局阈值，对趋势变化和阶段性负载变化不敏感 |
| 适合展示 | “全局分布异常检测” |

PPT 可用表述：

> IQR 方法用整条时间序列的四分位分布估计正常范围，超过 `Q1 - 1.5IQR` 或 `Q3 + 1.5IQR` 的点被视为异常。它不要求数据服从正态分布，因此适合作为监控场景中的稳健基线方法。

### 2.2 K-Sigma 算法

代码位置：

```text
src/algorithms/baseline.py
src/hadoop/reducer_baseline.py
```

实现逻辑：

1. 按 `cmdb_id + kpi_name` 分组。
2. 对每条序列计算均值 `mean` 和标准差 `std`。
3. 使用 `k=3` 设置阈值：

```text
threshold_low  = mean - 3 * std
threshold_high = mean + 3 * std
```

4. 超出上下界则标记为异常。
5. `score` 使用标准化偏离程度：

```text
score = abs(value - mean) / std
```

算法特点：

| 维度 | 说明 |
| --- | --- |
| 优点 | 原理简单，计算速度快，结果容易解释 |
| 局限 | 默认假设数据接近正态分布，极端值会拉大标准差，从而降低敏感性 |
| 适合展示 | “保守异常检测基线” |

PPT 可用表述：

> K-Sigma 方法使用均值和标准差描述正常波动范围。实验中它在统计类算法里的异常比例最低，说明该方法更保守，适合筛选偏离程度非常明显的异常点。

### 2.3 Range 规则阈值算法

代码位置：

```text
src/algorithms/baseline.py
src/hadoop/reducer_baseline.py
```

实现逻辑：

1. 按 KPI 名称识别指标类型。
2. 对百分比类指标设置理论范围 `[0, 100]`。
3. 对 rate、ratio、success、failure、error、cpu、memory、disk、latency 等非负指标设置 `[0, +inf)`。
4. 如果序列最小值本身非负，也设置 `[0, +inf)`。
5. 超出规则范围则标记为异常。

算法特点：

| 维度 | 说明 |
| --- | --- |
| 优点 | 业务含义明确，能发现负数、百分比越界等明显非法值 |
| 局限 | 严重依赖指标单位和命名规则，不适合单独评价异常检测效果 |
| 适合展示 | “规则基线”和“指标单位治理的重要性” |

当前结果注意事项：

Range 已修复此前 `usage` 类指标单位识别过宽的问题。修复后只对明确包含 `pct`、`percent`、`percentage` 等百分比含义的 KPI 使用 `[0,100]` 上界；`memoryUsage`、bytes、MB 等容量类指标不再按百分比处理。

本地下载的 `results/analysis_package_range_fix/` 显示，Hadoop Range 全量扫描 24,337,047 条记录，检出 51,840 个异常点，异常率为 0.2130%，涉及 18 条异常序列；未生成 `range_suspicious_thresholds.csv`，说明没有发现“上界为 100 且实际最大值超过 100”的明显残留误判。

修复后 Range 的异常集中在 `adservice.ts:8088` 和 `adservice2.ts:8088` 的 JVM Metaspace / NonHeap 内存指标，异常值为 `-1` 或接近 0 的负数，属于规则法适合发现的非法取值。更稳妥的讲法是：

> Range 是基于规则阈值的异常检测基线，能快速发现明显非法值。修复后它不再被容量类 usage 指标误判主导，而是主要补充统计方法不关注的规则非法值。

### 2.4 Advanced: Rolling Robust Z-Score

代码位置：

```text
src/algorithms/advanced.py
src/hadoop/reducer_advanced.py
```

实现逻辑：

1. 按 `cmdb_id + kpi_name` 分组，并按时间排序。
2. 对当前点 `x_t`，只使用它之前的历史窗口做统计，避免当前异常点污染阈值。
3. 默认窗口大小：

```text
window = 60
min_periods = 30
z_threshold = 3.5
```

4. 使用历史窗口的 median 作为局部中心。
5. 使用 IQR 估计局部波动尺度：

```text
scale = (Q3 - Q1) / 1.349
```

6. 计算 robust z-score：

```text
score = abs(value - center) / scale
```

7. 若 `score > 3.5`，标记为异常。
8. 输出动态上下界：

```text
threshold_low  = center - 3.5 * scale
threshold_high = center + 3.5 * scale
```

冷启动处理：

序列开头历史点不足时，使用整条序列的 median、IQR scale 和标准差作为 fallback，避免窗口不足导致阈值缺失。

算法特点：

| 维度 | 说明 |
| --- | --- |
| 优点 | 使用局部动态阈值，适合捕捉突增、突降和局部波动异常 |
| 局限 | 计算成本高于全局 IQR / K-Sigma |
| 适合展示 | “高级算法”和“局部异常检测能力” |

PPT 可用表述：

> Advanced 算法采用 Rolling Robust Z-Score。相比全局阈值方法，它用历史滑动窗口估计局部中心和波动范围，因此更适合处理监控指标中的阶段性负载变化和局部突发异常。

## 3. 算法异常检测结果

### 3.1 总体异常数量与比例

| 算法 | 数据量 | 异常点数 | 异常比例 | 结果解读 |
| --- | ---: | ---: | ---: | --- |
| IQR | 24,337,047 | 389,827 | 1.6018% | 稳健 baseline，异常量适中 |
| K-Sigma | 24,337,047 | 65,665 | 0.2698% | 最保守，只捕捉极明显偏离 |
| Range | 24,337,047 | 51,840 | 0.2130% | 修复后主要检测规则非法值，异常集中在 18 条序列 |
| Advanced | 24,337,047 | 330,333 | 1.3573% | 动态阈值方法，低于 IQR、高于 K-Sigma |

PPT 可用结论：

> 四类算法对同一批 2433 万条数据完成检测。IQR 与 Advanced 的异常比例分别为 1.60% 和 1.36%，更适合展示典型监控波动异常；K-Sigma 异常比例为 0.27%，在统计类方法中最保守；Range 修复后异常比例为 0.2130%，主要用于发现负值、百分比越界等规则非法值。

### 3.2 异常集中指标

根据 `results/analysis_package/anomaly_kpi_topn.csv`，当前异常较集中的 KPI 包括：

| 算法 | KPI | 异常点数 | 异常比例 | 说明 |
| --- | --- | ---: | ---: | --- |
| Advanced | `container_network_transmit_MB.eth0` | 25,272 | 9.86% | 网络发送流量局部突增/突降明显 |
| Advanced | `container_network_receive_MB.eth0` | 15,612 | 6.09% | 网络接收流量存在局部异常波动 |
| Advanced | `container_memory_usage_MB` | 15,416 | 6.37% | 内存使用存在阶段性异常 |
| IQR | `container_file_descriptors` | 20,312 | 8.40% | 文件描述符数量出现全局离群点 |
| IQR | `container_sockets` | 15,086 | 6.24% | socket 数量存在明显离群 |
| IQR | `container_network_receive_MB.eth0` | 13,396 | 5.23% | 网络接收流量有全局离群点 |
| K-Sigma | `container_network_receive_MB.eth0` | 6,523 | 2.55% | K-Sigma 只保留偏离最强的网络异常 |

修复后 Range 相关 Top KPI 集中在 JVM Metaspace / NonHeap 相关指标，例如 `java_lang_MemoryPool_Usage_max.Metaspace`、`java_lang_Memory_NonHeapMemoryUsage_max`、`jvm_memory_MB_max.nonheap`。这些结果适合说明 Range 能发现规则非法负值，但不建议替代 Advanced 网络流量案例作为主要时间序列波动展示。

### 3.3 Advanced 典型异常序列

当前 `demo_cases.csv` 中 Advanced 典型异常序列：

| cmdb_id | kpi_name | 异常点数 | 最大 score |
| --- | --- | ---: | ---: |
| `node-5.checkoutservice-2` | `container_network_transmit_MB.eth0` | 882 | 44.56 |
| `node-6.checkoutservice-0` | `container_network_transmit_MB.eth0` | 821 | 48.84 |
| `node-6.shippingservice-1` | `container_network_transmit_MB.eth0` | 765 | 38.96 |
| `node-5.shippingservice-1` | `container_network_transmit_MB.eth0` | 731 | 21.33 |
| `node-3.shippingservice2-0` | `container_network_transmit_MB.eth0` | 710 | 262.10 |

PPT 可用表述：

> Advanced 典型异常主要集中在容器网络发送流量指标，说明局部动态阈值对网络流量的突发变化更敏感。该类指标适合在 Demo 中展示“原始曲线 + 异常点叠加”的效果。

## 4. 算法效率与 Hadoop 加速

性能结果来自：

```text
docs/高级算法与性能对比报告.md
results/performance/full_comparison_report.csv
```

### 4.1 运行时间对比

| 算法 | Local 时间(s) | Hadoop 时间(s) | 加速比 |
| --- | ---: | ---: | ---: |
| IQR | 444 | 176 | 2.52x |
| K-Sigma | 547 | 174 | 3.14x |
| Range | 397 | 171 | 2.32x |
| Advanced | 565 | 193 | 2.93x |

### 4.2 吞吐量对比

| 算法 | Local 吞吐量(rows/s) | Hadoop 吞吐量(rows/s) |
| --- | ---: | ---: |
| IQR | 54,813 | 138,279 |
| K-Sigma | 44,492 | 139,868 |
| Range | 61,302 | 142,322 |
| Advanced | 43,074 | 126,099 |

PPT 可用结论：

> 在 2433 万条记录上，Hadoop 分布式版本相较本地单机均获得明显加速。K-Sigma 加速比最高，为 3.14x；Advanced 虽然计算逻辑更复杂，但在 Hadoop 上仍达到 2.93x 加速，说明 MapReduce 按时间序列分组并行处理的设计有效。

## 5. 最后可以得到的总的结论

### 5.1 算法层结论

1. IQR 是稳定可靠的全局分布基线，异常比例为 1.60%，适合做主要 baseline 展示。
2. K-Sigma 是最保守的方法，异常比例为 0.27%，适合说明不同算法敏感度差异。
3. Advanced 使用滑动窗口动态阈值，异常比例为 1.36%，在网络流量等局部波动指标上表现更突出。
4. Range 可以保留为规则基线，修复后异常率为 0.2130%，主要用于补充非法取值检测。

### 5.2 工程层结论

1. 项目完成了从数据清洗、统计画像、异常检测、分布式计算到 Demo 展示的完整链路。
2. Hadoop Streaming 方案能够按 `cmdb_id + kpi_name` 对时间序列分组，将不同序列并行交给 reducer 检测。
3. 在 3 台服务器、6 个 reducer 的配置下，四类算法均取得 2.32x 到 3.14x 的加速。
4. 结果文件统一为标准异常字段，便于后续 Demo、PPT 和更多算法扩展。

### 5.3 展示层结论

1. 数据规模页可以突出“2433 万记录、8666 条序列、584 类 KPI、60 秒采样”。
2. 算法页建议主讲 IQR、K-Sigma、Advanced，Range 作为规则合法性检查补充。
3. 结果页建议展示异常比例柱状图、典型 KPI Top 图、Advanced 典型异常曲线。
4. 性能页建议展示 Local vs Hadoop 运行时间和吞吐量，突出 Hadoop 加速效果。

## 6. PPT 中需要避免的表述

不建议使用：

```text
Range 检测效果最好，因为它检测出的异常最多。
```

原因：修复后 Range 异常点数为 51,840，低于 IQR 和 Advanced。更重要的是，Range 关注的是规则非法值，异常数量不能和统计类波动异常直接比较。

建议改为：

```text
Range 作为规则阈值基线，能发现明显越界值和非法负值；它的作用是补充合法性检查，而不是证明检测效果“最多”或“最好”。
```

不建议使用：

```text
所有 Top20 异常序列都是真实业务异常。
```

建议改为：

```text
Top 异常序列用于定位异常集中区域。修复后 Range Top 序列主要说明 JVM 内存类指标存在非法负值；IQR 和 Advanced 的网络、连接数、内存等异常更适合作为当前展示案例。
```

## 7. 可直接放入 PPT 的一页总结

> 本项目在约 2433 万条监控记录上完成了时间序列异常检测实验，覆盖 8666 条序列和 584 类 KPI。算法层面实现了 IQR、K-Sigma、Range 三类 baseline 以及 Rolling Robust Z-Score 高级算法。实验结果显示，IQR 与 Advanced 能捕捉更多典型监控波动异常，其中 Advanced 对网络流量等局部突发波动更敏感；Range 修复后异常率为 0.2130%，主要补充规则非法值检测。工程层面，Hadoop Streaming 版本在 3 台服务器上取得 2.32x 到 3.14x 的加速，证明按时间序列分组并行检测的方案能够有效支撑大规模监控数据处理。
