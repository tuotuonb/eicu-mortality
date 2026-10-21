"""一键运行全流程：下载数据 → SQL 提数 → 数据质控 → 基线表 → 建模与验证 → 机器学习对比 → 计算器网页。

用法（在项目根目录）：.venv/Scripts/python.exe run_all.py
"""
import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable

# Windows 上 R 默认装在 C:\Program Files\R\R-x.y.z，取最新版本
RSCRIPT = sorted(glob.glob(r"C:\Program Files\R\R-*\bin\Rscript.exe"))[-1]

STEPS = [
    ("下载并校验数据", [PY, "src/download_data.py"]),
    ("SQL 提数，生成分析数据集", [PY, "src/build_dataset.py"]),
    ("数据质控报告", [PY, "src/data_quality.py"]),
    ("基线特征表（Table 1）", [RSCRIPT, "R/01_table1.R"]),
    ("预测模型构建与验证", [RSCRIPT, "R/02_model.R"]),
    ("机器学习模型与 SHAP", [PY, "src/ml_models.py"]),
    ("四个模型对比", [RSCRIPT, "R/03_ml_compare.R"]),
    ("生成风险计算器网页", [PY, "src/build_dashboard.py"]),
]

for i, (title, cmd) in enumerate(STEPS, 1):
    print(f"\n===== 第 {i} 步：{title} =====", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)

print("\n全部完成，结果在 results/ 目录下。")
