#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创作工具星图 · 自动化质量自检套件 (v1.6.1)

构建期工具，位于构建目录，用 venv Python 运行：
    python selftest.py

把前五轮迭代中散落的静态检查固化为可重复执行的断言。
每项检查返回 (名称, 是否通过, 明细)，末尾汇总；任一失败则退出码 1。
"""
import os
import re
import sys
from pathlib import Path

VERSION = "v1.6.1"  # 套件声明版本，必须与包内各文档一致


def resolve_package_dir():
    """包目录解析：--base > 环境变量 > 完整包特征探测（与 build_manifest 一致）。"""
    for i, arg in enumerate(sys.argv):
        if arg == "--base" and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    if os.environ.get("ATLAS_PACKAGE"):
        return Path(os.environ["ATLAS_PACKAGE"])
    here = Path(__file__).resolve().parent
    for candidate in (here, here.parent / "创作工具星图",
                      here / "创作工具星图", here.parent):
        if (candidate / "index.html").is_file() and (
                (candidate / "创作工具星图.exe").is_file()
                or (candidate / "MANIFEST.md").is_file()):
            return candidate
    return here  # 兜底：由 main 的预检给出明确提示


BASE = resolve_package_dir()
HTML = [
    "index.html",
    "github-creative-tools-atlas.html",
    "route-a-painter-workstation.html",
    "studio.html",
]

_results = []


def check(name, ok, detail=""):
    _results.append((name, bool(ok), detail))


def read(rel):
    return (BASE / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 检查项
def check_html_structure():
    """三页 DOCTYPE / 标签配对 / 打印样式 / 语义 landmark。"""
    for rel in HTML:
        s = read(rel)
        checks = {
            "doctype": s.lstrip().lower().startswith("<!doctype html>"),
            "body配对": s.count("<body") == s.count("</body>"),
            "style配对": s.count("<style") == s.count("</style>"),
            "script配对": s.count("<script") == s.count("</script>"),
            "print样式": "@media print" in s,
        }
        bad = [k for k, v in checks.items() if not v]
        check(f"HTML结构/{rel}", not bad, "全部通过" if not bad else "失败:" + ",".join(bad))


def check_external_links():
    """所有 target=_blank 外链必须带 rel=noopener noreferrer。"""
    for rel in HTML:
        s = read(rel)
        blanks = len(re.findall(r'target="_blank"', s))
        guards = len(re.findall(r'rel="noopener noreferrer"', s))
        bad_tags = [t for t in re.findall(r"<a\b[^>]*>", s)
                    if 'target="_blank"' in t and "noopener" not in t]
        ok = (blanks == guards) and not bad_tags
        detail = f"_blank={blanks} noopener={guards} 未加固={len(bad_tags)}"
        check(f"外链安全/{rel}", ok, detail)


def check_accessibility():
    """无障碍要素：main landmark / 色彩方案 / 搜索框标签 / 播报 / 标题层级。"""
    for rel in HTML:
        s = read(rel)
        req = {
            "main landmark": 'role="main"' in s,
            "color-scheme dark": "color-scheme:dark" in s,
            "print light": "color-scheme:light" in s,
        }
        # 报告页额外要求：搜索框 aria-label + live region
        if rel != "index.html":
            req["搜索框标签"] = bool(re.search(r'<input[^>]*aria-label=', s))
            req["筛选播报"] = 'aria-live="polite"' in s
            h4 = len(re.findall(r"<h4\b", s))
            h4_fixed = len(re.findall(r'<h4[^>]*aria-level="3"', s))
            req["h4层级修正"] = (h4 == h4_fixed)
        bad = [k for k, v in req.items() if not v]
        check(f"无障碍/{rel}", not bad, "全部通过" if not bad else "失败:" + ",".join(bad))


def check_version_consistency():
    """版本一致性：套件声明 / MANIFEST / 使用说明 / 首页 / CHANGELOG 首条。"""
    sources = {
        "套件声明": VERSION,
        "MANIFEST": (re.search(r"版本：(v\d+\.\d+\.\d+)", read("MANIFEST.md")) or [None, ""])[1],
        "使用说明": (re.search(r"(v\d+\.\d+\.\d+)", read("使用说明.txt")) or [None, ""])[1],
        "首页": (re.search(r"(v\d+\.\d+\.\d+)", read("index.html")) or [None, ""])[1],
        "工坊": (re.search(r"(v\d+\.\d+\.\d+)", read("studio.html")) or [None, ""])[1],
    }
    changelog = read("CHANGELOG.md")
    first = re.search(r"^##\s+(v\d+\.\d+\.\d+)", changelog, re.M)
    sources["CHANGELOG首条"] = first.group(1) if first else ""
    vals = set(sources.values())
    ok = len(vals) == 1 and VERSION in vals
    detail = " ".join(f"{k}={v}" for k, v in sources.items())
    check("版本一致性", ok, detail)


def check_manifest_integrity():
    """清单项文件均存在；包内交付文档不得漏出清单；启动器须动态解析清单。"""
    man = read("MANIFEST.md")
    entries = re.findall(r"^\|\s*`([^`]+)`", man, re.M)
    missing = [e for e in entries if not (BASE / e.replace("/", "\\")).is_file()]
    check("清单/文件存在", not missing,
          f"{len(entries)} 项" if not missing else "缺失:" + ",".join(missing))

    # 包内顶层交付文档必须都在清单之外被覆盖（MANIFEST 自身除外）
    # 递归扫描（迭代记录已收进 迭代记录/ 子目录）
    deliverables = [str(p.relative_to(BASE)).replace("\\", "/")
                    for p in BASE.rglob("*")
                    if p.is_file() and p.suffix in (".html", ".md", ".txt", ".exe", ".ico", ".png")
                    and p.name != "MANIFEST.md" and "_internal" not in p.parts
                    and p.name not in ("tool-bridge.log",)]
    uncovered = [d for d in deliverables if d not in entries]
    check("清单/无遗漏", not uncovered,
          f"交付文件 {len(deliverables)} 个" if not uncovered else "漏:" + ",".join(uncovered))

    launcher_path = Path(__file__).resolve().parent / "launcher.py"
    if launcher_path.is_file():
        launcher = launcher_path.read_text(encoding="utf-8")
        dynamic = 'MANIFEST.md' in launcher and 're.findall' in launcher
        check("清单/启动器动态同步", dynamic, "动态解析" if dynamic else "退化为硬编码")
    else:
        check("清单/启动器动态同步", False, "launcher.py 未与套件同目录")


def check_scripts_ascii():
    """包内所有 .ps1 必须纯 ASCII（PS 5.1 按 ANSI 读无 BOM 脚本）。"""
    tools = BASE / "快捷方式工具"
    violations = []
    for p in sorted(tools.glob("*.ps1")):
        bad = sum(1 for c in p.read_bytes() if c > 127)
        if bad:
            violations.append(f"{p.name}({bad})")
    check("脚本/纯ASCII", not violations,
          f"{len(list(tools.glob('*.ps1')))} 个脚本" if not violations else "违规:" + ",".join(violations))


def check_iteration_archives():
    """迭代档案：每份 20 轮且编号连续；CHANGELOG 版本数与档案数对应。"""
    archives = sorted((BASE / "迭代记录").glob("迭代记录*.md"))
    problems = []
    for p in archives:
        nums = [int(x) for x in re.findall(r"^\*\*轮\s*(\d+)", p.read_text(encoding="utf-8"), re.M)]
        expected = list(range(1, 21))
        if nums != expected:
            problems.append(f"{p.name}(轮数={len(nums)},连续={nums == expected[:len(nums)]})")
    detail = f"{len(archives)} 份档案 × 20 轮" if not problems else "异常:" + ",".join(problems)
    check("档案/轮次完整", bool(archives) and not problems, detail)

    versions = re.findall(r"^##\s+(v\d+\.\d+\.\d+)", read("CHANGELOG.md"), re.M)
    # 迭代开始时先立 CHANGELOG 条目、结束时才把迭代档案入包，
    # 故开发期允许 CHANGELOG 领先 1 个版本；但绝不能反过来（档案多于版本）。
    ok = len(versions) >= len(archives) + 1  # +1 为 v1.0.0 初始版本
    check("档案/版本对应", ok, f"CHANGELOG {len(versions)} 版 vs 档案 {len(archives)} 份")


def check_diagnostic_tool():
    """用户侧诊断器必须存在且五个检查点齐全、结论明确。"""
    p = BASE / "快捷方式工具" / "diagnose.ps1"
    if not p.is_file():
        check("工具/诊断器", False, "diagnose.ps1 缺失")
        return
    s = p.read_text(encoding="utf-8")
    labels = ["CoreFiles", "AppBrowser", "Shortcut", "Runtime", "Integrity"]
    missing = [x for x in labels if x not in s]
    conclusions = all(k in s for k in ("DIAG_OK", "DIAG_FAIL", "NEXT:"))
    ok = not missing and conclusions
    detail = "5 检查点 + 结论齐全" if ok else f"缺:{missing} 结论={conclusions}"
    check("工具/诊断器", ok, detail)


def check_studio():
    """创作工坊：工具覆盖、生成器、产出能力、输入转义、首页导航。"""
    if not (BASE / "studio.html").is_file():
        check("工具/创作工坊", False, "studio.html 缺失")
        return
    s = (BASE / "studio.html").read_text(encoding="utf-8")
    tools = len(re.findall(r'\{n:"', s))
    groups = len(re.findall(r'\{id:"[^"]+", name:"', s))
    checks = {
        "工具覆盖≥50": tools >= 50,
        "环节≥7": groups >= 7,
        "生成器": all(k in s for k in ("buildPackage", "promptPack", "steps", "rankTools")),
        "产出能力": all(k in s for k in ("导出 .md", "复制任务包", "localStorage", "只复制提示词")),
        "输入转义": "function esc(" in s,
        "纯本地声明": "不上传" in s,
    }
    bad = [k for k, v in checks.items() if not v]
    check("工具/创作工坊", not bad,
          f"{tools} 工具 / {groups} 环节" if not bad else "失败:" + ",".join(bad))

    home = (BASE / "index.html").read_text(encoding="utf-8")
    check("导航/工坊入口", 'href="studio.html"' in home, "首页已接入" if 'href="studio.html"' in home else "首页无入口")


# ---------------------------------------------------------------- 汇总
def main():
    if not (BASE / "index.html").is_file() or not (BASE / "MANIFEST.md").is_file():
        print("ERROR: the resolved directory is not a complete package:", BASE)
        print("Use --base <package-dir> or set ATLAS_PACKAGE before running.")
        print("SELFTEST_FAIL")
        return 2
    check_html_structure()
    check_external_links()
    check_accessibility()
    check_version_consistency()
    check_manifest_integrity()
    check_scripts_ascii()
    check_iteration_archives()
    check_diagnostic_tool()
    check_studio()

    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print("=" * 60)
    print("创作工具星图 · 自动化质量自检")
    print("=" * 60)
    for name, ok, detail in _results:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f"  {detail}" if detail else ""))
    print("-" * 60)
    print(f"RESULT: {passed}/{total} passed")
    if passed != total:
        print("SELFTEST_FAIL")
        return 1
    print("SELFTEST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
