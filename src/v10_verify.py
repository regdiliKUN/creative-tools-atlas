#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第十轮 · 统一验证器（静态契约 + 桥端逻辑仿真），对应 20 轮检查点 V1..V20。

用法: python v10_verify.py [--json]
不启动网络服务、不 spawn 子进程：桥端 HTTP 行为用内存 mock 精确仿真。
"""
import importlib.util, io, json, re, sys
from pathlib import Path

# 第二十轮：路径相对脚本所在目录，不再写死 I:/（换盘 / 换机器也能跑）
BUILD = Path(__file__).resolve().parent
PKG = BUILD.parent / "创作工具星图"
REPO = BUILD.parent / "creative-tools-atlas"

R = []
def chk(tag, name, ok, detail=""):
    R.append(dict(tag=tag, name=name, ok=bool(ok), detail=str(detail)))

def read(p, enc="utf-8"):
    try: return Path(p).read_text(encoding=enc)
    except OSError: return ""

html = read(PKG / "studio.html")
# 始终从 HTML 实时抽取，避免"改了源文件却验了旧快照"的假失败
_m = re.search(r"<script>([\s\S]*?)</script>", html)
js = _m.group(1) if _m else ""
bridge_src = read(PKG / "快捷方式工具" / "tool-bridge.py")
selftest = read(BUILD / "selftest.py")
manifest = read(PKG / "MANIFEST.md")
changelog = read(PKG / "CHANGELOG.md")

# ---------- 数据提取（静态） ----------
tools = re.findall(r'\{n:"([^"]+)",\s*u:"([^"]+)",\s*s:"([^"]*)",\s*lic:"([^"]*)"', html)
tool_names = [t[0] for t in tools]
lics = {t[3] for t in tools}
risk_body = re.search(r"const RISK = \{([\s\S]*?)\n\};", html)
risk_keys = re.findall(r'"([^"]+)":', risk_body.group(1)) if risk_body else []
q_body = re.search(r"const QUALITY = \{([\s\S]*?)\n\};", html)
q_keys = re.findall(r'"([^"]+)":', q_body.group(1)) if q_body else []
stage_blocks = re.findall(r'title: "([^"]+)",[\s\S]*?tools: \[([^\]]*)\]', js)
kinds = re.findall(r'promptKind: "([^"]+)"', js)
pos_body = re.search(r"const POS = \{([\s\S]*?)\n  \};", js)
neg_body = re.search(r"const NEG = \{([\s\S]*?)\n  \};", js)
pos_keys = re.findall(r"^\s{4}(\w+):\s*`", pos_body.group(1), re.M) if pos_body else []
neg_keys = re.findall(r"^\s{4}(\w+):\s*`", neg_body.group(1), re.M) if neg_body else []

# V1 RISK 键命中
bad_risk = [k for k in risk_keys if k not in lics]
chk("V1", "RISK 键均能命中真实 lic", not bad_risk,
    "失效键=" + str(bad_risk) + " 社区许可入表=" + str("社区许可" in risk_keys))
chk("V1b", "商用包含社区许可警示（静态 RISK 引用）", "社区许可" in risk_keys,
    "RISK keys=" + str(risk_keys))

# V2 QUALITY 全覆盖
missing_q = [n for n in tool_names if n not in q_keys]
chk("V2", "QUALITY 覆盖全部工具", not missing_q, "未覆盖=" + str(missing_q))

# V3 支线工具语义
bad_tool = sorted({n for _, arr in stage_blocks for n in re.findall(r'"([^"]+)"', arr) if n not in tool_names})
whiteboard = [t for t, arr in stage_blocks
              if re.search(r"交付|精修|修模", t) and "excalidraw" in arr]
chk("V3", "支线工具名均存在于 GROUPS", not bad_tool, "孤立=" + str(bad_tool))
chk("V3b", "交付/精修阶段无白板工具串台", not whiteboard, "串台=" + str(whiteboard))

# V4 promptKind 覆盖
missing_k = sorted(set(kinds) - set(pos_keys) - set(neg_keys))
chk("V4", "每种 promptKind 均有 POS/NEG 模板", not missing_k, "缺模板=" + str(missing_k))
chk("V4b", "VRM / rebuild 有专属模板", "vrm" in pos_keys and "rebuild" in pos_keys,
    "POS keys=" + str(pos_keys))

# V5 selftest 数据契约
chk("V5", "selftest 含数据契约检查", "check_data_contracts" in selftest,
    "check_data_contracts=" + str("check_data_contracts" in selftest))

# V6 gen 启用 print
gen_block = re.search(r'\$\("gen"\)\.addEventListener\("click",\(\)=>\{[\s\S]*?\n\}\);', js)
gen_txt = gen_block.group(0) if gen_block else ""
en = re.search(r'\[([^\]]+)\]\.forEach\(id=>\$\(id\)\.disabled=false\)', gen_txt)
en_list = re.findall(r'"(\w+)"', en.group(1)) if en else []
chk("V6", "生成后启用 print 按钮", "print" in en_list, "启用集合=" + str(en_list))

# V7 自由文本转义（静态 + js 行为由 v10_verify.js 补）
esc_calls = re.findall(r"mdInline\(|promptSafe\(", js)
body_build = re.search(r"function buildPackage\(p\)\{[\s\S]*?\n\}", js)
bp = body_build.group(0) if body_build else ""
chk("V7", "任务包标题/概要转义 proj/subject", "mdInline(p.proj)" in bp and "mdInline(p.subject)" in bp,
    "title/outline escaped=" + str("mdInline(p.proj)" in bp and "mdInline(p.subject)" in bp))
chk("V7b", "提示词主体经 promptSafe 压平", "promptSafe(p.subject)" in js,
    "promptSafe=" + str("promptSafe(p.subject)" in js))

# V8 历史载入重置脏基准
load_block = js.split('querySelectorAll(".load")')[1].split('querySelectorAll(".del")')[0] if 'querySelectorAll(".load")' in js else ""
chk("V8", "历史载入后重置脏检测基准", "markClean" in load_block,
    "markClean=" + str("markClean" in load_block))
hist_en = re.search(r'\[([^\]]+)\]\.forEach\(id=>\$\(id\)\.disabled=false\)', load_block)
chk("V8b", "历史载入启用集合含 print", bool(hist_en) and "print" in hist_en.group(1),
    "载入启用=" + (hist_en.group(1) if hist_en else "无"))

# V9 esc 空值安全
esc_fn = re.search(r"function esc\(s\)\{[^\n]*", js)
chk("V9", "esc 对空值返回空串", bool(esc_fn) and ("s==null" in esc_fn.group(0) or "null" in esc_fn.group(0)),
    "esc=" + (esc_fn.group(0)[:110] if esc_fn else "缺失"))
get_hist = re.search(r"function getHist\(\)\{[\s\S]*?\n\}", js)
chk("V9b", "getHist 校验必要字段", bool(get_hist) and ("h.text" in get_hist.group(0) or "typeof h.text" in get_hist.group(0)),
    "字段校验=" + str(bool(get_hist) and ("h.text" in get_hist.group(0) or "typeof h.text" in get_hist.group(0))))

# V10 重复媒体查询
mq = re.findall(r"@media\(max-width:(\d+px)\)", html)
chk("V10", "无重复 max-width 媒体查询", len(mq) == len(set(mq)), "mq=" + str(mq))

# V11 print 覆盖
pr = re.search(r"@media print\{([\s\S]*?)\n  \}", html)
prt = pr.group(1) if pr else ""
chk("V11", "打印样式隐藏执行台", "sec-exec" in prt and ".exec" in prt,
    "含 sec-exec/.exec=" + str("sec-exec" in prt and ".exec" in prt))

# ---------- 桥端：加载模块（不启动服务） ----------
mod = None
try:
    spec = importlib.util.spec_from_file_location("tb_v10", PKG / "快捷方式工具" / "tool-bridge.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tb_v10"] = mod
    spec.loader.exec_module(mod)
except Exception as e:
    print("WARN bridge load:", e)

# V12 install 状态机全出口 —— 行为仿真（不再只数调用次数）
inst = re.search(r"^def install\(tid\):[\s\S]*?^class Handler", bridge_src, re.M)
inst_txt = inst.group(0) if inst else ""
import tempfile
_state_results = []
if mod:
    _tmpdir = tempfile.mkdtemp(prefix="v10state_")
    _orig_state_path = mod.INSTALL_STATE
    _orig_run = mod.subprocess.run
    mod.INSTALL_STATE = Path(_tmpdir) / "install-state.json"
    class _R:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def _run_case(label, tid, effect):
        try: mod.INSTALL_STATE.unlink()
        except OSError: pass
        mod.subprocess.run = effect
        try:
            mod.install(tid)
        except Exception:
            pass
        try:
            d = json.loads(mod.INSTALL_STATE.read_text(encoding="utf-8"))
            got = d.get(tid, {}).get("state", "NONE")
        except Exception:
            got = "NONE"
        _state_results.append((label, got))

    _run_case("pip成功", "trimesh", lambda *a, **k: _R(0, "ok"))
    _run_case("pip失败", "trimesh", lambda *a, **k: _R(1, "", "err"))
    def _timeout(*a, **k): raise mod.subprocess.TimeoutExpired("cmd", 1)
    _run_case("超时", "trimesh", _timeout)
    def _exc(*a, **k): raise RuntimeError("boom")
    _run_case("异常", "trimesh", _exc)
    _run_case("winget成功", "krita", lambda *a, **k: _R(0, "done"))
    _run_case("winget失败", "krita", lambda *a, **k: _R(5, "", "fail"))
    _run_case("手动", "aseprite", lambda *a, **k: _R(0))
    mod.subprocess.run = _orig_run
    mod.INSTALL_STATE = _orig_state_path

expected = {"pip成功": "succeeded", "pip失败": "failed", "超时": "failed",
            "异常": "failed", "winget成功": "succeeded", "winget失败": "failed", "手动": "manual"}
bad_states = [(l, g, expected[l]) for l, g in _state_results if g != expected[l]]
chk("V12", "install 7 个出口终态正确（行为仿真）", not bad_states,
    "结果=" + str(_state_results) + (" 不符=" + str(bad_states) if bad_states else ""))
chk("V12b", "无出口遗留 pending", all(g != "pending" for _, g in _state_results),
    "pending残留=" + str([l for l, g in _state_results if g == "pending"]))

# V13 POST 超大 body：用内存 mock 精确仿真 do_POST
class FakeRFile(io.BytesIO):
    def __init__(self, data): super().__init__(data); self.read_log = []
    def read(self, n=-1):
        out = super().read(n); self.read_log.append(len(out)); return out
class FakeWFile:
    def __init__(self): self.buf = b""
    def write(self, b): self.buf += b
class FakeHandler(mod.Handler):
    def __init__(self, path, body, headers):
        self.path = path
        self.headers = headers
        self.rfile = FakeRFile(body)
        self.wfile = FakeWFile()
        self._sent = []
        self.close_connection = False
    def send_response(self, code): self._sent.append(("status", code))
    def send_header(self, k, v): self._sent.append((k, v))
    def end_headers(self): self._sent.append(("end", None))
    # 不覆写 _json：让真实的响应头构造逻辑（含 Connection: close）真实执行

TOK = mod._BRIDGE_TOKEN
base_hdr = {"Host": "127.0.0.1:7843", "X-Bridge-Token": TOK, "Content-Length": "70000"}
h = FakeHandler("/api/ping", b"x" * 70000, base_hdr)
try: h.do_POST()
except Exception as e: print("WARN V13 sim:", e)
json_codes = [v for k, v in h._sent if k == "status"]
chk("V13", "超 64KB body 被 413 拒绝并关闭连接",
    413 in json_codes and h.close_connection,
    "codes=" + str(json_codes) + " close=" + str(h.close_connection) + " reads=" + str(h.rfile.read_log))
chk("V13c", "终止连接响应显式带 Connection: close",
    ("Connection", "close") in h._sent,
    "headers含=" + str(("Connection", "close") in h._sent))
# 正常小 body 必须被完整读取
h2 = FakeHandler("/api/ping", b"{}", {"Host": "127.0.0.1:7843", "X-Bridge-Token": TOK, "Content-Length": "2"})
try: h2.do_POST()
except Exception as e: print("WARN V13b sim:", e)
chk("V13b", "正常 body 被完整消费", h2.rfile.read_log == [2],
    "reads=" + str(h2.rfile.read_log) + " close=" + str(h2.close_connection))

# V14 _redact 正斜杠
if mod:
    cases = [r"C:\Users\john\AppData\krita.exe", "C:/Users/john/AppData/krita.exe",
             r"C:\Program Files\Krita (x64)\krita.exe", "C:/Program Files/Krita (x64)/krita.exe"]
    leaks = [c for c in cases if "john" in mod._redact("LAUNCH " + c) or "Program Files" in mod._redact("LAUNCH " + c)]
    chk("V14", "_redact 兼容正/反斜杠路径", not leaks, "泄漏=" + str(leaks))
else:
    chk("V14", "_redact 兼容正/反斜杠路径", False, "模块未加载")

# V15 launch 消息脱敏一致
chk("V15", "launch 返回消息经脱敏（仅文件名）", "_redact" in inst_txt or "Path(exe).name" in bridge_src,
    "含脱敏=" + str("_redact" in bridge_src))
launch_src = re.search(r"^def launch\(tid\):[\s\S]*?^def install", bridge_src, re.M)
chk("V15b", "launch 不回传绝对路径", bool(launch_src) and ":: \" + exe" not in launch_src.group(0),
    "仍拼接 exe=" + str(bool(launch_src) and ":: \" + exe" in launch_src.group(0)))

# V16 status 缓存 + 前端超时
chk("V16", "桥端 status 有 TTL 缓存", "STATUS_CACHE" in bridge_src or "_status_cache" in bridge_src,
    "缓存标识=" + str("STATUS_CACHE" in bridge_src or "_status_cache" in bridge_src))
ls = re.search(r"async function loadToolStatus\([\s\S]*?\n\}", js)
ls_txt = ls.group(0) if ls else ""
ft = re.search(r"timeoutFetch\([^;]*?,\{\},(\d+)\)", ls_txt)
chk("V16b", "前端 status 超时提升到 >=10s", bool(ft) and int(ft.group(1)) >= 10000,
    "超时=" + (ft.group(1) if ft else "?"))
chk("V16c", "安装后用 fresh=1 强制重算", "loadToolStatus(true)" in js,
    "fresh调用=" + str("loadToolStatus(true)" in js))

# V17 selftest 契约断言扩充
extra = [k for k in ("check_data_contracts", "check_interaction_contracts", "check_bridge_contracts") if k in selftest]
chk("V17", "selftest 含 3 组新契约断言", len(extra) == 3, "已含=" + str(extra))
chk("V17b", "selftest 版本为 v2.1.0", 'VERSION = "v2.1.0"' in selftest, "")

# V18 版本全量一致
vers = {
    "studio": (re.search(r"Production Studio · (v[\d.]+)", html) or [None, ""])[1],
    "MANIFEST": (re.search(r"版本：(v[\d.]+)", manifest) or [None, ""])[1],
    "CHANGELOG首条": (re.search(r"^##\s+(v[\d.]+)", changelog, re.M) or [None, ""])[1],
    "使用说明": (re.search(r"(v[\d.]+)", read(PKG / "使用说明.txt", "utf-8-sig")) or [None, ""])[1],
    "index": (re.search(r"(v[\d.]+)", read(PKG / "index.html")) or [None, ""])[1],
    "bridge": "v" + (re.search(r'VERSION = "([\d.]+)"', bridge_src) or [None, ""])[1],
    "selftest": (re.search(r'VERSION = "(v[\d.]+)"', selftest) or [None, ""])[1],
    "repo README": "v" + (re.search(r"v([\d.]+)\s+起带", read(REPO / "README.md")) or [None, ""])[1],
}
chk("V18", "8 处版本统一为 v2.1.0", set(vers.values()) == {"v2.1.0"}, json.dumps(vers, ensure_ascii=False))
chk("V18b", "CHANGELOG 有 v2.1.0 条目", vers["CHANGELOG首条"] == "v2.1.0", "")

# V19 MANIFEST 双向 + SHA
entries = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|\s*`([0-9a-f]{16})", manifest, re.M)
import hashlib
sha_bad, size_bad, missing = [], [], []
for rel, size, sha in entries:
    p = PKG / rel
    if not p.is_file(): missing.append(rel); continue
    b = p.read_bytes()
    if len(b) != int(size): size_bad.append(rel + ":%d!=%s" % (len(b), size))
    if hashlib.sha256(b).hexdigest()[:16] != sha: sha_bad.append(rel)
deliverables = [str(p.relative_to(PKG)).replace("\\", "/") for p in PKG.rglob("*")
                if p.is_file() and p.name != "MANIFEST.md" and "_internal" not in p.parts
                and p.name not in ("tool-bridge.log", "tool-bridge.log.1", "install-state.json","jobs.json","start-all.log", ".krita_token","krita_session.json","krita_session.ack","krita_session.json.tmp", "translate_cache.json", "translate_cache.json.tmp")
                and p.relative_to(PKG).parts[0] != "outputs"   # 第十二轮：用户产物不是交付物
                and "__pycache__" not in p.parts]
covered = {e[0] for e in entries}
uncovered = [d for d in deliverables if d not in covered]
chk("V19", "MANIFEST 文件存在且 SHA/字节匹配",
    not missing and not size_bad and not sha_bad,
    "缺文件=" + str(missing) + " 字节不符=" + str(size_bad) + " SHA不符=" + str(sha_bad))
chk("V19b", "MANIFEST 覆盖全部交付文件", not uncovered,
    "漏=" + str(uncovered) + " 清单项=" + str(len(entries)))

# V20 迭代记录
v10 = read(PKG / "迭代记录" / "迭代记录-v10.md", "utf-8-sig")
nums = [int(x) for x in re.findall(r"^\*\*轮\s*(\d+)", v10, re.M)]
chk("V20", "迭代记录 v10 存在且 20 轮连续", nums == list(range(1, 21)),
    "轮次=" + str(nums))
chk("V20b", "v10 记录含整体提升与诚实排除说明",
    "整体提升" in v10 and ("排除" in v10 or "未复现" in v10), "")

# ---------- 输出 ----------
sel = None
for a in sys.argv:
    if a.startswith("--tags="):
        sel = set(a.split("=", 1)[1].split(","))
shown = [r for r in R if sel is None or r["tag"] in sel]
if "--json" in sys.argv:
    print(json.dumps(shown, ensure_ascii=False))
else:
    print("=" * 76)
    print("第十轮 · 统一验证器" + (" [轮次过滤 " + ",".join(sorted(sel)) + "]" if sel else " V1..V20"))
    print("=" * 76)
    for r in shown:
        print("[%s] %-4s %-38s %s" % ("PASS" if r["ok"] else "FAIL", r["tag"], r["name"], r["detail"]))
    bad = [r for r in shown if not r["ok"]]
    print("-" * 76)
    print("RESULT: %d/%d passed  (FAIL=%d)" % (len(shown) - len(bad), len(shown), len(bad)))
    sys.exit(0 if not bad else 1)
