# -*- coding: utf-8 -*-
"""重新打包桌面启动器 创作工具星图.exe，并放回软件包（第二十轮：统一入口）。
由 rebuild_launcher.bat 调用；需要本机 Python 装有 PyInstaller（当前是 Python 3.14 的用户目录）。"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "创作工具星图"
NAME = "创作工具星图"


def main():
    spec = HERE / (NAME + ".spec")
    print("[1/3] PyInstaller ...", flush=True)
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(spec)], cwd=str(HERE))
    exe = HERE / "dist" / NAME / (NAME + ".exe")
    if r.returncode != 0 or not exe.is_file():
        print("BUILD_FAILED (PyInstaller exit code %s)" % r.returncode)
        return 1
    print("[2/3] Copy into the package ...", flush=True)
    bak = HERE / "bak_r20"
    bak.mkdir(exist_ok=True)
    old = PKG / (NAME + ".exe")
    if old.is_file():
        shutil.copy2(str(old), str(bak / (NAME + ".exe.%s.bak" % time.strftime("%H%M%S"))))
    shutil.copy2(str(exe), str(old))
    shutil.copytree(str(HERE / "dist" / NAME / "_internal"), str(PKG / "_internal"), dirs_exist_ok=True)
    print("[3/3] Done:", old, flush=True)
    print("LAUNCHER_REBUILT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
