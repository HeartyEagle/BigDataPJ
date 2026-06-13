# PPT 算法与异常结果整理

本文面向答辩 PPT 整理当前项目中异常检测算法的实现方法、结果数据、可得结论和需要注意的限制。当前整理基于现有 `results/` 输出，不重新运行算法。

## 1. 数据与任务背景

项目目标是对运维监控指标构成的多变量时间序列进行异常检测。清洗后的性能指标统一为：

```text
timestamp, cmdb_id, kpi_name, value
```

一条时间序列定义为：

```text
cmdb_id + kpi_name
```

当前全量实验数据规模如下：

| 指标 | 数值 |
| --- | ---: |
| 总记录数 | 24,337,047 |
| 时间序列数 | 8,666 |
| CMDB 对象数 | 282 |
| KPI 种类数 | 584 |
| 时间范围 | 2022-03-19 16:00:00 至 2022-03-21 15:59:00 |
| 采样间隔 | 60 秒 |

这些数据规模满足项目对 5000+ 时间序列、分钟级采样和大规模监控数据处理的展示要求。

## 2. 算法实现方法和实现详情

### 2.1 IQR 四分位距法

实现位置：

```text
src/algorithms/baseline.py
src/hadoop/reducer_baseline.py
```

IQR 方法按每条时间序列独立计算全局分布。对一条序列取第一四分位数 `Q1` 和第三四分位数 `Q3`，得到：

```text
IQR = Q3 - Q1
threshold_low  = Q1 - 1.5 * IQR
threshold_high = Q3 + 1.5 * IQR
```

若某个点低于下界或高于上界，则标记为异常。异常分数使用超出阈值的距离：

```text
score = max(threshold_low - value, value - threshold_high, 0)
```

PPT 可讲法：IQR 是一种鲁棒的全局统计基线，不依赖正态分布，对极端值不如均值方差敏感，适合作为监控数据异常检测的基础方法。

### 2.2 K-Sigma 均值方差法

实现位置：

```text
src/algorithms/baseline.py
src/hadoop/reducer_baseline.py
```

K-Sigma 方法对每条序列计算全局均值 `mean` 和标准差 `std`，默认 `k=3`：

```text
threshold_low  = mean - 3 * std
threshold_high = mean + 3 * std
```

超过三倍标准差范围的点被标记为异常。异常分数为标准化偏离程度：

```text
score = abs(value - mean) / std
```

PPT 可讲法：K-Sigma 适合较稳定、接近正态波动的指标，结果通常更保守；但它容易受到极端值影响，对强偏态分布不如 IQR 稳健。

### 2.3 Range 规则阈值法

实现位置：

```text
src/algorithms/baseline.py
src/hadoop/reducer_baseline.py
```

Range 方法不是从数据分布学习阈值，而是根据 KPI 名称和基础业务规则设置取值范围。例如：

```text
百分比类指标：0 到 100
CPU / memory / disk / latency / time 等非负指标：0 到 +inf
其他非负序列：0 到 +inf
```

PPT 可讲法：Range 是规则型基线，主要用于发现明显非法值，例如负数、超过百分比上限的值或违反物理意义的值。它解释性强、速度快，但强依赖指标单位和命名规范。

修复后结果注意事项：Range 已调整为只对明确百分比指标使用 `[0,100]` 上界，`memoryUsage`、bytes、MB 等容量类指标不再按百分比处理。新的 Hadoop Range 分析包显示，24,337,047 条记录中检出 51,840 个异常点，异常率为 0.2130%，涉及 18 条异常序列；`range_suspicious_thresholds.csv` 未生成，说明没有发现“上界为 100 但实际最大值超过 100”的明显残留误判。

修复后的 Range Top 结果集中在 `adservice.ts:8088` 和 `adservice2.ts:8088` 的 JVM Metaspace / NonHeap 相关指标，取值为 `-1` 或接近 `0` 的负数，属于规则法适合发现的非法负值。PPT 中建议把 Range 讲成“合法性检查补充”，不要用异常数量多少评价它和 IQR / Advanced 谁更好。

### 2.4 Advanced：Rolling Robust Z-Score

实现位置：

```text
src/algorithms/advanced.py
src/hadoop/reducer_advanced.py
```

高级算法采用 Rolling Robust Z-Score。与 IQR / K-Sigma 使用整条序列的全局阈值不同，该方法使用历史滑动窗口估计当前时刻的局部中心和波动范围。

核心流程：

1. 对每条 `cmdb_id + kpi_name` 序列按时间排序。
2. 对当前点 `x_t`，只使用它之前的历史值构造滑动窗口，默认窗口大小 `window=60`，最小历史点数 `min_periods=30`。
3. 使用窗口 median 作为局部中心。
4. 使用窗口 IQR 估计鲁棒尺度：

```text
scale = (Q3 - Q1) / 1.349
```

5. 计算 robust z-score：

```text
score = abs(x_t - center) / scale
```

6. 默认阈值 `z_threshold=3.5`。当 `score > 3.5` 时标记为异常。
7. 输出动态上下界：

```text
threshold_low  = center - 3.5 * scale
threshold_high = center + 3.5 * scale
```

算法还对冷启动做了 fallback：当序列开头历史窗口不足时，使用全局 median 和全局 scale 补齐，避免前几十个点无法检测。

PPT 可讲法：Advanced 方法更适合监控场景中的局部突增、突降和阶段性负载变化；它只使用当前点之前的历史窗口估计阈值，避免当前异常点污染自己的检测阈值。

## 3. 算法最后得到的异常情况结果

### 3.1 全量异常数量与异常比例

当前四种算法在 24,337,047 条记录上的全量检测结果如下，其中 Range 使用修复后的 Hadoop 结果：

| 方法 | 异常点数 | 异常比例 | 结果解读 |
| --- | ---: | ---: | --- |
| IQR | 389,827 | 1.6018% | 全局鲁棒统计方法，检测结果适中 |
| K-Sigma | 65,665 | 0.2698% | 最保守，只标记强偏离均值的点 |
| Range | 51,840 | 0.2130% | 修复后只保留明确规则非法值，异常集中在 18 条序列 |
| Advanced | 330,333 | 1.3573% | 局部窗口检测，异常比例低于 IQR，高于 K-Sigma |

可用于 PPT 的主要结论：

- Range 修复后异常比例最低，为 0.2130%，但它检测的是规则非法值，不能简单理解为“最保守的统计异常算法”。
- K-Sigma 在统计类算法中最保守，异常比例为 0.2698%。
- IQR 和 Advanced 的异常比例都在 1% 到 2% 左右，更适合作为主要检测结果展示。
- Advanced 检出 330,333 个异常点，说明滑动窗口方法能够在保持较低异常比例的同时捕捉局部波动。
- Range 只检出 51,840 个异常点，说明修复后它回归为规则合法性检查，主要用于补充统计方法不关注的非法取值。

### 3.2 典型异常 KPI 分布

当前异常 Top KPI 中，较有展示价值的指标包括：

| 方法 | KPI | 异常点数 | 异常比例 | 说明 |
| --- | --- | ---: | ---: | --- |
| Rolling-Robust-ZScore | container_network_transmit_MB.eth0 | 25,272 | 9.8602% | 网络发送流量局部波动明显 |
| Rolling-Robust-ZScore | container_network_receive_MB.eth0 | 15,612 | 6.0913% | 网络接收流量存在局部突增/突降 |
| Rolling-Robust-ZScore | container_memory_usage_MB | 15,416 | 6.3728% | 内存使用量存在阶段性异常波动 |
| IQR | container_file_descriptors | 20,312 | 8.3967% | 文件描述符异常适合做系统资源案例 |
| IQR | container_network_receive_MB.eth0 | 13,396 | 5.2266% | 全局分布下网络接收流量存在离群点 |
| K-Sigma | container_network_receive_MB.eth0 | 6,523 | 2.5450% | 三倍标准差下仍能检出的强异常 |

这些指标适合在 PPT 中作为“异常集中出现的资源类型”：网络流量、内存使用、文件描述符、CPU 使用、Istio 请求延迟和请求量。

### 3.3 Advanced 典型异常序列

Advanced 输出的典型异常序列如下：

| cmdb_id | kpi_name | 异常数 | 最大 score |
| --- | --- | ---: | ---: |
| node-5.checkoutservice-2 | container_network_transmit_MB.eth0 | 882 | 44.5562 |
| node-6.checkoutservice-0 | container_network_transmit_MB.eth0 | 821 | 48.8353 |
| node-6.shippingservice-1 | container_network_transmit_MB.eth0 | 765 | 38.9606 |
| node-5.shippingservice-1 | container_network_transmit_MB.eth0 | 731 | 21.3312 |
| node-3.shippingservice2-0 | container_network_transmit_MB.eth0 | 710 | 262.1042 |

PPT 可讲法：这些典型案例都集中在容器网络发送流量指标上，说明服务节点之间的网络流量存在明显局部波动。Rolling Robust Z-Score 对这类“相对历史窗口突然偏离”的场景更敏感。

### 3.4 Range 修复后结果说明

修复后的 Range 结果来自：

```text
results/analysis_package_range_fix/
```

关键结果：

| 指标 | 数值 |
| --- | ---: |
| 扫描记录数 | 24,337,047 |
| Range 异常点数 | 51,840 |
| Range 异常率 | 0.2130% |
| 有异常序列数 | 18 |
| 上界 100 且实际最大值超过 100 的疑似误判 | 0 |

Range Top KPI 集中在以下 JVM 内存指标：

```text
java_lang_GarbageCollector_LastGcInfo_memoryUsageAfterGc_max.Metaspace.Copy
java_lang_GarbageCollector_LastGcInfo_memoryUsageBeforeGc_max.Metaspace.Copy
java_lang_MemoryPool_Usage_max.Metaspace
java_lang_Memory_NonHeapMemoryUsage_max
jvm_memory_MB_max.nonheap
```

这些序列的异常率为 100%，原因是值为 `-1` 或接近 0 的负数，而 Range 对 memory / JVM 指标设置非负下界 `0`。这说明修复后的 Range 不再被大规模容量指标误判主导，而是更清晰地定位到规则非法值。

PPT 建议：可以用 Range 作为“规则阈值检测非法负值”的例子，但主异常案例仍建议使用 Advanced 的网络流量曲线，因为它更能体现时间序列波动异常。

## 4. 性能效率相关内容

完整性能报告见：

```text
docs/高级算法与性能对比报告.md
results/performance/full_comparison_report.csv
```

### 4.1 本地与 Hadoop 运行时间对比

| 方法 | Local 时间(s) | Hadoop 时间(s) | 加速比 |
| --- | ---: | ---: | ---: |
| IQR | 444 | 176 | 2.52x |
| K-Sigma | 547 | 174 | 3.14x |
| Range | 397 | 171 | 2.32x |
| Advanced | 565 | 193 | 2.93x |

PPT 可讲法：四种算法在 Hadoop 三节点集群上均获得明显加速，说明按时间序列分组的异常检测任务天然适合 MapReduce 并行处理。其中 K-Sigma 加速比最高，Advanced 在计算更复杂的情况下仍达到 2.93x 加速。

### 4.2 吞吐量对比

| 方法 | Local 吞吐量(rows/s) | Hadoop 吞吐量(rows/s) |
| --- | ---: | ---: |
| IQR | 54,813 | 138,279 |
| K-Sigma | 44,492 | 139,868 |
| Range | 61,302 | 142,322 |
| Advanced | 43,074 | 126,099 |

PPT 可讲法：Hadoop 模式下吞吐量稳定在 12.6 万到 14.2 万 rows/s，明显高于本地单机。即使 Advanced 需要滑动窗口和动态阈值计算，仍能保持 12.6 万 rows/s 的处理能力。

## 5. 最后可以得到的总的结论

### 5.1 算法效果结论

1. 本项目完成了从清洗数据到异常检测结果的闭环，四种算法都能输出统一格式的异常结果。
2. K-Sigma 在统计类算法中异常比例最低，适合强调“高置信度、强偏离”的异常。
3. IQR 不依赖正态分布，结果较稳定，适合作为主要 baseline。
4. Advanced 使用历史滑动窗口和鲁棒统计量，能够捕捉局部突增、突降和阶段性波动，是当前最适合作为项目亮点的算法。
5. Range 规则法解释性强，修复后异常率降至 0.2130%，适合作为规则合法性检查补充，不应和 IQR / Advanced 直接比较“异常数量越多越好”。

### 5.2 系统实现结论

1. 数据按 `cmdb_id + kpi_name` 划分为独立时间序列，适合在 Hadoop 中按 key 分组并行处理。
2. 本地 Python 和 Hadoop Streaming 使用一致的输入输出字段，保证 Demo、PPT 和结果汇总可以统一读取。
3. Hadoop 三节点集群在四种算法上都带来 2.32x 到 3.14x 的加速，证明分布式方案对大规模监控指标有效。
4. Streamlit Demo 可以基于 `analysis_package` 和结果图快速展示数据概览、异常点叠加、算法对比和性能对比。

### 5.3 风险与改进方向

1. Range 的 `usage` 单位误判已经修复，当前未发现明显的 100 上界残留误判。
2. 后续可增加指标元数据字典，为不同 KPI 配置单位、合法范围和告警等级。
3. 对 Range 检出的 JVM 负值，可以在业务侧进一步确认是采集缺省值、哨兵值还是实际非法值。
4. Advanced 可进一步调参，例如窗口大小、最小历史点数和 z-score 阈值，以适配不同业务服务的波动周期。

## 6. PPT 可直接使用的表述

### 项目算法页

本项目实现了三类 baseline 方法和一种高级滑动窗口方法：IQR 使用四分位距构造鲁棒全局阈值；K-Sigma 使用均值和标准差检测强偏离点；Range 使用规则阈值检测明显非法值；Rolling Robust Z-Score 使用历史滑动窗口的 median 和 IQR 构造动态阈值，更适合捕捉局部异常。

### 异常结果页

在 24,337,047 条监控记录、8,666 条时间序列上，IQR 检出 389,827 个异常点，异常比例 1.6018%；K-Sigma 检出 65,665 个异常点，异常比例 0.2698%；修复后的 Range 检出 51,840 个规则非法值，异常比例 0.2130%；Advanced 检出 330,333 个异常点，异常比例 1.3573%。Advanced 的典型异常集中在容器网络发送流量指标，说明局部流量突增/突降是本轮数据中的重要异常模式。

### 性能结果页

在三节点 Hadoop 集群上，四种算法都获得明显加速：IQR 为 2.52x，K-Sigma 为 3.14x，Range 为 2.32x，Advanced 为 2.93x。Hadoop 模式吞吐量稳定在 12.6 万到 14.2 万 rows/s，证明按时间序列分组的异常检测任务适合使用 MapReduce 并行处理。

### 总结页

项目完成了从监控数据清洗、时间序列构造、异常检测、Hadoop 分布式计算到 Demo 可视化展示的完整链路。算法上，IQR 和 K-Sigma 提供稳定 baseline，Range 补充规则非法值检测，Advanced 提供面向局部波动的增强检测能力；系统上，Hadoop 显著提升全量数据处理效率。后续可结合 KPI 元数据继续优化阈值配置和告警解释。
