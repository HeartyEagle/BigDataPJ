param(
  [string]$LocalCleaned = "data/cleaned/metrics_cleaned.csv",
  [string]$HdfsCleaned = "/bigdatapj/cleaned/metrics_cleaned.csv"
)

$ErrorActionPreference = "Stop"

hdfs dfs -mkdir -p /bigdatapj/cleaned
hdfs dfs -put -f $LocalCleaned $HdfsCleaned
hdfs dfs -ls $HdfsCleaned
