"""第 6 步：机器学习模型对比（随机森林、XGBoost）与 SHAP 可解释性分析。

  - 使用全部 22 个候选变量，不做人工筛选
  - 随机森林：缺失值用建模组中位数插补（放在 Pipeline 里，避免验证组信息泄露）
  - XGBoost：原生支持缺失值，不插补
  - 两个模型都在建模组用 5 折交叉验证网格搜索调参（指标：AUC）
  - 建模组的预测值用交叉验证的折外预测（out-of-fold），验证组用最终模型直接预测

输出：
  results/model/predictions_ml.csv        各模型预测值（供 R/03_ml_compare.R 比较）
  results/tables/table5_ml_tuning.csv     调参结果
  results/figures/fig10_shap_summary.png  SHAP 蜂群图
  results/figures/fig11_shap_dependence.png  主要变量的 SHAP 依赖图
"""
import json
import re

import matplotlib
import numpy as np
import pandas as pd
import shap
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.model_selection import GridSearchCV, StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from xgboost import XGBClassifier

from db import PROCESSED, ROOT

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
plt.rcParams["axes.unicode_minus"] = False

SEED = 2026
FEATURES = [
    "age", "male", "heart_rate", "mean_bp", "resp_rate", "temperature", "gcs",
    "bun_max_lab", "creatinine_max_lab", "wbc_max_lab", "hemoglobin_min",
    "platelets_min", "bicarbonate_min", "potassium_max", "glucose",
    "mech_vent", "elective_surgery", "diabetes", "immunosuppression",
    "metastatic_cancer", "cirrhosis", "hematologic_cancer",
]
FIG = ROOT / "results" / "figures"
MODEL = ROOT / "results" / "model"


def chinese_labels() -> dict:
    v = pd.read_csv(ROOT / "config" / "variables.csv")
    # 去掉"首日最差值"等括注，图上更紧凑
    return {r.name: r.label.split("（")[0] for r in v.itertuples()}


def tune(estimator, grid: dict, X, y, cv) -> GridSearchCV:
    search = GridSearchCV(estimator, grid, scoring="roc_auc", cv=cv, n_jobs=-1)
    search.fit(X, y)
    return search


def main() -> None:
    df = pd.read_csv(PROCESSED / "analysis_dataset.csv")
    dev = df[df.cohort_split == "development"]
    val = df[df.cohort_split == "validation"]
    X_dev, y_dev = dev[FEATURES], dev.death_hosp
    X_val = val[FEATURES]
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)

    rf = tune(
        make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(n_estimators=500, random_state=SEED, n_jobs=-1),
        ),
        {
            "randomforestclassifier__max_depth": [3, 5, 8, None],
            "randomforestclassifier__min_samples_leaf": [5, 10, 20],
            "randomforestclassifier__max_features": ["sqrt", 0.5],
        },
        X_dev, y_dev, cv,
    )
    xgb = tune(
        XGBClassifier(subsample=0.8, colsample_bytree=0.8, eval_metric="logloss",
                      random_state=SEED, n_jobs=1),
        {
            "max_depth": [2, 3, 4],
            "min_child_weight": [1, 5, 10],
            "n_estimators": [100, 200, 400],
            "learning_rate": [0.03, 0.05],
        },
        X_dev, y_dev, cv,
    )

    tuning = pd.DataFrame([
        {"模型": "随机森林", "交叉验证 AUC": round(rf.best_score_, 3),
         "最优参数": json.dumps(rf.best_params_, ensure_ascii=False)},
        {"模型": "XGBoost", "交叉验证 AUC": round(xgb.best_score_, 3),
         "最优参数": json.dumps(xgb.best_params_, ensure_ascii=False)},
    ])
    tuning.to_csv(ROOT / "results" / "tables" / "table5_ml_tuning.csv", index=False, encoding="utf-8-sig")
    print(tuning.to_string(index=False))

    # 建模组：折外预测；验证组：最终模型预测
    pred = pd.concat([
        pd.DataFrame({
            "patientunitstayid": dev.patientunitstayid,
            "p_rf": cross_val_predict(rf.best_estimator_, X_dev, y_dev, cv=cv, method="predict_proba")[:, 1],
            "p_xgb": cross_val_predict(xgb.best_estimator_, X_dev, y_dev, cv=cv, method="predict_proba")[:, 1],
        }),
        pd.DataFrame({
            "patientunitstayid": val.patientunitstayid,
            "p_rf": rf.predict_proba(X_val)[:, 1],
            "p_xgb": xgb.predict_proba(X_val)[:, 1],
        }),
    ])
    pred.to_csv(MODEL / "predictions_ml.csv", index=False)
    print(f"已生成 {MODEL / 'predictions_ml.csv'}")

    # ---------------- SHAP：解释 XGBoost 模型（建模组）
    labels = chinese_labels()
    X_cn = X_dev.rename(columns=labels)
    explanation = shap.TreeExplainer(xgb.best_estimator_)(X_cn)

    plt.figure()
    shap.plots.beeswarm(explanation, max_display=12, show=False)
    fig = plt.gcf()
    fig.set_size_inches(9, 6.5)
    # shap 自带的英文标注换成中文
    ax, colorbar = fig.axes[0], fig.axes[-1]
    ax.set_yticklabels([re.sub(r"Sum of (\d+) other features", r"其余 \1 个变量合计", t.get_text())
                        for t in ax.get_yticklabels()])
    colorbar.set_ylabel("变量取值")
    colorbar.set_yticklabels(["低", "高"])
    plt.title("SHAP 蜂群图：XGBoost 模型中各变量对死亡风险的影响", fontsize=13)
    plt.xlabel("SHAP 值（对预测对数几率的贡献）")
    fig.tight_layout()
    fig.savefig(FIG / "fig10_shap_summary.png", dpi=300)
    plt.close(fig)
    print(f"已生成 {FIG / 'fig10_shap_summary.png'}")

    # 平均 |SHAP| 最大的 6 个连续变量画依赖图，与 Logistic 模型的 RCS 曲线相互印证
    importance = pd.Series(np.abs(explanation.values).mean(axis=0), index=X_cn.columns).sort_values(ascending=False)
    continuous = [c for c in importance.index if X_cn[c].nunique() > 2][:6]
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))
    for ax, name in zip(axes.flat, continuous):
        shap.plots.scatter(explanation[:, name], ax=ax, show=False, color="#2F6FA3", dot_size=6, alpha=0.5)
        ax.axhline(0, color="grey", linestyle="--", linewidth=0.8)
        ax.set_title(name, fontsize=11)
        ax.set_xlabel("")
        ax.set_ylabel("SHAP 值")
    fig.suptitle("SHAP 依赖图：主要连续变量与死亡风险的关系", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG / "fig11_shap_dependence.png", dpi=300)
    plt.close(fig)
    print(f"已生成 {FIG / 'fig11_shap_dependence.png'}")
    print("SHAP 重要性前 10：")
    print(importance.head(10).round(3).to_string())

    # 导出 SHAP 重要性，供展示网页绘图
    name_of = {label: name for name, label in labels.items()}
    (MODEL / "shap_importance.json").write_text(json.dumps(
        [{"name": name_of.get(k, k), "label": k, "mean_abs_shap": round(float(v), 4)} for k, v in importance.items()],
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已生成 {MODEL / 'shap_importance.json'}")


if __name__ == "__main__":
    main()
