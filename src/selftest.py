#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创作工具星图 · 自动化质量自检套件 (v2.1.0)

构建期工具，位于构建目录，用 venv Python 运行：
    python selftest.py

把前五轮迭代中散落的静态检查固化为可重复执行的断言。
每项检查返回 (名称, 是否通过, 明细)，末尾汇总；任一失败则退出码 1。
"""
import os
import re
import sys
from pathlib import Path

VERSION = "v2.1.0"  # 套件声明版本，必须与包内各文档一致


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


_READ_MISSING = []   # 轮14：记录 read() 遇到的缺失文件
def read(rel):
    try:
        return (BASE / rel).read_text(encoding="utf-8")
    except OSError:
        if rel not in _READ_MISSING: _READ_MISSING.append(rel)
        return ""


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
    # 轮13：README 版本检查——路径不可达时显式 FAIL，不静默跳过
    repo_readme = Path(__file__).resolve().parent.parent / "creative-tools-atlas" / "README.md"
    pkg_readme = BASE.parent / "creative-tools-atlas" / "README.md"
    readme = repo_readme if repo_readme.is_file() else pkg_readme
    if readme.is_file():
        rm = re.search(r"v(\d+\.\d+\.\d+)\s+起带", readme.read_text(encoding="utf-8"))
        sources["README"] = ("v" + rm.group(1)) if rm else ""
        check("版本/README", rm is not None, "README版本字段存在" if rm else "README无版本字段")
    else:
        check("版本/README", False, "README 路径不可达（仓库源码不在预期位置）")
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
    missing = [e for e in entries if not (BASE / e).is_file()]   # 第二十轮：pathlib 自己处理分隔符，Linux / Windows 都能跑
    check("清单/文件存在", not missing,
          f"{len(entries)} 项" if not missing else "缺失:" + ",".join(missing))

    # 包内顶层交付文档必须都在清单之外被覆盖（MANIFEST 自身除外）
    # 递归扫描（迭代记录已收进 迭代记录/ 子目录）
    # 全量扫描交付物（含 .ps1/.py），只有 _internal 与运行日志排除
    deliverables = [str(p.relative_to(BASE)).replace("\\", "/")
                    for p in BASE.rglob("*")
                    if p.is_file() and p.name != "MANIFEST.md" and "_internal" not in p.parts
                    and p.name not in ("tool-bridge.log","tool-bridge.log.1","install-state.json","jobs.json","start-all.log", ".krita_token","krita_session.json","krita_session.ack","krita_session.json.tmp", "translate_cache.json", "translate_cache.json.tmp") and "__pycache__" not in p.parts
                    and p.relative_to(BASE).parts[0] != "outputs"]   # 第十二轮：用户产物不是交付物
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
    """迭代档案：每份 20 轮（或显式声明的专项轮数）且编号连续；CHANGELOG 版本数与档案数对应。"""
    archives = sorted((BASE / "迭代记录").glob("迭代记录*.md"))
    problems = []
    for p in archives:
        text = p.read_text(encoding="utf-8")
        nums = [int(x) for x in re.findall(r"^\*\*轮\s*(\d+)", text, re.M)]
        # 第十二轮：常规档案固定 20 轮；聚焦攻坚的专项档案须在文件内显式声明
        # "<!-- 专项轮次：N -->"，且实际轮数必须恰为 N、编号从 1 连续——不允许凑数，也不允许少写。
        decl = re.search(r"<!--\s*专项轮次：(\d+)\s*-->", text)
        expected = list(range(1, (int(decl.group(1)) if decl else 20) + 1))
        if nums != expected:
            problems.append(f"{p.name}(轮数={len(nums)},连续={nums == expected[:len(nums)]})")
    detail = f"{len(archives)} 份档案（常规 20 轮 / 专项按声明）编号连续" if not problems else "异常:" + ",".join(problems)
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


def check_ps_braces():
    """轮16：PS 脚本大括号平衡的静态近似检查（抓轮14 那种孤立 } 语法错）。"""
    tools = BASE / "快捷方式工具"
    scripts = sorted(tools.glob("*.ps1")) if tools.is_dir() else []
    if not scripts:
        check("脚本/PS语法静态", False, "未找到任何 .ps1（目录缺失？）")
        return
    bad = []
    for p in scripts:
        depth = 0
        orphan = False
        for ln in p.read_text(encoding="utf-8").splitlines():
            code = ln.split("#", 1)[0]
            opens = code.count("{"); closes = code.count("}")
            if closes > opens and depth == 0:
                orphan = True
            depth += opens - closes
            if depth < 0: orphan = True
        if depth != 0 or orphan:
            bad.append(p.name + "(depth=%d%s)" % (depth, ",orphan" if orphan else ""))
    check("脚本/PS语法静态", not bad,
          "%d 脚本括号平衡" % len(scripts) if not bad else "异常:" + ",".join(bad))


def check_studio():
    """创作工坊：工具覆盖、生成器、产出能力、输入转义、首页导航。"""
    if not (BASE / "studio.html").is_file():
        check("工具/创作工坊", False, "studio.html 缺失")
        return
    s = (BASE / "studio.html").read_text(encoding="utf-8")
    tools = len(re.findall(r'\{n:"', s))
    groups = len(re.findall(r'\{id:"[^"]+", name:"', s))
    workflows = len(re.findall(r'\n    id: "', s))
    stages = len(re.findall(r'\n        title: "', s))
    checks = {
        "工作流≥9": workflows >= 9,
        "支线阶段≥30": stages >= 30,
        "工作流选择器": 'id="wfGrid"' in s and 'id="wfBranches"' in s,
        "上手引导": 'guide' in s and 'branch-cta' in s,
        "效果优先保留": 'QUALITY' in s and '效果优先' in s,
        "工具覆盖≥50": tools >= 50,
        "环节≥7": groups >= 7,
        "生成器": all(k in s for k in ("buildPackage", "promptPack", "steps", "rankTools")),
        "产出能力": all(k in s for k in ("导出 .md", "复制任务包", "localStorage", "只复制提示词")),
        "输入转义": "function esc(" in s,
        "纯本地声明": "不上传" in s,
    }
    bad = [k for k, v in checks.items() if not v]
    check("工具/创作工坊", not bad,
          f"{workflows} 工作流 / {stages} 阶段 / {tools} 工具" if not bad else "失败:" + ",".join(bad))

    home = (BASE / "index.html").read_text(encoding="utf-8")
    check("导航/工坊入口", 'href="studio.html"' in home, "首页已接入" if 'href="studio.html"' in home else "首页无入口")


def check_data_contracts():
    """轮5：把第十轮发现的四类"数据表互相矛盾"固化为可执行契约，防止改数据时再次漂移。

    WORKFLOWS / GROUPS / QUALITY / RISK / POS / NEG / T2B / tool-bridge.TOOLS
    之间必须互相引用得上、语义不串台。
    """
    s = read("studio.html")
    if not s:
        check("数据/契约", False, "studio.html 不可读")
        return
    # 工具条目与真实 lic / tier
    entries = re.findall(r'\{n:"([^"]+)",\s*u:"([^"]+)",\s*s:"([^"]*)",\s*lic:"([^"]*)"', s)
    names = [e[0] for e in entries]
    lics = {e[3] for e in entries}
    problems = []

    # 契约 1：RISK 的每个键都必须能命中一个真实 lic（原 "community" 永不命中）
    rb = re.search(r"const RISK = \{([\s\S]*?)\n\};", s)
    risk_keys = re.findall(r'"([^"]+)":', rb.group(1)) if rb else []
    dead = [k for k in risk_keys if k not in lics]
    if dead: problems.append("RISK失效键:" + ",".join(dead))
    if "社区许可" not in risk_keys: problems.append("RISK缺社区许可")

    # 契约 2：QUALITY 必须覆盖全部工具，且不得有幽灵键
    qb = re.search(r"const QUALITY = \{([\s\S]*?)\n\};", s)
    q_keys = re.findall(r'"([^"]+)":', qb.group(1)) if qb else []
    miss_q = [n for n in names if n not in q_keys]
    ghost_q = [k for k in q_keys if k not in names]
    if miss_q: problems.append("QUALITY缺:" + ",".join(miss_q))
    if ghost_q: problems.append("QUALITY幽灵:" + ",".join(ghost_q))

    # 契约 3：支线 stages 引用的工具名必须真实；交付/精修阶段不得出现白板工具
    stages = re.findall(r'title: "([^"]+)",[\s\S]*?tools: \[([^\]]*)\]', s)
    orphan = sorted({n for _, arr in stages for n in re.findall(r'"([^"]+)"', arr) if n not in names})
    if orphan: problems.append("支线孤立工具:" + ",".join(orphan))
    sem = [t for t, arr in stages if re.search(r"交付|精修|修模", t) and "excalidraw" in arr]
    if sem: problems.append("交付阶段白板串台:" + ",".join(sem))

    # 契约 4：promptKind ↔ POS/NEG 双向覆盖，且 9 条工作流应有 9 套模板（不复用）
    kinds = set(re.findall(r'promptKind: "([^"]+)"', s))
    pb = re.search(r"const POS = \{([\s\S]*?)\n  \};", s)
    nb = re.search(r"const NEG = \{([\s\S]*?)\n  \};", s)
    pos_keys = set(re.findall(r"^\s{4}(\w+):\s*`", pb.group(1), re.M)) if pb else set()
    neg_keys = set(re.findall(r"^\s{4}(\w+):\s*`", nb.group(1), re.M)) if nb else set()
    if kinds - pos_keys: problems.append("POS缺:" + ",".join(sorted(kinds - pos_keys)))
    if kinds - neg_keys: problems.append("NEG缺:" + ",".join(sorted(kinds - neg_keys)))
    if len(kinds) < 9: problems.append("提示词模板复用(%d<9)" % len(kinds))

    # 契约 5：T2B ↔ 桥端 TOOLS 双向映射（前端点了按钮，桥里必须有对应实现）
    tb = re.search(r"const T2B=\{([\s\S]*?)\n\};", s)
    t2b = re.findall(r"'([^']+)':'([^']+)'", tb.group(1)) if tb else []
    bridge_src = read("快捷方式工具/tool-bridge.py")
    bridge_ids = set(re.findall(r'^\s{4}"([a-z0-9]+)":\s*\{"name":', bridge_src, re.M))
    dangling = [i for _, i in t2b if i not in bridge_ids]
    unmapped = [i for i in bridge_ids if i not in {v for _, v in t2b}]
    bad_front = [n for n, _ in t2b if n not in names]
    if dangling: problems.append("T2B指向不存在的桥id:" + ",".join(dangling))
    if unmapped: problems.append("桥id未被前端映射:" + ",".join(sorted(unmapped)))
    if bad_front: problems.append("T2B前端名不在GROUPS:" + ",".join(bad_front))

    check("数据/契约", not problems,
          ("%d 工具 / %d RISK键 / %d QUALITY / %d 模板 / %d 桥映射 全部自洽"
           % (len(names), len(risk_keys), len(q_keys), len(pos_keys), len(t2b)))
          if not problems else "失败:" + "; ".join(problems))


def check_interaction_contracts():
    """轮17：固化第十轮的交互/转义/打印契约，防止功能静默退化。"""
    s = read("studio.html")
    if not s:
        check("交互/契约", False, "studio.html 不可读")
        return
    issues = []
    # 1) 生成与载入的按钮启用集合必须都含 print（v1.9 生成后打印不可用）
    gb = re.search(r'\$\("gen"\)\.addEventListener\("click",\(\)=>\{[\s\S]*?\n\}\);', s)
    ge = re.search(r'\[([^\]]+)\]\.forEach\(id=>\$\(id\)\.disabled=false\)', gb.group(0)) if gb else None
    if not ge or "print" not in ge.group(1): issues.append("生成未启用print")
    lb = s.split('querySelectorAll(".load")')
    if len(lb) > 1:
        load = lb[1].split('querySelectorAll(".del")')[0]
        if "markClean" not in load: issues.append("历史载入未重置脏基准")
        if "print" not in load: issues.append("历史载入未启用print")
    else:
        issues.append("找不到历史载入逻辑")
    # 2) 三个自由文本输入都要转义（v1.9 只覆盖了 extra）
    bp = re.search(r"function buildPackage\(p\)\{[\s\S]*?\n\}", s)
    for fn, where in (("mdInline(p.proj)", bp), ("mdInline(p.subject)", bp)):
        if not where or fn not in where.group(0): issues.append("未转义:" + fn)
    if "promptSafe(p.subject)" not in s: issues.append("提示词主体未清洗")
    # 3) 空值与损坏存储边界
    if "s==null" not in re.search(r"function esc\([^\n]*", s).group(0): issues.append("esc空值未归一")
    if "typeof h.text" not in s: issues.append("getHist未校验字段")
    # 4) CSS：重复媒体查询、打印声明兑现
    mq = re.findall(r"@media\(max-width:(\d+px)\)", s)
    if len(mq) != len(set(mq)): issues.append("重复媒体查询")
    pr = re.search(r"@media print\{([\s\S]*?)\n  \}", s)
    if not pr or "sec-exec" not in pr.group(1) or ".exec" not in pr.group(1):
        issues.append("打印未隐藏执行台")
    # 5) 提示词模板数与工作流数一致（不再复用）
    kinds = set(re.findall(r'promptKind: "([^"]+)"', s))
    pb = re.search(r"const POS = \{([\s\S]*?)\n  \};", s)
    pos = set(re.findall(r"^\s{4}(\w+):\s*`", pb.group(1), re.M)) if pb else set()
    if len(kinds) < 9 or kinds - pos: issues.append("提示词模板未全覆盖")
    check("交互/契约", not issues,
          "生成/载入/转义/边界/打印/模板 六类契约齐备" if not issues else "失败:" + ",".join(issues))


def check_bridge_contracts():
    """轮17：固化第十轮的桥端协议契约（超大 body / 状态机 / 脱敏 / 缓存）。"""
    p = BASE / "快捷方式工具" / "tool-bridge.py"
    if not p.is_file():
        check("桥端/契约", False, "tool-bridge.py 缺失")
        return
    s = p.read_text(encoding="utf-8")
    issues = []
    # 1) 超大 body：必须拒绝且关闭连接（否则 keep-alive 串包）
    if '413' not in s or "self.close_connection = True" not in s:
        issues.append("超大body未拒绝/未关连接")
    if "min(n, 65536)" in s: issues.append("仍存在残留body读法")
    # 2) install 状态机：finally 统一落终态，不留 pending
    inst = re.search(r"^def install\(tid\):[\s\S]*?^class Handler", s, re.M)
    it = inst.group(0) if inst else ""
    if "finally:" not in it: issues.append("install无finally统一落盘")
    if not re.search(r'final_state\s*=\s*\("failed"', it): issues.append("失败终态缺失")
    # 3) 脱敏兼容正斜杠 + launch 只回文件名
    if "[\\\\/]" not in s: issues.append("_redact不支持正斜杠")
    if "Path(exe).name" not in s: issues.append("launch回显仍含绝对路径")
    # 4) status 缓存 + 失效 + 前端超时
    if "STATUS_TTL" not in s or "invalidate_status_cache" not in s:
        issues.append("status缓存/失效缺失")
    if "10000" not in read("studio.html"): issues.append("前端status超时未提升")
    # 5) Python 语法可编译
    try:
        compile(s, str(p), "exec")
    except SyntaxError as e:
        issues.append("语法错误:" + str(e))
    check("桥端/契约", not issues,
          "body/状态机/脱敏/回显/缓存 五类契约齐备" if not issues else "失败:" + ",".join(issues))


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
    check_data_contracts()          # 轮5
    check_interaction_contracts()   # 轮17
    check_bridge_contracts()        # 轮17
    check_ps_braces()
    # 轮14：被读文件缺失 -> 结构化 FAIL，而非 traceback
    check("读取/文件齐全", not _READ_MISSING,
          "全部可读" if not _READ_MISSING else "缺失:" + ",".join(_READ_MISSING))

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
