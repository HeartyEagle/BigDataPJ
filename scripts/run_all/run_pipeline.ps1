param(
  [string]$InputPath = "data/raw",
  [string]$CleanedPath = "data/cleaned/metrics_cleaned.csv",
  [switch]$RunHadoop
)

$ErrorActionPreference = "Stop"

python -m src.preprocessing.clean_metrics --input $InputPath --output $CleanedPath
python -m src.preprocessing.build_profiles --input $CleanedPath
python -m src.algorithms.baseline --input $CleanedPath --method all

if ($RunHadoop) {
  .\scripts\hadoop\init_hdfs.ps1
  .\scripts\hadoop\upload_cleaned.ps1 -LocalCleaned $CleanedPath
  .\scripts\hadoop\run_streaming_iqr.ps1
  .\scripts\hadoop\download_results.ps1
}

Write-Host "Pipeline finished. Results are under results/."
