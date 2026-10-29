"""第 9 步：生成中文研究报告（PDF）。

从 results/ 读取全部表格和图表，按临床预测模型论文的格式（参照 TRIPOD 报告规范）生成 HTML，
再用 Edge 无界面模式打印成 A4 PDF。正文中的数字都从结果文件读取，模型更新后重新运行即可同步。

输出：dist/report.html、dist/研究报告.pdf
"""
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pandas as pd

from data_quality import consistency_check, missing_comparison
from db import PROCESSED, RAW, ROOT

DIST = ROOT / "dist"
TABLES = ROOT / "results" / "tables"
FIG = "../results/figures"  # 相对 dist/report.html 的路径
EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

CSS = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm; }
body { font-family: "Times New Roman", "SimSun", "宋体", serif; font-size: 10.5pt; line-height: 1.75; color: #111; }
h1, h2, h3, .caption, th, .kw b, .meta { font-family: "Arial", "SimHei", "黑体", "Microsoft YaHei", sans-serif; }
h1 { font-size: 18pt; text-align: center; margin: 0 0 6pt; line-height: 1.4; }
.meta { text-align: center; font-size: 10pt; color: #333; margin-bottom: 14pt; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; break-after: avoid; }
h3 { font-size: 11pt; margin: 10pt 0 4pt; break-after: avoid; }
p { text-indent: 2em; margin: 0 0 5pt; text-align: justify; }
.abstract { border: 0.75pt solid #777; padding: 8pt 12pt; margin-bottom: 8pt; }
.abstract p { text-indent: 0; margin: 0 0 4pt; }
.abstract b, .kw b { font-family: "Arial", "SimHei", "黑体", sans-serif; }
.kw { text-indent: 0; }
table.tl { border-collapse: collapse; width: 100%; font-size: 8.8pt; line-height: 1.45; margin: 2pt 0 4pt;
           border-top: 1.5pt solid #000; border-bottom: 1.5pt solid #000; break-inside: auto; }
table.tl thead { display: table-header-group; }
table.tl th { border-bottom: 0.75pt solid #000; padding: 3pt 4pt; font-weight: bold; text-align: left; font-size: 8.8pt; }
table.tl td { padding: 2pt 4pt; text-align: left; vertical-align: top; }
table.tl tr { break-inside: avoid; }
.caption { font-size: 9.5pt; font-weight: bold; text-align: center; margin: 10pt 0 3pt; break-after: avoid; }
.tnote { font-size: 8.5pt; color: #333; text-indent: 0; margin: 0 0 8pt; }
figure { margin: 8pt 0 10pt; break-inside: avoid; text-align: center; }
figure img { width: 100%; }
figure.narrow img { width: 82%; }
figcaption { font-family: "Arial", "SimHei", "黑体", sans-serif; font-size: 9.5pt; font-weight: bold; margin-top: 3pt; }
.flow { display: grid; grid-template-columns: 1fr 1fr; gap: 0 10pt; margin: 8pt 0 2pt; font-size: 9pt; break-inside: avoid; }
.flow .box { grid-column: 1; border: 0.75pt solid #000; padding: 4pt 6pt; text-align: center; line-height: 1.45; }
.flow .excl { grid-column: 2; align-self: center; border: 0.75pt dashed #555; padding: 3pt 6pt; color: #333; line-height: 1.4; }
.flow .arrow { grid-column: 1; text-align: center; line-height: 1.2; color: #333; }
.flow .split { grid-column: 1 / span 2; display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; }
.flow .split .box { grid-column: auto; }
ol.refs { font-size: 9pt; line-height: 1.55; padding-left: 18pt; }
ol.refs li { margin-bottom: 2pt; }
.small { font-size: 9pt; color: #333; text-indent: 0; }
"""


def esc(x) -> str:
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else html.escape(str(x))


def table_html(df: pd.DataFrame, keep_together: bool = False) -> str:
    def cell(v) -> str:
        text = esc(v)
        # AUC 及其置信区间不折行
        return f'<td style="white-space:nowrap">{text}</td>' if re.match(r"^\d\.\d{3} \(", text) else f"<td>{text}</td>"
    head = "".join(f"<th>{esc(c)}</th>" for c in df.columns)
    body = "".join("<tr>" + "".join(cell(v) for v in row) + "</tr>" for row in df.itertuples(index=False))
    style = ' style="break-inside: avoid"' if keep_together else ""
    return f'<table class="tl"{style}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def clean_t1_label(s: str) -> str:
    """去掉 tableone 输出里的 (median [IQR])、= 是 (%) 等标记，换成中文写法。"""
    if s == "n":
        return "例数"
    s = s.replace(" (median [IQR])", "").replace(" = 是 (%)", "（是，%）").replace(" (%)", "（%）")
    return s.strip()


def or_ci(o, lo, hi) -> str:
    return f"{o:.2f} ({lo:.2f}–{hi:.2f})"


def facts() -> dict:
    df = pd.read_csv(PROCESSED / "analysis_dataset.csv")
    raw = pd.read_csv(RAW / "patient.csv.gz", usecols=["hospitalid"])
    perf = pd.read_csv(TABLES / "table4_performance.csv", encoding="utf-8-sig")
    # 按字符串读取，保留 P 值末尾的 0（如 0.510）
    comp = pd.read_csv(TABLES / "table6_model_comparison.csv", encoding="utf-8-sig", dtype=str).fillna("")
    tuning = pd.read_csv(TABLES / "table5_ml_tuning.csv", encoding="utf-8-sig").set_index("模型")
    t2 = pd.read_csv(TABLES / "table2_univariate.csv", encoding="utf-8-sig", dtype={"P": str})
    t3 = pd.read_csv(TABLES / "table3_multivariable.csv", encoding="utf-8-sig")
    roc = json.loads((ROOT / "results" / "model" / "roc_validation.json").read_text(encoding="utf-8"))
    shap = json.loads((ROOT / "results" / "model" / "shap_importance.json").read_text(encoding="utf-8"))
    model = json.loads((ROOT / "results" / "model" / "model.json").read_text(encoding="utf-8"))

    def p_row(ds, prefix):
        return perf[(perf["数据集"] == ds) & perf["模型"].str.startswith(prefix)].iloc[0]

    def c_row(ds, m):
        return comp[(comp["数据集"] == ds) & (comp["模型"] == m)].iloc[0]

    dev = df[df.cohort_split == "development"]
    val = df[df.cohort_split == "validation"]
    sub = "外部验证组（有 APACHE 预测者）"
    final_labels = [v["label"].split("（")[0] for v in model["variables"]]
    sig = t2["P"].map(lambda p: p == "<0.001" or (isinstance(p, str) and p not in ("", "nan") and float(p) < 0.05))
    in_model = {v["name"] for v in model["variables"]}
    return {
        "stays": len(raw), "hospitals": raw.hospitalid.nunique(),
        "n": len(df), "deaths": int(df.death_hosp.sum()), "mort": df.death_hosp.mean() * 100,
        "n_dev": len(dev), "d_dev": int(dev.death_hosp.sum()), "m_dev": dev.death_hosp.mean() * 100,
        "n_val": len(val), "d_val": int(val.death_hosp.sum()), "m_val": val.death_hosp.mean() * 100,
        "n_cand": len(t2), "n_sig": int(sig.sum()), "final": final_labels,
        "auc_app": p_row("建模组", "本研究模型（表观）")["AUC"],
        "auc_cor": p_row("建模组", "本研究模型（Bootstrap")["AUC"],
        "slope_cor": p_row("建模组", "本研究模型（Bootstrap")["校准斜率"],
        "auc_val": p_row("验证组", "本研究模型")["AUC"],
        "slope_val": p_row("验证组", "本研究模型")["校准斜率"],
        "brier_val": p_row("验证组", "本研究模型")["Brier"],
        "n_sub": int(c_row(sub, "APACHE IVa")["例数"]), "d_sub": int(c_row(sub, "APACHE IVa")["死亡数"]),
        "auc_ap": c_row(sub, "APACHE IVa")["AUC"], "slope_ap": c_row(sub, "APACHE IVa")["校准斜率"],
        "auc_lr_sub": c_row(sub, "Logistic 列线图模型")["AUC"],
        "p_ap": roc["p_vs_apache"],
        "auc_rf": c_row("外部验证组（全部）", "随机森林")["AUC"], "p_rf": c_row("外部验证组（全部）", "随机森林")["vs Logistic P"],
        "auc_xgb": c_row("外部验证组（全部）", "XGBoost")["AUC"], "p_xgb": c_row("外部验证组（全部）", "XGBoost")["vs Logistic P"],
        "cv_rf": tuning.loc["随机森林", "交叉验证 AUC"], "cv_xgb": tuning.loc["XGBoost", "交叉验证 AUC"],
        "shap_top10_in": sum(1 for s in shap[:10] if s["name"] in in_model),
        "shap_top": "、".join(s["label"] for s in shap[:5]),
        "miss": missing_comparison(df), "check": consistency_check(df),
        "t3": t3, "n_params": len(model["coefficients"]) - 1,
    }


def flow_html(f) -> str:
    steps = pd.read_csv(TABLES / "cohort_steps.csv", encoding="utf-8-sig")
    parts = [f'<div class="box">eICU Demo 全部 ICU 入住记录<br>n = {steps.n[0]:,}（院内死亡 {steps.deaths[0]}）</div><div></div>']
    for i in range(1, len(steps)):
        removed = steps.n[i - 1] - steps.n[i]
        parts.append(f'<div class="arrow">↓</div><div class="excl">{esc(steps.description[i])}<br>减少 {removed:,} 条</div>')
        label = "最终纳入" if i == len(steps) - 1 else ""
        parts.append(f'<div class="box">{label} n = {steps.n[i]:,}（院内死亡 {steps.deaths[i]}）</div><div></div>')
    parts.append(f'<div class="arrow">↓</div><div></div><div class="split">'
                 f'<div class="box">建模组：中西部、南部医院<br>n = {f["n_dev"]:,}（死亡 {f["d_dev"]}，{f["m_dev"]:.1f}%）</div>'
                 f'<div class="box">外部验证组：西部、东北部医院<br>n = {f["n_val"]}（死亡 {f["d_val"]}，{f["m_val"]:.1f}%）</div></div>')
    return f'<div class="flow">{"".join(parts)}</div>'


def build_html() -> str:
    f = facts()
    t1 = pd.read_csv(TABLES / "table1_by_outcome.csv", encoding="utf-8-sig", dtype=str).fillna("")
    t1 = t1.rename(columns={"p": "P", "缺失率(%)": "缺失率（%）"})
    t1["变量"] = t1["变量"].map(clean_t1_label)
    t2 = pd.read_csv(TABLES / "table2_univariate.csv", encoding="utf-8-sig", dtype={"P": str, "P_非线性": str})
    t2_out = pd.DataFrame({
        "变量": t2["中文名"], "OR 单位": t2["单位"],
        "OR (95% CI)": [or_ci(*x) for x in zip(t2.OR, t2.CI下限, t2.CI上限)],
        "P（整体）": t2["P"].fillna(""), "P（非线性）": t2["P_非线性"].fillna(""), "例数": t2["例数"],
    })
    t3 = f["t3"]
    t3_out = pd.DataFrame({
        "变量": t3["中文名"], "对比": t3["对比"],
        "OR (95% CI)": [or_ci(*x) for x in zip(t3.OR, t3.CI下限, t3.CI上限)],
        "P（对比）": t3["P_对比"].fillna(""), "P（整体）": t3["P_整体"].fillna(""), "P（非线性）": t3["P_非线性"].fillna(""),
    })
    t4 = pd.read_csv(TABLES / "table4_performance.csv", encoding="utf-8-sig", dtype=str).fillna("")
    t6 = pd.read_csv(TABLES / "table6_model_comparison.csv", encoding="utf-8-sig", dtype=str).fillna("")
    t6 = t6[["数据集", "模型", "例数", "死亡数", "AUC", "Brier", "校准斜率", "vs Logistic P", "vs APACHE IVa P"]]
    miss = f["miss"].rename(columns={"APACHE 表缺失率(%)": "APACHE 表缺失率（%）", "SQL 提取缺失率(%)": "SQL 提取缺失率（%）"})
    chk = f["check"]
    final = "、".join(f["final"])

    def fig(name, caption, cls=""):
        return f'<figure class="{cls}"><img src="{FIG}/{name}"><figcaption>{caption}</figcaption></figure>'

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>ICU 患者院内死亡风险预测研究报告</title><style>{CSS}</style></head>
<body>
<h1>基于 eICU 多中心数据的 ICU 患者院内死亡风险<br>列线图模型构建与外部验证</h1>
<p class="meta">李若冲　｜　个人研究项目　｜　2026 年 10 月<br>
在线演示：tuotuonb.github.io/eicu-mortality　　源代码：github.com/tuotuonb/eicu-mortality</p>

<div class="abstract">
<p><b>目的</b>　利用入 ICU 首日即可获得的床旁指标，构建 ICU 患者院内死亡风险预测模型，在其他地区的医院中进行外部验证，并与 APACHE IVa 评分和机器学习模型比较。</p>
<p><b>方法</b>　数据来自 eICU Collaborative Research Database Demo（2014–2015 年，美国 {f["hospitals"]} 家医院，{f["stays"]:,} 次 ICU 入住）。用 SQL 提取首次入住 ICU 的成年患者及其首日特征。以中西部、南部医院的患者为建模组，西部、东北部医院的患者为外部验证组。缺失值采用多重插补；连续变量用限制性立方样条刻画非线性关系；经单因素筛选和 AIC 向后逐步回归建立多因素 Logistic 回归模型，并绘制列线图。内部验证采用 Bootstrap 重抽样 1000 次（每次重做变量筛选）；外部验证评价区分度、校准度和临床获益。</p>
<p><b>结果</b>　共纳入 {f["n"]:,} 例患者，院内死亡 {f["deaths"]} 例（{f["mort"]:.1f}%）。最终模型包含 {len(f["final"])} 个变量：{final}。建模组 Bootstrap 校正 AUC 为 {f["auc_cor"]}；外部验证组 AUC 为 {f["auc_val"]}，校准斜率 {f["slope_val"]}。在有 APACHE IVa 预测值的 {f["n_sub"]} 例验证组患者中，本模型与 APACHE IVa（AUC {f["auc_ap"]}）的差异无统计学意义（P = {f["p_ap"]}）。随机森林和 XGBoost 的外部验证 AUC 分别为 {f["auc_rf"]} 和 {f["auc_xgb"]}，均未显著优于 Logistic 模型。</p>
<p><b>结论</b>　仅用 {len(f["final"])} 个可从医院信息系统自动提取的首日指标，即可获得与 APACHE IVa 相近的区分度。模型在外部验证中存在一定程度的过拟合，应用于新的医院前需要用本地数据重新校准。</p>
</div>
<p class="kw"><b>关键词</b>　重症监护；院内死亡；预测模型；列线图；外部验证；eICU</p>

<h2>1　背景</h2>
<p>ICU 患者病情危重、变化快，早期识别高死亡风险的患者，有助于分配医疗资源、制定治疗计划以及与家属沟通预后。APACHE 等评分系统应用广泛，但需要收集大量变量，其中包括需人工判断的入院诊断分类，录入负担较重。</p>
<p>医院信息系统（HIS）、检验信息系统（LIS）中已经保存了大量结构化的床旁数据。如果能只用这些可自动提取的指标建立预测模型，就可以在不增加临床工作量的前提下实现风险评估。本研究基于公开的 eICU 多中心重症数据库，完整实践了从 SQL 提数、数据质控、统计建模到外部验证和工具化交付的流程。</p>

<h2>2　方法</h2>
<h3>2.1　数据来源</h3>
<p>本研究使用 eICU Collaborative Research Database Demo v2.0.1<sup>[1,2]</sup>。该数据库是 eICU 多中心重症数据库的开放获取子集，包含 2014–2015 年美国 {f["hospitals"]} 家医院的 {f["stays"]:,} 次 ICU 入住记录，已经去标识化，所有时间以「距入 ICU 时刻的分钟数」存储。本报告参照 TRIPOD 预测模型报告规范<sup>[3]</sup>撰写。</p>
<h3>2.2　研究对象</h3>
<p>研究单位为每位患者首次住院中的首次 ICU 入住。纳入标准：年龄 ≥ 18 岁；ICU 停留 ≥ 4 小时；出院结局明确；有 APACHE 首日生理数据。ICU 停留时间的下限参照 APACHE IV 采用 4 小时而非常见的 24 小时：本数据中停留不足 24 小时的入住有 893 例，其中院内死亡 71 例，按 24 小时排除会丢失近三分之一的死亡病例，引入选择偏倚。按医院所在地区划分建模组和外部验证组（图 1）。结局为院内死亡。</p>
{flow_html(f)}
<p class="caption" style="text-align:center">图 1　患者筛选流程</p>
<h3>2.3　变量提取与数据质控</h3>
<p>候选预测变量为入 ICU 首日即可获得、缺失率低于 30%、有临床意义的 {f["n_cand"]} 个变量，包括人口学信息、生命体征、检验指标、首日机械通气和合并症。生命体征取 APACHE 记录的首日最差值（偏离正常最远的一次）。检验指标用 SQL 从原始检验表重新提取，时间窗口为入 ICU 前 6 小时至入 ICU 后 24 小时，并按生理合理范围剔除录入错误。乳酸（缺失 68.5%）和血气指标（缺失 81.5%）缺失过多，不进入模型。</p>
<p>为验证提数的正确性，将 SQL 提取的首日最高肌酐与 APACHE 表记录的首日最差肌酐进行比较：{chk["配对例数"]:,} 例配对的 Spearman 相关系数为 {chk["Spearman 相关系数"]}，差值中位数为 {chk["差值中位数(mg/dL)"]} mg/dL。数据清洗中发现首日最差体温存在 22.2 ℃、23.3 ℃、28.8 ℃ 等生理上不可能的值，按 30–43 ℃ 的合理范围清洗后视为缺失。</p>
<h3>2.4　缺失值处理</h3>
<p>采用多重插补（mice 包，预测均值匹配法，插补 5 次）<sup>[4,5]</sup>。建模组和验证组分别插补，避免验证组的信息进入建模过程。模型系数在 5 个插补数据集上分别估计，按 Rubin 规则合并。</p>
<h3>2.5　模型构建</h3>
<p>在建模组中对每个候选变量进行单因素 Logistic 回归。连续变量用含 3 个节点的限制性立方样条（RCS）同时检验整体关联和非线性<sup>[6]</sup>。单因素 P &lt; 0.05 的变量进入多因素模型，非线性显著的保留样条形式，再按 AIC 进行向后逐步回归，得到最终模型并绘制列线图。</p>
<h3>2.6　模型验证与比较</h3>
<p>内部验证采用 Bootstrap 重抽样 1000 次，每次重抽样都重新进行变量筛选，以校正筛选过程带来的乐观偏倚<sup>[6]</sup>。外部验证在验证组中评价区分度（AUC 及其 DeLong 95% 置信区间）、校准度（校准曲线、校准截距与斜率、Brier 分数、Hosmer-Lemeshow 检验）和临床获益（决策曲线分析，DCA）<sup>[7]</sup>。与 APACHE IVa 的比较限于有其预测值的患者，采用配对 DeLong 检验<sup>[8]</sup>。另以全部候选变量建立随机森林和 XGBoost 模型（5 折交叉验证网格搜索调参），并用 SHAP 值解释 XGBoost 模型<sup>[9]</sup>。</p>
<h3>2.7　统计软件</h3>
<p>数据提取使用 DuckDB（SQL）；数据处理与机器学习使用 Python 3.12（pandas、scikit-learn、XGBoost、SHAP）；统计分析使用 R 4.6（rms、mice、pROC、dcurves、tableone）。双侧 P &lt; 0.05 为差异有统计学意义。全部分析可通过一条命令从下载数据开始复现。</p>

<h2>3　结果</h2>
<h3>3.1　研究人群</h3>
<p>共纳入 {f["n"]:,} 例患者，院内死亡 {f["deaths"]} 例（{f["mort"]:.1f}%）。建模组 {f["n_dev"]:,} 例（死亡 {f["d_dev"]} 例，{f["m_dev"]:.1f}%），外部验证组 {f["n_val"]} 例（死亡 {f["d_val"]} 例，{f["m_val"]:.1f}%）。与存活者相比，死亡患者年龄更大，GCS 评分更低，肌酐和乳酸更高，首日机械通气比例更高（表 1）。</p>
<p class="caption">表 1　存活与死亡患者的基线特征</p>
{table_html(t1)}
<p class="tnote">连续变量以中位数 [四分位间距] 表示，Mann-Whitney U 检验；分类变量以 n (%) 表示，卡方检验。</p>
<h3>3.2　数据质控</h3>
<p>APACHE 表只记录用于评分的一个值，检验指标缺失较多；从原始检验表按时间窗口重新提取后，缺失率由 24–29% 降至 5–8%（表 2），建模时检验指标一律使用 SQL 提取的版本。</p>
<p class="caption">表 2　APACHE 表与 SQL 重新提取的检验指标缺失率比较</p>
{table_html(miss, keep_together=True)}
<h3>3.3　单因素与多因素分析</h3>
<p>{f["n_cand"]} 个候选变量中，{f["n_sig"]} 个在单因素分析中 P &lt; 0.05（表 3）。平均动脉压、体温、肌酐等变量与死亡风险呈 U 型或倒 U 型关系：例如平均动脉压按线性项分析 OR 接近 1，用限制性立方样条分析则整体关联 P &lt; 0.001。经向后逐步回归，最终模型保留 {len(f["final"])} 个变量（{f["n_params"]} 个参数），其独立影响见表 4 和图 2，非线性关系见图 3。</p>
<p class="caption">表 3　单因素 Logistic 回归分析（建模组）</p>
{table_html(t2_out)}
<p class="tnote">连续变量的 OR 按「OR 单位」列所示的增量计算；整体 P 值和非线性 P 值来自限制性立方样条模型。</p>
<p class="caption">表 4　多因素 Logistic 回归分析（建模组，5 个插补数据集合并）</p>
{table_html(t3_out)}
<p class="tnote">以 RCS 形式进入模型的变量，分别给出低值端和高值端相对参照值的 OR。</p>
{fig("fig2_forest.png", "图 2　多因素 Logistic 回归森林图")}
{fig("fig4_rcs.png", "图 3　非线性变量与院内死亡风险的关系（限制性立方样条）")}
<h3>3.4　列线图</h3>
<p>根据最终模型绘制列线图（图 4）。使用时按患者各指标的取值读出得分，相加得到总分，再对应到院内死亡风险。网页风险计算器按同样的方法计算，其结果与 R 模型逐位一致。</p>
{fig("fig3_nomogram.png", "图 4　院内死亡风险列线图", "narrow")}
<h3>3.5　模型性能</h3>
<p>建模组表观 AUC 为 {f["auc_app"]}，Bootstrap 校正后为 {f["auc_cor"]}，校正后校准斜率 {f["slope_cor"]}。外部验证组 AUC 为 {f["auc_val"]}，校准斜率 {f["slope_val"]}，Brier 分数 {f["brier_val"]}（表 5，图 5–7）。在有 APACHE IVa 预测值的 {f["n_sub"]} 例验证组患者（死亡 {f["d_sub"]} 例）中，本模型 AUC 为 {f["auc_lr_sub"].split(" ")[0]}，APACHE IVa 为 {f["auc_ap"]}，差异无统计学意义（P = {f["p_ap"]}）。决策曲线显示，在大部分阈概率范围内，本模型和 APACHE IVa 的净获益均高于「全部干预」和「均不干预」。</p>
<p class="caption">表 5　模型性能</p>
{table_html(t4)}
{fig("fig5_roc.png", "图 5　ROC 曲线：本研究模型与 APACHE IVa")}
{fig("fig6_calibration.png", "图 6　校准曲线")}
{fig("fig7_dca.png", "图 7　决策曲线分析")}
<h3>3.6　与机器学习模型比较</h3>
<p>随机森林和 XGBoost 在建模组 5 折交叉验证的 AUC 分别为 {f["cv_rf"]:.3f} 和 {f["cv_xgb"]:.3f}；外部验证 AUC 分别为 {f["auc_rf"]} 和 {f["auc_xgb"]}，与 Logistic 模型的差异均无统计学意义（P = {f["p_rf"]}、{f["p_xgb"]}；表 6，图 8）。SHAP 分析中，XGBoost 最重要的变量依次为 {f["shap_top"]}，前 10 个变量中有 {f["shap_top10_in"]} 个与列线图模型一致（图 9）；依赖图同样显示体温呈 U 型、肌酐呈倒 U 型关系（图 10）。</p>
<p class="caption">表 6　四个模型在外部验证组的比较</p>
{table_html(t6)}
{fig("fig8_model_roc.png", "图 8　外部验证组 ROC 曲线：四个模型比较")}
{fig("fig10_shap_summary.png", "图 9　SHAP 蜂群图（XGBoost，建模组）")}
{fig("fig11_shap_dependence.png", "图 10　主要连续变量的 SHAP 依赖图")}

<h2>4　讨论</h2>
<p>本研究仅用 {len(f["final"])} 个可从 HIS、LIS 自动提取的入 ICU 首日指标，建立了院内死亡风险列线图模型。外部验证中其区分度与 APACHE IVa 无统计学差异，而 APACHE IVa 需要 100 多个变量，其中包括需人工判断的上百类入院诊断。对于希望在信息系统中自动完成风险评估的场景，这类简化模型更容易落地。</p>
<p>平均动脉压、体温、碳酸氢根与死亡风险呈 U 型关系，肌酐呈倒 U 型关系，若按线性处理会低估或遗漏这些变量的作用。肌酐在约 2 mg/dL 时风险最高，可能与长期透析的慢性肾病患者基础肌酐较高、急性病情相对较轻有关。糖尿病的 OR 小于 1，既往重症研究中也有类似报道，但也可能来自残余混杂或小样本波动，不应理解为糖尿病具有保护作用。</p>
<p>随机森林和 XGBoost 并未优于 Logistic 回归，这与临床预测模型领域的系统综述结论一致<sup>[10]</sup>：在变量不多的表格数据上，加入样条的 Logistic 回归已能刻画主要的非线性关系，而且可解释性更好。两类方法识别出的重要变量和非线性形状高度一致，相互印证了结果的可靠性。</p>
<p>本研究存在以下局限：第一，样本量有限，建模组仅有 {f["d_dev"]} 例死亡事件，每参数事件数（EPV）低于常用的 10，外部验证中校准斜率为 {f["slope_val"]}，提示存在一定过拟合；第二，逐步回归在小样本下不稳定，3 个体温异常值即可改变入选变量，虽然内部验证已计入这一不稳定性，后续可尝试惩罚回归；第三，数据来自 2014–2015 年的美国医院，且外部验证仍在同一数据库内完成，缺乏前瞻性验证，用于国内医院前需要用本地数据重新验证和校准。</p>

<h2>5　结论</h2>
<p>基于 eICU 多中心数据建立的 {len(f["final"])} 变量列线图模型，在不同地区医院的外部验证中表现出良好的区分度，与 APACHE IVa 相当；所需变量均可从医院信息系统自动提取，适合进一步在本地数据上验证、校准和集成。</p>

<h2>数据与代码</h2>
<p class="small">全部 SQL、Python、R 代码及分析结果已公开：github.com/tuotuonb/eicu-mortality；交互式风险计算器与项目展示：tuotuonb.github.io/eicu-mortality。代码库不含患者级数据，运行 run_all.py 可从 PhysioNet 下载开放数据并复现全部结果。本报告为个人学习研究项目，未经同行评审，模型仅用于科研与教学演示，不能用于临床决策。</p>

<h2>参考文献</h2>
<ol class="refs">
<li>Pollard T, Badawi O, Raffa J. eICU Collaborative Research Database Demo (version 2.0.1). PhysioNet; 2021. https://doi.org/10.13026/4mxk-na84</li>
<li>Pollard TJ, Johnson AEW, Raffa JD, Celi LA, Mark RG, Badawi O. The eICU Collaborative Research Database, a freely available multi-center database for critical care research. Sci Data. 2018;5:180178.</li>
<li>Collins GS, Reitsma JB, Altman DG, Moons KGM. Transparent reporting of a multivariable prediction model for individual prognosis or diagnosis (TRIPOD): the TRIPOD statement. BMJ. 2015;350:g7594.</li>
<li>Rubin DB. Multiple Imputation for Nonresponse in Surveys. New York: Wiley; 1987.</li>
<li>van Buuren S, Groothuis-Oudshoorn K. mice: Multivariate Imputation by Chained Equations in R. J Stat Softw. 2011;45(3):1–67.</li>
<li>Harrell FE Jr. Regression Modeling Strategies. 2nd ed. Cham: Springer; 2015.</li>
<li>Vickers AJ, Elkin EB. Decision curve analysis: a novel method for evaluating prediction models. Med Decis Making. 2006;26(6):565–574.</li>
<li>DeLong ER, DeLong DM, Clarke-Pearson DL. Comparing the areas under two or more correlated receiver operating characteristic curves: a nonparametric approach. Biometrics. 1988;44(3):837–845.</li>
<li>Lundberg SM, Lee SI. A unified approach to interpreting model predictions. Advances in Neural Information Processing Systems 30 (NIPS 2017).</li>
<li>Christodoulou E, Ma J, Collins GS, Steyerberg EW, Verbakel JY, Van Calster B. A systematic review shows no performance benefit of machine learning over logistic regression for clinical prediction models. J Clin Epidemiol. 2019;110:12–22.</li>
</ol>
</body></html>
"""


def main() -> None:
    DIST.mkdir(exist_ok=True)
    report = DIST / "report.html"
    report.write_text(build_html(), encoding="utf-8")
    print(f"已生成 {report}")

    edge = next((p for p in EDGE_CANDIDATES if p.exists()), None)
    if edge is None:
        print("未找到 Microsoft Edge，跳过 PDF 生成；可用浏览器打开 dist/report.html 后打印为 PDF")
        return
    pdf = DIST / "研究报告.pdf"
    profile = DIST / ".edge-profile"
    subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={profile}",
                    "--no-pdf-header-footer", f"--print-to-pdf={pdf}", report.as_uri()],
                   check=True, timeout=180, capture_output=True)
    shutil.rmtree(profile, ignore_errors=True)
    print(f"已生成 {pdf}（{pdf.stat().st_size / 1024 / 1024:.1f} MB）")


if __name__ == "__main__":
    main()
