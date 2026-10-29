"""第 10 步：打包离线材料。

公开版（发布到 GitHub Pages 供下载，不含任何个人信息）：
  downloads/eicu-offline-package.zip   展示页离线版、简洁版计算器、研究报告、源代码
  downloads/eicu-research-report.pdf   研究报告

个人版（另外放入简历等个人材料，只保存在本机，不要提交到仓库）：
  .venv/Scripts/python.exe src/build_package.py --personal <输出 zip> --extra <简历.pdf> [<面试讲解稿.pdf> ...]
"""
import argparse
import shutil
import subprocess
import zipfile
from pathlib import Path

from db import ROOT

DIST = ROOT / "dist"
DOWNLOADS = ROOT / "downloads"
FOLDER = "eICU项目离线包"

GUIDE = """eICU 院内死亡风险预测项目 · 离线包

文件说明
  展示页.html          项目展示页（含风险计算器），双击用浏览器打开，断网也能使用
  简洁版计算器.html    只有风险计算器的简洁版本，适合打印或在旧电脑上使用
  研究报告.pdf         按临床论文格式整理的完整研究报告，可直接打印
  源代码.zip           SQL、R、Python 全部源码与 README（不含数据；运行 run_all.py 会下载开放数据并复现全部结果）

在线版本：https://tuotuonb.github.io/eicu-mortality/

本项目仅用于科研与教学演示，不能用于临床决策。
数据来自 eICU Collaborative Research Database Demo v2.0.1（PhysioNet，开放获取）。
"""


def source_zip(path: Path) -> None:
    """按 git 管理的文件打包源代码（已提交的文件和尚未提交但不被忽略的新文件），不含下载区和数据。"""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                         cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8")
    files = sorted({f for f in out.split("\0") if f and not f.startswith("downloads/")})
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            if (ROOT / f).is_file():
                z.write(ROOT / f, f"eicu-mortality/{f}")


def package(out_zip: Path, extras: list[Path]) -> None:
    stage = DIST / "package"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    shutil.copy(DIST / "showcase_offline.html", stage / "展示页.html")
    shutil.copy(ROOT / "dashboard" / "index.html", stage / "简洁版计算器.html")
    shutil.copy(DIST / "研究报告.pdf", stage / "研究报告.pdf")
    source_zip(stage / "源代码.zip")
    (stage / "使用说明.txt").write_text(GUIDE.replace("\n", "\r\n"), encoding="utf-8-sig")
    for e in extras:
        shutil.copy(e, stage / e.name)

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(stage.iterdir()):
            z.write(f, f"{FOLDER}/{f.name}")
    names = "、".join(f.name for f in sorted(stage.iterdir()))
    print(f"已生成 {out_zip}（{out_zip.stat().st_size / 1024 / 1024:.1f} MB）：{names}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personal", type=Path, help="个人版输出路径（不传则生成公开版到 downloads/）")
    parser.add_argument("--extra", type=Path, nargs="*", default=[], help="个人版额外放入的文件，如简历")
    args = parser.parse_args()

    if args.personal:
        package(args.personal, args.extra)
        return
    DOWNLOADS.mkdir(exist_ok=True)
    package(DOWNLOADS / "eicu-offline-package.zip", [])
    shutil.copy(DIST / "研究报告.pdf", DOWNLOADS / "eicu-research-report.pdf")
    print(f"已生成 {DOWNLOADS / 'eicu-research-report.pdf'}")


if __name__ == "__main__":
    main()
