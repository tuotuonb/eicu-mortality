"""DuckDB 连接：把 data/raw 下的 eICU 原始 csv.gz 注册成同名视图，SQL 里直接按表名查询。"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
SQL_DIR = ROOT / "sql"


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for f in sorted(RAW.glob("*.csv.gz")):
        table = f.name.removesuffix(".csv.gz").lower()
        # 全部列按 CSV 自动推断类型；eICU 的缺失值是空字符串
        con.execute(
            f"CREATE OR REPLACE VIEW {table} AS "
            f"SELECT * FROM read_csv_auto('{f.as_posix()}', header=true, sample_size=-1)"
        )
    return con


def run_sql_file(con: duckdb.DuckDBPyConnection, name: str) -> None:
    """执行 sql/ 下的一个脚本（可包含多条语句）。"""
    con.execute((SQL_DIR / name).read_text(encoding="utf-8"))
