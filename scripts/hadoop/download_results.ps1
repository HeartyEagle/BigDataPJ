param(
  [string]$HdfsOutput = "/bigdatapj/results/anomalies/hadoop_iqr",
  [string]$LocalOutputDir = "results/anomalies/hadoop_iqr"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force $LocalOutputDir | Out-Null
hdfs dfs -get -f "$HdfsOutput/part-*" $LocalOutputDir

Write-Host "Downloaded Hadoop result parts to $LocalOutputDir"
