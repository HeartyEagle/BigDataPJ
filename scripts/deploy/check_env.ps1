$ErrorActionPreference = "Stop"

Write-Host "Python:"
python --version

Write-Host "Hadoop:"
hadoop version

Write-Host "HDFS root check:"
hdfs dfs -ls /

Write-Host "Required paths:"
@(
  "data/raw",
  "data/cleaned",
  "results/profiles",
  "results/anomalies",
  "results/performance"
) | ForEach-Object {
  if (Test-Path $_) {
    Write-Host "[OK] $_"
  } else {
    Write-Host "[MISS] $_"
  }
}
