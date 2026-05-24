"""Project-wide data contracts.

成员 1（组长）负责维护本文件：任何输入/输出字段变更都要先改这里，
再通知成员 2-6 同步修改各自模块，避免最后集成时字段对不上。
"""

METRICS_COLUMNS = ["timestamp", "cmdb_id", "kpi_name", "value"]
BUSINESS_COLUMNS = ["timestamp", "service", "rr", "sr", "count", "mrt"]

SERIES_KEY = ["cmdb_id", "kpi_name"]

SERIES_INDEX_COLUMNS = [
    "series_id",
    "cmdb_id",
    "kpi_name",
    "start_time",
    "end_time",
    "point_count",
]

SERIES_PROFILE_COLUMNS = [
    "series_id",
    "cmdb_id",
    "kpi_name",
    "count",
    "missing_rate",
    "min",
    "max",
    "mean",
    "std",
]

ANOMALY_COLUMNS = [
    "timestamp",
    "cmdb_id",
    "kpi_name",
    "value",
    "method",
    "is_anomaly",
    "score",
    "threshold_low",
    "threshold_high",
]

PERFORMANCE_COLUMNS = [
    "method",
    "server_num",
    "series_count",
    "data_count",
    "runtime_sec",
    "throughput",
]
