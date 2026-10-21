"""第 1 步：执行 sql/ 下的提数脚本，生成分析数据集和患者筛选流程表。

用法：.venv/Scripts/python.exe src/build_dataset.py
输出：
  data/processed/analysis_dataset.csv   分析用宽表（一行一位患者）
  results/tables/cohort_steps.csv       纳入排除每一步的例数（画流程图用）
"""
from db import PROCESSED, ROOT, connect, run_sql_file

SQL_FILES = [
    "01_cohort.sql",
    "02_apache_features.sql",
    "03_lab_first24h.sql",
    "04_analysis_dataset.sql",
]


def main() -> None:
    con = connect()
    for name in SQL_FILES:
        run_sql_file(con, name)
        print(f"已执行 {name}")

    PROCESSED.mkdir(parents=True, exist_ok=True)
    tables = ROOT / "results" / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    df = con.sql("SELECT * FROM analysis_dataset").df()
    df.to_csv(PROCESSED / "analysis_dataset.csv", index=False, encoding="utf-8")

    steps = con.sql("SELECT * FROM cohort_steps").df()
    steps.to_csv(tables / "cohort_steps.csv", index=False, encoding="utf-8-sig")

    print("\n患者筛选流程：")
    for row in steps.itertuples():
        print(f"  {row.step}. {row.description}：{row.n} 例（死亡 {row.deaths} 例）")
    split = df.groupby("cohort_split")["death_hosp"].agg(["count", "sum"])
    print("\n建模组 / 验证组：")
    for name, row in split.iterrows():
        print(f"  {name}：{row['count']} 例，死亡 {row['sum']} 例（{row['sum'] / row['count']:.1%}）")


if __name__ == "__main__":
    main()
