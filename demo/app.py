"""Streamlit demo entry.

成员 6 主要修改本文件：
1. 从 results/profiles 读取统计文件做首页。
2. 从 results/anomalies 读取异常结果画曲线和异常点。
3. 从 results/performance 读取性能结果做单机/多机对比。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "results" / "profiles"
ANOMALIES = ROOT / "results" / "anomalies"


st.set_page_config(page_title="时间序列异常检测", layout="wide")
st.title("时间序列异常检测 Demo")

overview_path = PROFILES / "data_overview.json"
if overview_path.exists():
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    cols = st.columns(4)
    cols[0].metric("记录数", overview.get("record_count", 0))
    cols[1].metric("时间序列数", overview.get("series_count", 0))
    cols[2].metric("监控对象数", overview.get("cmdb_count", 0))
    cols[3].metric("KPI 数", overview.get("kpi_count", 0))
else:
    st.warning("还没有统计结果，请先运行 src.preprocessing.build_profiles。")

kpi_path = PROFILES / "kpi_distribution.csv"
if kpi_path.exists():
    kpi = pd.read_csv(kpi_path)
    st.subheader("KPI 分布")
    st.plotly_chart(px.bar(kpi.head(30), x="kpi_name", y="record_count"), use_container_width=True)

anomaly_files = sorted(ANOMALIES.glob("anomaly_*.csv"))
if anomaly_files:
    selected_file = st.selectbox("异常结果文件", anomaly_files, format_func=lambda p: p.name)
    anomalies = pd.read_csv(selected_file)
    st.subheader("异常数量")
    st.dataframe(anomalies.groupby(["method", "kpi_name"])["is_anomaly"].sum().reset_index().head(50))
else:
    st.info("还没有异常结果，请先运行 src.algorithms.baseline。")
