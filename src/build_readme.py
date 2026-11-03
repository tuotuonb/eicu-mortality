"""由 README.md 生成 .github/README.md。

GitHub 首页会优先显示 .github/README.md，码云首页显示根目录的 README.md。
码云版面向国内访客，不写「GitHub 可能打不开」之类的提示；GitHub 版在码云版基础上加回这些说明。
修改 README.md 后运行：.venv/Scripts/python.exe src/build_readme.py
"""
import re

from db import ROOT

SRC = ROOT / "README.md"
OUT = ROOT / ".github" / "README.md"

SCREENSHOT = "(docs/images/showcase.png)](https://tuotuonb.github.io/eicu-mortality/)\n"

# （码云版原文, GitHub 版写法）
GITHUB_ONLY = [
    ("**GitHub 仓库**：[github.com/tuotuonb/eicu-mortality](https://github.com/tuotuonb/eicu-mortality)（与本仓库内容相同）",
     "**国内镜像**：[码云 gitee.com/tuotuobunni/eicu-mortality](https://gitee.com/tuotuobunni/eicu-mortality)（与 GitHub 仓库内容相同）"),
    (SCREENSHOT,
     SCREENSHOT + "\n> 在中国大陆，GitHub 页面可能打不开或图片加载不出来，可以改看上面的码云镜像，或从码云下载离线版。\n"),
    ("**安装加速**：可以使用清华镜像安装依赖：",
     "**中国大陆网络**：安装依赖时可以使用清华镜像，速度更快："),
]


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    for old, new in GITHUB_ONLY:
        # README 改了措辞却忘了改这里时，直接报错，避免两个版本悄悄不一致
        if text.count(old) != 1:
            raise SystemExit(f"README.md 中找不到（或不止一处）：{old.strip()}")
        text = text.replace(old, new)

    # 文件放在 .github/ 下，相对链接改成从仓库根目录算起
    text = re.sub(r"\]\((?!https?://|#|/)([^)]+)\)", r"](/\1)", text)

    header = "<!-- 由 src/build_readme.py 从 README.md 生成，请改 README.md 后重新运行 -->\n"
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + text)
    print(f"已生成 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
