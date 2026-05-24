# Hadoop 运行说明

成员 2 和成员 5 共同负责本目录。

本项目采用：

```text
HDFS：存储原始数据、清洗数据、统计结果、异常结果
Hadoop Streaming：用 Python mapper/reducer 按时间序列分组运行异常检测
```

为什么这样设计：

```text
1. 贴合“大数据平台”课程要求。
2. Python 算法代码可以复用，不必全组改写 Java MapReduce。
3. Map 阶段按 cmdb_id + kpi_name 分组，Reduce 阶段每个 key 就是一条时间序列。
4. 服务器 1 作为 NameNode/ResourceManager，服务器 2/3 作为 DataNode/NodeManager。
```
