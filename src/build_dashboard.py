"""第 8 步：生成网页。

把模型系数（results/model/）和性能结果（results/tables/）写进网页模板。

  dashboard/template.html          → dashboard/index.html（完整网页）、dashboard/calculator.html（Artifact 版）
                                     简洁版风险计算器
  dashboard/showcase_template.html → dashboard/showcase.html（在线版，下载按钮指向 GitHub Pages 上的文件）
                                     dashboard/showcase_artifact.html（Artifact 版，不显示下载区）
                                     dist/showcase_offline.html（离线包用，下载按钮指向同一文件夹里的文件）

所有页面都是单文件：数据、图表、列线图图片都内嵌在页面里，只有字体从 Google Fonts 异步加载（加载不到时用系统字体）。
"""
import base64
import io
import json
import textwrap

import pandas as pd
from PIL import Image

from data_quality import missing_comparison
from db import PROCESSED, ROOT

DASH = ROOT / "dashboard"
DIST = ROOT / "dist"
TABLES = ROOT / "results" / "tables"
FIGURES = ROOT / "results" / "figures"
MODEL_DIR = ROOT / "results" / "model"

REPORT_NOTE = "全部图表、表格与方法说明，按临床论文格式排版，可直接打印"
DOWNLOADS = {
    "online": [
        {"label": "研究报告（PDF）", "note": REPORT_NOTE,
         "href": "../downloads/eicu-research-report.pdf", "download": False},
        {"label": "离线包（ZIP）", "note": "展示页离线版、简洁版计算器、研究报告和源代码，断网也能使用",
         "href": "../downloads/eicu-offline-package.zip", "download": True},
    ],
    "offline": [
        {"label": "研究报告（PDF）", "note": REPORT_NOTE, "href": "研究报告.pdf", "download": False},
        {"label": "源代码（ZIP）", "note": "SQL、R、Python 全部源码与 README", "href": "源代码.zip", "download": True},
    ],
    "artifact": [],
}


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


def baseline_rows() -> list:
    """Table 1 中最能说明差异的几行：存活 vs 死亡。"""
    t1 = pd.read_csv(TABLES / "table1_by_outcome.csv", encoding="utf-8-sig", dtype=str).fillna("")
    wanted = ["n", "年龄", "GCS 评分", "平均动脉压", "肌酐（", "乳酸（最高值）", "首日机械通气", "APACHE IV 评分"]
    rows = []
    for w in wanted:
        hit = t1[t1["变量"].str.startswith(w)]
        if hit.empty:
            continue
        r = hit.iloc[0]
        label = (r["变量"].replace(" (median [IQR])", "").replace(" = 是 (%)", "（%）")
                 .replace("n", "例数", 1) if w == "n" else
                 r["变量"].replace(" (median [IQR])", "").replace(" = 是 (%)", "（%）"))
        rows.append({"label": label, "alive": r["存活"], "dead": r["死亡"], "p": r["p"]})
    return rows


def forest_rows() -> list:
    t3 = pd.read_csv(TABLES / "table3_multivariable.csv", encoding="utf-8-sig")
    return [{"label": r["中文名"].split("（")[0], "contrast": r["对比"],
             "or": float(r["OR"]), "lo": float(r["CI下限"]), "hi": float(r["CI上限"])} for _, r in t3.iterrows()]


def model_summary(model: dict) -> dict:
    t2 = pd.read_csv(TABLES / "table2_univariate.csv", encoding="utf-8-sig", dtype=str)
    significant = t2["P"].map(lambda p: p == "<0.001" or (p not in ("", "nan") and float(p) < 0.05))
    return {"n_candidates": len(t2), "n_univariate": int(significant.sum()), "n_final": len(model["variables"])}


def nomogram_data_uri() -> str:
    """列线图缩小后转成 WebP，直接内嵌进页面。"""
    img = Image.open(FIGURES / "fig3_nomogram.png").convert("RGB")
    img = img.resize((1400, round(img.height * 1400 / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82, method=6)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def calibration_series() -> list:
    cal = json.loads((MODEL_DIR / "calibration.json").read_text(encoding="utf-8"))
    out = []
    for key, name, color in [("B：本研究模型", "本研究模型", "--m-lr"), ("B：APACHE IVa", "APACHE IVa", "--m-apache")]:
        c = cal[key]
        step = max(1, len(c["pred"]) // 120)
        idx = list(range(0, len(c["pred"]), step)) + [len(c["pred"]) - 1]
        out.append({"name": name, "color": color, "pred": [c["pred"][i] for i in idx], "obs": [c["obs"][i] for i in idx]})
    return out


def calibration_note() -> str:
    perf = pd.read_csv(TABLES / "table4_performance.csv", encoding="utf-8-sig")
    lr = perf[(perf["数据集"] == "验证组") & (perf["模型"] == "本研究模型")].iloc[0]
    ap = perf[(perf["数据集"] == "验证组（有 APACHE 预测者）") & (perf["模型"] == "APACHE IVa")].iloc[0]
    return (f"外部验证组中，本模型的校准斜率为 {lr['校准斜率']}（理想值为 1），APACHE IVa 为 {ap['校准斜率']}。"
            "斜率小于 1 说明本模型的预测偏极端，这与样本量有限有关；在新医院使用前，应先用当地数据重新校准。")


def dca_series() -> list:
    dca = json.loads((MODEL_DIR / "dca_validation.json").read_text(encoding="utf-8"))
    style = {"本研究模型": ("--m-lr", 2.4, ""), "APACHE IVa": ("--m-apache", 2.2, ""),
             "全部干预": ("--dim", 1.6, "5 4"), "均不干预": ("--muted", 1.4, "")}
    return [{"name": n, "color": style[n][0], "width": style[n][1], "dash": style[n][2],
             "threshold": dca[n]["threshold"], "net_benefit": dca[n]["net_benefit"]} for n in style if n in dca]


def render(template: str, data: dict, fragment_path=None, standalone_path=None) -> None:
    # 防止 JSON 里的 "</" 提前结束 <script> 标签
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    fragment = (DASH / template).read_text(encoding="utf-8").replace("__DATA_JSON__", payload)
    if fragment_path:
        fragment_path.write_text(fragment, encoding="utf-8")
        print(f"已生成 {fragment_path}")
    if standalone_path:
        head, body = fragment.split("</style>", 1)
        standalone = (
            '<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"{head}</style>\n</head>\n<body>{body}</body>\n</html>\n"
        )
        standalone_path.write_text(standalone, encoding="utf-8")
        print(f"已生成 {standalone_path}（{len(standalone.encode()) / 1024:.0f} KB）")


def main() -> None:
    model = json.loads((MODEL_DIR / "model.json").read_text(encoding="utf-8"))
    for key in ("performance", "test_cases"):
        model.pop(key, None)
    report = build_report()
    render("template.html", {"model": model, "report": report}, DASH / "calculator.html", DASH / "index.html")

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
        "baseline": baseline_rows(),
        "forest": forest_rows(),
        "model_summary": model_summary(model),
        "nomogram": nomogram_data_uri(),
        "roc": json.loads((MODEL_DIR / "roc_validation.json").read_text(encoding="utf-8")),
        "calibration": calibration_series(),
        "cal_note": calibration_note(),
        "dca": dca_series(),
        "shap": json.loads((MODEL_DIR / "shap_importance.json").read_text(encoding="utf-8")),
        "sql": sql_excerpt(),
    }
    DIST.mkdir(exist_ok=True)
    render("showcase_template.html", {**showcase, "downloads": DOWNLOADS["online"]}, None, DASH / "showcase.html")
    render("showcase_template.html", {**showcase, "downloads": DOWNLOADS["artifact"]}, DASH / "showcase_artifact.html")
    render("showcase_template.html", {**showcase, "downloads": DOWNLOADS["offline"]}, None, DIST / "showcase_offline.html")


if __name__ == "__main__":
    main()
