param(
  [string]$Base = "/bigdatapj"
)

$ErrorActionPreference = "Stop"

hdfs dfs -mkdir -p $Base/raw
hdfs dfs -mkdir -p $Base/cleaned
hdfs dfs -mkdir -p $Base/results/profiles
hdfs dfs -mkdir -p $Base/results/anomalies
hdfs dfs -mkdir -p $Base/results/performance

hdfs dfs -ls $Base
