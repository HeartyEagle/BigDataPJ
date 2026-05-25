# 数据导入脚本说明

成员 2 负责本目录。

建议先实现一个最小导入流程：

```bash
python scripts/import_data/import_metrics.py --input <原始数据目录> --output data/raw/metrics_raw.csv
```

成员 2 交给成员 3 的文件至少要包含：

```text
timestamp, cmdb_id, kpi_name, value
```
