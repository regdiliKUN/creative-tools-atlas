# -*- coding: utf-8 -*-
"""把软件包与构建脚本同步进 git 仓库 creative-tools-atlas（第二十轮）。只复制、不删除仓库里的文件。

映射：软件包根目录的 HTML → 仓库根；icon → assets/；CHANGELOG / MANIFEST / 使用说明 / 迭代记录 → docs/；
快捷方式工具/ → tools/（排除运行时数据）；构建 / 门禁 / 启动器源码 → src/。
用法：python sync_repo.py   （输出 SYNC_OK 与复制的文件数）"""
import shutil
import sys
from pathlib import Path

BUILD = Path(__file__).resolve().parent
PKG = BUILD.parent / "创作工具星图"
REPO = BUILD.parent / "creative-tools-atlas"
RUNTIME = {"jobs.json", "tool-bridge.log", "tool-bridge.log.1", "start-all.log", "install-state.json", ".krita_token",
           "krita_session.json", "krita_session.ack", "krita_session.json.tmp", "translate_cache.json",
           "translate_cache.json.tmp", "jobs.json.tmp", "translator_download.log"}
SRC_FILES = ["launcher.py", "build_manifest.py", "selftest.py", "v10_verify.py", "v11_verify.py", "test_e2e_automation.py",
             "test_automation.js", "verify_exec_buttons.js", "v10_script.js", "run_all_gates.bat",
             "rebuild_launcher.py", "rebuild_launcher.bat", "sync_repo.py", "real_to3d_test.py"]


def copy(src, dst, n):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file() or dst.read_bytes() != src.read_bytes():
        shutil.copy2(str(src), str(dst))
        n[0] += 1


def main():
    n = [0]
    for f in PKG.glob("*.html"):
        copy(f, REPO / f.name, n)
    for f in ("icon.ico", "icon.png"):
        copy(PKG / f, REPO / "assets" / f, n)
    for f in ("CHANGELOG.md", "MANIFEST.md", "使用说明.txt"):
        copy(PKG / f, REPO / "docs" / f, n)
    for f in (PKG / "迭代记录").glob("*.md"):
        copy(f, REPO / "docs" / "迭代记录" / f.name, n)
    tools = PKG / "快捷方式工具"
    for f in tools.rglob("*"):
        if not f.is_file() or "__pycache__" in f.parts or f.name in RUNTIME or f.suffix in (".bak", ".pyc", ".tmp"):
            continue
        copy(f, REPO / "tools" / f.relative_to(tools), n)
    for f in SRC_FILES:
        if (BUILD / f).is_file():
            copy(BUILD / f, REPO / "src" / f, n)
    print("SYNC_OK copied=%d" % n[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
