#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为软件包生成 MANIFEST.md（文件清单 + SHA-256 基线）。构建期工具。

包目录解析优先级（构建目录与软件包的实际关系是「同级」而非父子）：
  1. 环境变量 ATLAS_PACKAGE 指定的路径
  2. 脚本同目录本身是完整包（index.html + exe 同时在）
  3. 脚本父目录下的「创作工具星图」（构建目录场景）
  4. 脚本同目录下的「创作工具星图」
  5. 脚本父目录本身是完整包
找不到时明确报错，绝不静默在错误位置生成清单。
"""
import hashlib
import os
import sys
from pathlib import Path


def is_package(d):
    """完整包特征：有首页，且有 exe 或清单之一（防止构建区的 HTML 副本误判）。"""
    if not (d / "index.html").is_file():
        return False
    return (d / "创作工具星图.exe").is_file() or (d / "MANIFEST.md").is_file()


def resolve_package_dir():
    env = os.environ.get("ATLAS_PACKAGE")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent / "创作工具星图",
                      here / "创作工具星图", here.parent):
        if is_package(candidate):
            return candidate
    print("ERROR: cannot locate the package directory.", file=sys.stderr)
    print("Set ATLAS_PACKAGE=<path-to-package> before running this script.",
          file=sys.stderr)
    sys.exit(2)


BASE = resolve_package_dir()
FILES = [
    "创作工具星图.exe",
    "index.html",
    "github-creative-tools-atlas.html",
    "route-a-painter-workstation.html",
    "studio.html",
    "icon.ico",
    "icon.png",
    "使用说明.txt",
    "CHANGELOG.md",
    "迭代记录.md",
    "迭代记录-v2.md",
    "迭代记录-v3.md",
    "迭代记录-v4.md",
    "迭代记录-v5.md",
    "迭代记录-v6.md",
    "快捷方式工具/shortcut.ps1",
    "快捷方式工具/resolve-desktop.ps1",
    "快捷方式工具/rebuild-shortcut.ps1",
    "快捷方式工具/verify-package.ps1",
    "快捷方式工具/diagnose.ps1",
]


def sha256(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main():
    lines = [
        "# 创作工具星图 · 文件清单与校验基线",
        "",
        "版本：v1.6.0　生成日期：2026-11-17",
        "",
        "| 文件 | 字节 | SHA-256（前16位） |",
        "|---|---:|---|",
    ]
    for rel in FILES:
        p = BASE / rel
        if p.is_file():
            lines.append(f"| `{rel}` | {p.stat().st_size} | `{sha256(p)}…` |")
        else:
            lines.append(f"| `{rel}` | — | 缺失 |")
    lines += [
        "",
        "> `_internal/` 为运行依赖目录，勿单独移动或删除。",
        "> 校验方法：在「快捷方式工具」目录运行 `verify-package.ps1`（比对 SHA-256）。",
        "> 校验值由 `build_manifest.py` 生成；文件变更后请重新运行以刷新基线。",
    ]
    out = BASE / "MANIFEST.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成 {out}（{len(FILES)} 项）")


if __name__ == "__main__":
    main()
