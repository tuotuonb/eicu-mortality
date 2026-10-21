"""第 0 步：从 PhysioNet 下载 eICU Demo 中本项目用到的数据表，并做 SHA256 校验。

eICU-CRD Demo v2.0.1 是开放获取数据集，不需要申请权限。
用法：.venv/Scripts/python.exe src/download_data.py
"""
import hashlib
import urllib.request

from db import RAW

BASE = "https://physionet.org/files/eicu-crd-demo/2.0.1/"
TABLES = [
    "patient", "hospital", "apachePatientResult", "apacheApsVar",
    "apachePredVar", "lab", "diagnosis", "admissionDx", "pastHistory",
]


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    sums_text = urllib.request.urlopen(BASE + "SHA256SUMS.txt").read().decode()
    expected = {name: digest for digest, name in (line.split() for line in sums_text.splitlines() if line.strip())}

    for t in TABLES:
        name = f"{t}.csv.gz"
        dest = RAW / name
        if dest.exists() and sha256(dest) == expected.get(name):
            print(f"已存在且校验通过：{name}")
            continue
        print(f"下载 {name} ...")
        urllib.request.urlretrieve(BASE + name, dest)
        ok = sha256(dest) == expected.get(name)
        print(f"  校验{'通过' if ok else '失败，请重新运行'}")


if __name__ == "__main__":
    main()
