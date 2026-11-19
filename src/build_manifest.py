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
import re
from datetime import date
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
    "迭代记录/迭代记录.md",
    "迭代记录/迭代记录-v2.md",
    "迭代记录/迭代记录-v3.md",
    "迭代记录/迭代记录-v4.md",
    "迭代记录/迭代记录-v5.md",
    "迭代记录/迭代记录-v6.md",
    "迭代记录/迭代记录-v7.md",
    "迭代记录/迭代记录-v8.md",
    "迭代记录/迭代记录-v9.md",
    "迭代记录/迭代记录-v10.md",
    "迭代记录/迭代记录-v11.md",
    "迭代记录/迭代记录-v12.md",
    "快捷方式工具/shortcut.ps1",
    "快捷方式工具/resolve-desktop.ps1",
    "快捷方式工具/rebuild-shortcut.ps1",
    "快捷方式工具/verify-package.ps1",
    "快捷方式工具/diagnose.ps1",
    "快捷方式工具/tool-bridge.py",
    "快捷方式工具/start-all.bat",
    "快捷方式工具/check-bridge-fresh.ps1",
    "快捷方式工具/painter/stroke_planner.py",
    "快捷方式工具/painter/install_krita_plugin.py",
    "快捷方式工具/painter/pykrita/atlas_painter.desktop",
    "快捷方式工具/painter/pykrita/atlas_painter/__init__.py",
    "快捷方式工具/painter/pykrita/atlas_painter/atlas_painter.py",
    "快捷方式工具/painter/pykrita/atlas_painter/atlas_studio.py",
    "快捷方式工具/translate_zh_en.py",
    "快捷方式工具/download_model.py",
    "快捷方式工具/automation.py",
    "快捷方式工具/clean_image.py",
    "快捷方式工具/workflows/trellis2_image_to_3d.json",
    "快捷方式工具/install-comfyui-v312.ps1",
    "快捷方式工具/本机安装配置记录.md",
    "快捷方式工具/start-tool-bridge.ps1",
    "快捷方式工具/install-comfyui.ps1",
    "快捷方式工具/安装AI引擎说明.md",
]


def sha256(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def current_version():
    """轮19：版本号单一事实来源——从 CHANGELOG 首条解析，不再在脚本里硬编码。
    解析失败即报错退出，避免静默沿用旧版本导致清单与包不一致。"""
    cl = BASE / "CHANGELOG.md"
    if not cl.is_file():
        print("ERROR: CHANGELOG.md missing; cannot determine version.", file=sys.stderr)
        sys.exit(1)
    m = re.search(r"^##\s+(v\d+\.\d+\.\d+)", cl.read_text(encoding="utf-8"), re.M)
    if not m:
        print("ERROR: no version heading in CHANGELOG.md; refuse to guess.", file=sys.stderr)
        sys.exit(1)
    return m.group(1)


def main():
    lines = [
        "# 创作工具星图 · 文件清单与校验基线",
        "",
        "版本：" + current_version() + "　生成日期：" + date.today().isoformat(),
        "",
        "| 文件 | 字节 | SHA-256（前16位） |",
        "|---|---:|---|",
    ]
    missing = []
    for rel in FILES:
        p = BASE / rel
        if p.is_file():
            lines.append(f"| `{rel}` | {p.stat().st_size} | `{sha256(p)}…` |")
        else:
            missing.append(rel)
    if missing:
        print("ERROR: missing files, refuse to generate manifest:", file=sys.stderr)
        for m in missing:
            print("  " + m, file=sys.stderr)
        sys.exit(1)
    # 轮15：反向扫描——发现包内清单之外的交付物也拒绝生成（与缺失检查对称）
    declared=set(FILES)
    extra=[]
    for f in BASE.rglob("*"):
        if not f.is_file(): continue
        rel=str(f.relative_to(BASE)).replace("\\","/")
        if rel=="MANIFEST.md" or "_internal" in f.parts or "__pycache__" in f.parts: continue
        # 轮11：jobs.json 是自动化引擎的运行时状态（作业历史/进度），不是交付物
        if f.name in ("tool-bridge.log","tool-bridge.log.1","install-state.json","jobs.json","start-all.log", ".krita_token","krita_session.json","krita_session.ack","krita_session.json.tmp", "translate_cache.json", "translate_cache.json.tmp"): continue
        # 第十二轮：outputs/ 是用户作业产物（运行时生成），不是交付物
        if rel.startswith("outputs/"): continue
        if rel not in declared: extra.append(rel)
    if extra:
        print("ERROR: files in package but NOT declared in FILES (add them or exclude):", file=sys.stderr)
        for e in sorted(extra): print("  " + e, file=sys.stderr)
        sys.exit(1)
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
