param(
  [string]$Input = "/bigdatapj/cleaned/metrics_cleaned.csv",
  [string]$Output = "/bigdatapj/results/anomalies/hadoop_iqr",
  [string]$StreamingJar = "/usr/local/hadoop/share/hadoop/tools/lib/hadoop-streaming.jar"
)

$ErrorActionPreference = "Stop"

hdfs dfs -rm -r -f $Output

hadoop jar $StreamingJar `
  -D mapreduce.job.name=BigDataPJ-Hadoop-IQR `
  -D mapreduce.job.reduces=2 `
  -files src/hadoop/mapper_baseline.py,src/hadoop/reducer_baseline.py `
  -mapper "python3 mapper_baseline.py" `
  -reducer "python3 reducer_baseline.py" `
  -input $Input `
  -output $Output

hdfs dfs -ls $Output
