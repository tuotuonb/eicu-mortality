"""第 8 步：生成网页。

把模型系数（results/model/）和性能结果（results/tables/）写进网页模板，每个模板生成两个文件：
完整网页（可直接用浏览器打开，或发布到 GitHub Pages），以及不含 <html>/<head> 外壳、用于发布为 Claude Artifact 的版本。

  dashboard/template.html          → index.html / calculator.html          简洁版风险计算器
  dashboard/showcase_template.html → showcase.html / showcase_artifact.html  监护仪风格的项目展示页
"""
import json
import textwrap

import pandas as pd

from data_quality import missing_comparison
from db import PROCESSED, ROOT

DASH = ROOT / "dashboard"
TABLES = ROOT / "results" / "tables"
MODEL_DIR = ROOT / "results" / "model"


def auc_only(text: str) -> str:
    """'0.814 (0.749–0.879)' → '0.814'"""
    return str(text).split(" ")[0]


def build_report() -> dict:
    df = pd.read_csv(PROCESSED / "analysis_dataset.csv")
    perf = pd.read_csv(TABLES / "table4_performance.csv", encoding="utf-8-sig")
    tuning = pd.read_csv(TABLES / "table5_ml_tuning.csv", encoding="utf-8-sig").set_index("模型")
    comp = pd.read_csv(TABLES / "table6_model_comparison.csv", encoding="utf-8-sig")

    def perf_row(dataset: str, model_prefix: str) -> pd.Series:
        return perf[(perf["数据集"] == dataset) & perf["模型"].str.startswith(model_prefix)].iloc[0]

    def comp_row(dataset: str, model: str) -> pd.Series:
        return comp[(comp["数据集"] == dataset) & (comp["模型"] == model)].iloc[0]

    full, sub = "外部验证组（全部）", "外部验证组（有 APACHE 预测者）"
    lr_val = perf_row("验证组", "本研究模型")
    lr_corrected = perf_row("建模组", "本研究模型（Bootstrap")
    apache = comp_row(sub, "APACHE IVa")
    lr_sub = comp_row(sub, "Logistic 列线图模型")

    performance = [
        {"model": "Logistic 列线图模型（本计算器）", "css": "ours", "n_vars": 9,
         "dev_auc": f"{lr_corrected['AUC']}（Bootstrap 校正）", "val_auc": lr_val["AUC"]},
        {"model": "XGBoost", "n_vars": 22,
         "dev_auc": f"{tuning.loc['XGBoost', '交叉验证 AUC']:.3f}（5 折交叉验证）",
         "val_auc": comp_row(full, "XGBoost")["AUC"]},
        {"model": "随机森林", "n_vars": 22,
         "dev_auc": f"{tuning.loc['随机森林', '交叉验证 AUC']:.3f}（5 折交叉验证）",
         "val_auc": comp_row(full, "随机森林")["AUC"]},
        {"model": "APACHE IVa", "css": "apache", "n_vars": "100+", "dev_auc": "—", "val_auc": f"{apache['AUC']}*"},
    ]
    note = (
        f"* 外部验证组中只有 {apache['例数']} 例有 APACHE IVa 预测值。在这批患者中，本模型 AUC 为 "
        f"{auc_only(lr_sub['AUC'])}，与 APACHE IVa 的差异无统计学意义（配对 DeLong 检验 P = {lr_sub['vs APACHE IVa P']}）；"
        f"XGBoost、随机森林与本模型的差异也均无统计学意义。"
    )
    methods = [
        ["研究对象", f"eICU 数据库中首次入住 ICU 的成年患者，共 {len(df):,} 例，院内死亡 {int(df.death_hosp.sum())} 例"],
        ["数据提取", "用 SQL 从原始检验表按时间窗口提取首日检验值，缺失率由 24–29% 降至 5–8%"],
        ["缺失值", "多重插补（mice，5 次）"],
        ["变量筛选", "单因素分析（限制性立方样条）→ 多因素 Logistic 回归 → AIC 向后逐步回归"],
        ["内部验证", "Bootstrap 1000 次，每次重做变量筛选"],
        ["外部验证", "中西部、南部医院建模，西部、东北部医院验证"],
    ]
    return {
        "cohort": {
            "n": len(df),
            "deaths": int(df.death_hosp.sum()),
            "mortality": float(df.death_hosp.mean()),
            "hospitals": int(df.hospitalid.nunique()),
        },
        "headline_auc": auc_only(lr_val["AUC"]),
        "performance": performance,
        "performance_note": note,
        "methods": methods,
    }


def sql_excerpt() -> str:
    """从 01_cohort.sql 截取用窗口函数取首次 ICU 入住的那一段，展示在网页上。"""
    lines = (ROOT / "sql" / "01_cohort.sql").read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if "CREATE OR REPLACE TABLE stay_base" in l)
    end = next(i for i, l in enumerate(lines) if "AS stay_seq" in l)
    # 去掉与窗口函数无关的普通字段，让节选更聚焦
    skip = {"p.patienthealthsystemstayid,", "p.hospitalid,", "h.region,", "p.ethnicity,", "p.unittype,",
            "p.unitadmitsource,", "p.admissionheight,", "p.admissionweight,"}
    keep = [l for l in lines[start:end + 1] if l.strip() not in skip]
    return textwrap.dedent("\n".join(keep)) + "\nFROM patient p\nLEFT JOIN hospital h USING (hospitalid);"


def render(template: str, data: dict, fragment_name: str, standalone_name: str) -> None:
    # 防止 JSON 里的 "</" 提前结束 <script> 标签
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    fragment = (DASH / template).read_text(encoding="utf-8").replace("__DATA_JSON__", payload)
    (DASH / fragment_name).write_text(fragment, encoding="utf-8")

    head, body = fragment.split("</style>", 1)
    standalone = (
        '<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"{head}</style>\n</head>\n<body>{body}</body>\n</html>\n"
    )
    (DASH / standalone_name).write_text(standalone, encoding="utf-8")
    print(f"已生成 {DASH / standalone_name}")
    print(f"已生成 {DASH / fragment_name}")


def main() -> None:
    model = json.loads((MODEL_DIR / "model.json").read_text(encoding="utf-8"))
    for key in ("performance", "test_cases"):
        model.pop(key, None)
    report = build_report()
    render("template.html", {"model": model, "report": report}, "calculator.html", "index.html")

    df = pd.read_csv(PROCESSED / "analysis_dataset.csv")
    steps = pd.read_csv(TABLES / "cohort_steps.csv", encoding="utf-8-sig")
    showcase = {
        "model": model,
        "report": report,
        "split": {
            "dev": [int((df.cohort_split == "development").sum()), int(df.loc[df.cohort_split == "development", "death_hosp"].sum())],
            "val": [int((df.cohort_split == "validation").sum()), int(df.loc[df.cohort_split == "validation", "death_hosp"].sum())],
        },
        "cohort_steps": steps[["step", "description", "n", "deaths"]].to_dict(orient="records"),
        "missing": missing_comparison(df).to_dict(orient="records"),
        "roc": json.loads((MODEL_DIR / "roc_validation.json").read_text(encoding="utf-8")),
        "shap": json.loads((MODEL_DIR / "shap_importance.json").read_text(encoding="utf-8")),
        "sql": sql_excerpt(),
    }
    render("showcase_template.html", showcase, "showcase_artifact.html", "showcase.html")


if __name__ == "__main__":
    main()
