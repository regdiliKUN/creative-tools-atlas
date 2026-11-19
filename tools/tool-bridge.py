#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创作工具星图 · 本地工具桥 (tool-bridge)

只监听 127.0.0.1 的迷你 HTTP 服务，让 file:// 工坊页能安全调用本机程序。
零第三方依赖，仅用标准库。

启动: python tool-bridge.py
端点:
  GET  /api/status              所有工具的安装状态
  GET  /api/ping                健康检查
  POST /api/launch?id=<id>      启动已安装工具
  POST /api/install?id=<id>     一键安装（winget / pip）
  GET  /api/log                 最近操作日志
"""
import atexit
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# 自动化执行引擎（失败不影响主桥启动——保持向后兼容）
try:
    import automation as _auto
except Exception as _ae:
    _auto = None
    print("WARN automation engine unavailable: " + str(_ae)[:120], flush=True)

PORT = 7843
SERVICE = "atlas-tool-bridge"
VERSION = "2.1.0"
_BRIDGE_TOKEN = secrets.token_urlsafe(24)   # 轮1：challenge token，仅内存，进程重启即换
# 第十八轮：Krita「Atlas 工坊」面板专用令牌——启动时写进本目录 .krita_token，面板读它调用工具桥。
# 只放行"回传继续 / 保存提示词 / 翻译提示词"三个接口，拿不到网页令牌能做的启动、安装等操作。
_PLUGIN_TOKEN = secrets.token_urlsafe(24)
PLUGIN_PATHS = ("/api/job/resume", "/api/job/spec", "/api/translate")   # 第十九轮：面板精修前翻译提示词
UPLOAD_PATHS = ("/api/upload", "/api/job/input")                          # 第二十轮：上传输入图片 / 3D 模型
_LOG_LOCK = threading.Lock()          # 轮20：多线程日志串行化
_INSTALL_LOCK = threading.Lock()      # 轮20：安装去重（同一时刻只允许一个）
_INSTALLING = set()
# 安全白名单：只允许本机来源，防止任意网页/DNS rebinding 跨站触发 launch/install
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HERE = Path(__file__).resolve().parent
# 第十二轮：代码指纹——启动时对 tool-bridge.py + automation.py 取 SHA-256 前 12 位。
# start-all.bat 用同样算法比对磁盘文件，不一致说明跑的是旧代码，自动重启桥。
import hashlib as _hl
CODE_STAMP = _hl.sha256(b"".join((HERE / n).read_bytes() for n in ("tool-bridge.py", "automation.py")
                                 if (HERE / n).is_file())).hexdigest()[:12]
LOG = HERE / "tool-bridge.log"
INSTALL_STATE = HERE / "install-state.json"   # 轮9：安装状态记录

# 工具定义：id -> {name, kind, winget, pip, exe(glob 候选), args, note}
# kind: desktop=有 exe 可启动 / cli=pip 包 / suite=依附宿主(ComfyUI/Blender) / web=云端或源码
TOOLS = {
    "krita":        {"name":"Krita","kind":"desktop","winget":"KDE.Krita","exe":[r"C:\Program Files\Krita (x64)\bin\krita.exe",r"C:\Program Files\Krita\bin\krita.exe",r"C:\Program Files\Krita (x64)\krita.exe",r"C:\Program Files\Krita\krita.exe"],"reg":["Krita"]},
    "blender":      {"name":"Blender","kind":"desktop","winget":"BlenderFoundation.Blender","exe":[r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"],"reg":["Blender"]},
    "freecad":      {"name":"FreeCAD","kind":"desktop","winget":"FreeCAD.FreeCAD","exe":[r"C:\Program Files\FreeCAD*\bin\FreeCAD.exe"],"reg":["FreeCAD"]},
    "openscad":     {"name":"OpenSCAD","kind":"desktop","winget":"OpenSCAD.OpenSCAD","exe":[r"C:\Program Files\OpenSCAD\openscad.exe"],"reg":["OpenSCAD"]},
    "meshlab":      {"name":"MeshLab","kind":"desktop","winget":"CNRISTI.MeshLab","exe":[r"C:\Program Files\VCG\MeshLab\meshlab.exe"],"reg":["MeshLab"]},
    "opentoonz":    {"name":"OpenToonz","kind":"desktop","winget":"DWANGO.OpenToonz","exe":[r"C:\Program Files\OpenToonz*\opentoonz.exe"],"reg":["OpenToonz"]},
    "cura":         {"name":"Cura","kind":"desktop","winget":"Ultimaker.Cura","exe":[r"C:\Program Files\UltiMaker Cura *\UltiMaker-Cura.exe",r"C:\Program Files\UltiMaker Cura *\Cura.exe"],"reg":["Cura", "UltiMaker"]},
    "prusaslicer":  {"name":"PrusaSlicer","kind":"desktop","winget":"Prusa3D.PrusaSlicer","exe":[r"C:\Program Files\Prusa3D\PrusaSlicer\PrusaSlicer.exe"],"reg":["PrusaSlicer", "Prusa"]},
    "orcaslicer":   {"name":"OrcaSlicer","kind":"desktop","winget":"SoftFever.OrcaSlicer","exe":[r"C:\Program Files\OrcaSlicer\OrcaSlicer.exe"],"reg":["OrcaSlicer"]},
    "uvtools":      {"name":"UVtools","kind":"desktop","winget":"PTRTECH.UVtools","exe":[r"C:\Program Files\UVtools\UVtools.exe"],"reg":["UVtools"]},
    "aseprite":     {"name":"Aseprite","kind":"desktop","exe":[r"C:\Program Files\Aseprite\Aseprite.exe"],"reg":["Aseprite"]},
    # 第十二轮：优先认本机便携版（I:\workbuddy\AI-Engine\portable），否则"需配置"会误报
    "comfyui":      {"name":"ComfyUI","kind":"suite","exe":[r"I:\workbuddy\AI-Engine\portable\ComfyUI_windows_portable\run_nvidia_gpu.bat",r"C:\ComfyUI\run_nvidia_gpu.bat",r"D:\ComfyUI\run_nvidia_gpu.bat"]},
    "trimesh":      {"name":"trimesh","kind":"cli","pip":"trimesh"},
    "cadquery":     {"name":"CadQuery","kind":"cli","pip":"cadquery"},
    "assimp":       {"name":"Assimp","kind":"cli","pip":"pyassimp"},
    "smplx":        {"name":"smplx","kind":"cli","pip":"smplx"},
    "excalidraw":   {"name":"excalidraw","kind":"web","url":"https://excalidraw.com"},
    "charstudio":   {"name":"CharacterStudio","kind":"web","url":"https://m3-org.github.io/CharacterStudio/"},
    "threestudio":  {"name":"threestudio","kind":"web","url":"https://github.com/threestudio-project/threestudio"},
}


def _redact(msg):
    """日志脱敏——去掉用户名与完整路径，仅保留文件名，降低本地信息泄露。

    轮13：v1.9 只匹配反斜杠路径；桥端 glob / Path 字符串化会产出正斜杠路径，
    实测 "C:/Users/john/AppData/krita.exe" 完整泄露用户名与目录。统一用 [\\\\/] 兼容两种分隔符。
    """
    # 用户目录（正反斜杠皆可）：C:/Users/<name>/... -> <userdir>/...（保留尾分隔符，避免与文件名粘连）
    msg = re.sub(r"[A-Za-z]:[\\/]Users[\\/][^\\\s/]+[\\/]?", "<userdir>/", msg, flags=re.I)
    # 任意带盘符或 <userdir> 前缀的绝对路径 -> 仅保留文件名（路径可含空格）
    msg = re.sub(r"(?:<userdir>|[A-Za-z]:)[\\/][^\n]*?[\\/]([^\\\n/]+\.exe)", r"\1", msg, flags=re.I)
    # 兜底：纯 Unix 绝对路径里的 exe（如 /opt/tools/krita.exe）
    msg = re.sub(r"(?<![\w>])/[^\n\s]*?/([^/\n\s]+\.exe)", r"\1", msg)
    return msg


def w(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), _redact(str(msg)))
    print(line, flush=True)
    try:
        with _LOG_LOCK:
            # 轮19：简单轮转——超过 1MB 就改名 .1（最多保留一份旧日志）
            try:
                if LOG.stat().st_size > 1024 * 1024:
                    bak = LOG.with_suffix(".log.1")
                    if bak.exists(): bak.unlink()
                    LOG.rename(bak)
            except OSError:
                pass
            with LOG.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass


def registry_exe(names):
    """从 Windows 卸载项动态找 exe：匹配显示名，读 DisplayIcon/InstallLocation。"""
    if os.name != "nt":
        return None
    try:
        import winreg
        # 轮8：HKLM 优先——HKCU 卸载项当前用户可写，可被注册假条目劫持执行
        roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")]
        hkcu_roots = [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        def safe_candidate(p):
            """轮8：只接受规范化的绝对路径，拒绝 .. / 相对路径 / 非 exe。"""
            try:
                q = Path(p)
                if not q.is_absolute(): return None
                q = q.resolve()
                if ".." in p.replace("\\", "/").split("/"): return None
                if q.suffix.lower() != ".exe" or not q.is_file(): return None
                return str(q)
            except Exception:
                return None
        # 先扫 HKLM（可信），无结果再扫 HKCU（用户可写，仅兜底）
        for hive, sub in roots + hkcu_roots:
            try:
                key = winreg.OpenKey(hive, sub)
            except Exception:
                continue
            i = 0
            while True:
                try:
                    sk = winreg.OpenKey(key, winreg.EnumKey(key, i))
                except OSError:
                    break
                i += 1
                try:
                    disp = winreg.QueryValueEx(sk, "DisplayName")[0]
                except Exception:
                    continue
                if not any(n.lower() in disp.lower() for n in names):
                    continue
                for field in ("DisplayIcon", "InstallLocation"):
                    try:
                        v = winreg.QueryValueEx(sk, field)[0]
                    except Exception:
                        continue
                    v = str(v).strip('"').split(",")[0]
                    if v.lower().endswith(".exe"):
                        sv=safe_candidate(v)
                        if sv: return sv
                    if v and Path(v).is_dir():
                        for exe in Path(v).rglob("*.exe"):
                            low = exe.name.lower()
                            # 轮13：用工具的 reg 名称/可执行名匹配，而非全局 6 词白名单
                            if any(n.lower() in low for n in names) or any(
                                    k in low for k in ("slicer","krita","freecad","cura",
                                                      "uvtools","blender","openscad","meshlab",
                                                      "opentoonz","aseprite")):
                                sv=safe_candidate(str(exe))
                                if sv: return sv
                try:
                    winreg.CloseKey(sk)
                except Exception:
                    pass
    except Exception:
        pass
    return None


def find_exe(patterns, regnames=None):
    for pat in patterns or []:
        if any(ch in pat for ch in "*?"):
            try:
                hits = sorted(__import__("glob").glob(pat))
                if hits:
                    return hits[0]
            except Exception:
                pass
        elif Path(pat).is_file():
            return pat
    if regnames:
        return registry_exe(regnames)
    return None


def pip_installed(mod):
    """真正的导入检测：必须检查 returncode，否则 import 失败也返回 True。"""
    try:
        r = subprocess.run([sys.executable, "-c", "import " + mod],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        return r.returncode == 0
    except Exception:
        return False


def _load_install_state():
    try:
        d=json.loads(INSTALL_STATE.read_text(encoding="utf-8"))
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}

def _save_install_state(st):
    try:
        with _LOG_LOCK:
            INSTALL_STATE.write_text(json.dumps(st,ensure_ascii=False,indent=2),encoding="utf-8")
    except Exception:
        pass

def _set_install_state(tid, state, extra=""):
    st=_load_install_state()
    st[tid]={"state":state,"time":time.strftime("%Y-%m-%d %H:%M:%S"),"detail":extra[:300]}
    _save_install_state(st)


def status_of(tid, t):
    if t["kind"] == "cli":
        mod = t.get("pip", "").split("=")[0]
        ok = pip_installed(mod) if mod else False
        return {"id": tid, "name": t["name"], "kind": t["kind"], "installed": ok,
                "path": "", "winget": t.get("winget", ""), "pip": t.get("pip", ""), "note": t.get("note", "")}
    if t["kind"] == "web":
        return {"id": tid, "name": t["name"], "kind": t["kind"], "installed": True,
                "path": "", "url": t.get("url", ""), "note": "云端 / 网页版，点击在浏览器打开"}
    exe = find_exe(t.get("exe", []), t.get("reg")) if (t.get("exe") or t.get("reg")) else None
    return {"id": tid, "name": t["name"], "kind": t["kind"], "installed": bool(exe),
            "path": exe or "", "winget": t.get("winget", ""), "note": t.get("note", "")}


_STATUS_CACHE = {"ts": 0.0, "data": None}
_STATUS_LOCK = threading.Lock()
STATUS_TTL = 30.0     # 秒；安装动作会主动失效缓存


def invalidate_status_cache():
    """轮15：安装/卸载后立即刷新，避免 30s 内拿到陈旧状态。"""
    with _STATUS_LOCK:
        _STATUS_CACHE["ts"] = 0.0
        _STATUS_CACHE["data"] = None


def all_status(force=False):
    """轮15：状态检测要 spawn 4 个子进程（每个最多 8s）+ 遍历注册表，
    最坏 30s+。缓存 30s，避免每次 ping 后的探测都重跑一遍。
    """
    now = time.time()
    with _STATUS_LOCK:
        if not force and _STATUS_CACHE["data"] is not None and (now - _STATUS_CACHE["ts"]) < STATUS_TTL:
            return list(_STATUS_CACHE["data"])
    data = [status_of(tid, t) for tid, t in TOOLS.items()]
    with _STATUS_LOCK:
        _STATUS_CACHE["ts"] = now
        _STATUS_CACHE["data"] = list(data)
    return data


def launch(tid):
    t = TOOLS.get(tid)
    if not t:
        return False, "未知工具 id: " + tid
    if t["kind"] == "web":
        webbrowser.open(t.get("url", ""))
        return True, "已在浏览器打开 " + t["name"]
    if t["kind"] == "cli":
        return False, t["name"] + " 是 Python 命令行库，无 GUI 可启动；在脚本里 import 使用即可。"
    if tid == "comfyui":
        # 第十二轮：便携版直接起服务（独立控制台窗口、不自动开浏览器），与 start-all.bat 一致
        bat = find_exe(t.get("exe", []), None)
        if bat:
            root = Path(bat).parent
            py = root / "python_embeded" / "python.exe"
            if py.is_file():
                flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                subprocess.Popen([str(py), "-s", "ComfyUI\\main.py", "--windows-standalone-build",
                                  "--disable-auto-launch", "--disable-dynamic-vram", "--cache-classic"],   # 见 start-all.bat 的说明
                                 cwd=str(root), creationflags=flags)
                return True, "已启动 ComfyUI（约 30 秒就绪，就绪后执行台会显示「运行中」）"
    if t["kind"] == "suite":
        return False, t["name"] + " 需先安装框架与模型权重，请按「安装AI引擎说明.md」启动。"
    exe = find_exe(t.get("exe", []), t.get("reg")) if (t.get("exe") or t.get("reg")) else None
    if not exe:
        return False, t["name"] + " 未检测到本地安装，请先一键安装"
    try:
        if exe.lower().endswith(".bat"):
            subprocess.Popen(exe, shell=True, cwd=str(Path(exe).parent))
        else:
            subprocess.Popen([exe], shell=False, cwd=str(Path(exe).parent))
        # 轮14：与 /api/log 脱敏口径一致——回给前端的也只保留文件名，
        # 不把本机绝对路径（含用户名/安装布局）显示在页面状态栏里。
        return True, "已启动 " + t["name"] + " :: " + Path(exe).name
    except Exception as e:
        return False, "启动失败: " + str(e)


def install(tid):
    """轮12：所有出口统一在 finally 落终态。

    v1.9 只有 winget 分支写状态，pip 成功/失败、超时、异常四条出口直接 return，
    状态永久停在 pending（用户看到"安装中"永不结束，重启也不自愈）。
    改为单一 final_state 变量 + finally 写盘，杜绝"新增分支又忘记写状态"。
    """
    t = TOOLS.get(tid)
    if not t:
        return False, "未知工具 id: " + tid
    _set_install_state(tid,"pending","started")
    final_state = None
    try:
        if t["kind"] == "cli" and t.get("pip"):
            r = subprocess.run([sys.executable, "-m", "pip", "install", t["pip"]],
                               capture_output=True, text=True, timeout=600)
            ok = r.returncode == 0
            final_state = ("succeeded" if ok else "failed",
                           ("pip 安装成功: " + t["pip"]) if ok else ("pip 失败: " + r.stderr[-300:]))
            return ok, final_state[1]
        if t.get("winget"):
            cmd = ["winget", "install", "--id", t["winget"], "--exact", "--silent",
                   "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            out = r.stdout + r.stderr
            # 轮15：returncode 为主，兼容中英文"已安装"文案
            already = ("already installed" in out.lower() or
                       "已安装" in out or "已安装的版本" in out)
            ok = r.returncode == 0 or already
            final_state = ("succeeded" if ok else "failed", out if ok else out[-300:])
            if ok:
                return True, "winget 安装完成: " + t["winget"]
            return False, "winget 失败: " + out[-300:] + "（如需重试请先检查是否残留部分安装）"
        final_state = ("manual", "无 winget/pip 一键路径，需手动安装")
        return False, t["name"] + " 需要手动安装（无 winget/pip 一键路径），已为你打开官方页面"
    except subprocess.TimeoutExpired:
        # 轮15：按分支给正确超时数字（pip=10分钟 / winget=15分钟）
        limit = "10 分钟" if (t.get("kind") == "cli") else "15 分钟"
        final_state = ("failed", "安装超时（>" + limit + "）")
        return False, "安装超时（>" + limit + "），请手动检查"
    except Exception as e:
        final_state = ("failed", "安装异常: " + str(e))
        return False, "安装异常: " + str(e)
    finally:
        if final_state:
            _set_install_state(tid, final_state[0], final_state[1])
        else:   # 兜底：任何未预期路径都不留 pending
            _set_install_state(tid, "failed", "未预期退出")



def _diag():
    out = {}
    def run(args, t=15):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=t,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return (r.stdout or r.stderr or "").strip()
        except Exception as e:
            return "ERR " + str(e)
    out["gpu"] = run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,clocks.sm,clocks_throttle_reasons.active",
                      "--format=csv,noheader"])
    out["gpu_apps"] = run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"])
    out["top_mem"] = run(["powershell", "-NoProfile", "-Command",
                          "Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 "
                          "| ForEach-Object { '{0} {1} {2}MB cpu={3}' -f $_.Id,$_.ProcessName,[int]($_.WorkingSet64/1MB),[int]$_.CPU }"], 30)
    out["mem"] = run(["powershell", "-NoProfile", "-Command",
                      "$o=Get-CimInstance Win32_OperatingSystem; '{0}MB free of {1}MB; commit {2}MB of {3}MB' -f "
                      "[int]($o.FreePhysicalMemory/1KB),[int]($o.TotalVisibleMemorySize/1KB),"
                      "[int](($o.TotalVirtualMemorySize-$o.FreeVirtualMemory)/1KB),[int]($o.TotalVirtualMemorySize/1KB)"], 30)
    return out

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # 轮6：keep-alive，需每个响应带 Content-Length（_json 已有）

    def _origin_allowed(self):
        """浏览器请求：仅放行 file://(null) 与本机 http(s) 预览来源。"""
        origin = self.headers.get("Origin")
        if not origin:
            return True  # 非浏览器请求，靠 Host 校验
        if origin == "null":
            return True  # file:// 打开工坊
        try:
            o = urlparse(origin)
            if o.scheme in ("http", "https") and (o.hostname or "").lower() in LOCAL_HOSTS:
                return True
        except Exception:
            pass
        return False

    def _host_allowed(self):
        """所有请求都要过 Host 校验，挡住 DNS rebinding。"""
        host = self.headers.get("Host", "")
        hostname = host.split(":")[0].strip("[]").lower()
        return hostname in LOCAL_HOSTS

    def _forbidden(self):
        return (not self._host_allowed()) or (not self._origin_allowed())

    def _cors(self):
        # 不再使用通配符：只反射已验证的本机来源
        origin = self.headers.get("Origin")
        if origin == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
        elif origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Bridge-Token")

    def _referer_ok(self):
        """轮9修正：校验来源为本机页面。恶意 file:// HTML 的 Referer 是 file:// 开头，在此被拒。
        注意：不能要求 Referer 含 studio.html——内置浏览器的静态代理会改写路径，
        合法页面的 Referer 形如 http://127.0.0.1:5104/（不含文件名）。"""
        ref = (self.headers.get("Referer") or "").lower()
        if not ref: return False
        try:
            o = urlparse(ref)
            if o.scheme in ("http","https") and (o.hostname or "").lower() in LOCAL_HOSTS:
                return True
            # file:// 是交付包的正常打开方式（双击 studio.html）。
            # 协议层无法区分合法工坊与恶意本地 HTML——这是 file:// 的固有限制，
            # 已在迭代记录中如实标注。这里只放行明确指向 studio.html 的 file 来源，
            # 并记警告日志留痕；恶意 HTML 若伪装该文件名，需用户主动双击，属社工范畴。
            if o.scheme == "file" and ref.rstrip("/").lower().endswith("studio.html"):
                w("NOTE file:// origin accepted (inherent file:// trust limit)")
                return True
            return False
        except Exception:
            return False

    def _guard(self):
        """统一入口守卫：不合法直接 403 并返回 True。"""
        if self._forbidden():
            w("FORBIDDEN host=%s origin=%s" % (
                self.headers.get("Host", ""), self.headers.get("Origin", "-")))
            self.close_connection = True   # 第十九轮：没读请求体就拒绝 → 必须断开，否则残留的请求体会被当成下一个请求
            self._json({"ok": False, "error": "forbidden origin/host"}, 403)
            return True
        return False

    def _token_guard(self):
        """轮1/6：敏感操作要求自定义头 token（挡 form submit 与无 token 的 fetch）。"""
        got = self.headers.get("X-Bridge-Token", "")
        if got != _BRIDGE_TOKEN:
            w("REJECT token-less sensitive request")
            # 第十九轮：这里还没读请求体。保持连接的话，残留的 JSON 正文会被当成下一个请求的开头
            # （实测：令牌失效 → 页面重新申请令牌并重发 → 拿到 501 "Unsupported method"）。拒绝后断开连接。
            self.close_connection = True
            self._json({"ok": False, "error": "missing/invalid bridge token"}, 403)
            return True
        return False

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")  # 轮10
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        # 轮20：终止连接的响应必须显式告知客户端，不能只靠 close_connection + EOF 让它猜
        if self.close_connection:
            self.send_header("Connection", "close")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if self._guard(): return
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self._cors()
        self.end_headers()

    # 第十二轮：桥直接托管工坊页面。file:// 页面发出的请求浏览器一律不带 Referer，
    # /api/challenge 因此永远拒绝（日志 "CHALLENGE denied (referer=-)"），一键执行不可用。
    # 从 http://127.0.0.1:7843/studio.html 打开后与 API 同源，Referer 为本机 http 来源，
    # 走既有的 _referer_ok 规则——安全口径不变（远程网站无法伪造本机 Referer）。
    # 白名单托管，不做任意路径映射，杜绝路径穿越。
    STATIC = {
        "/": ("index.html", "text/html; charset=utf-8"),     # 第二十轮：统一入口——根地址是导航首页
        "/studio.html": ("studio.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/github-creative-tools-atlas.html": ("github-creative-tools-atlas.html", "text/html; charset=utf-8"),
        "/route-a-painter-workstation.html": ("route-a-painter-workstation.html", "text/html; charset=utf-8"),
        "/icon.png": ("icon.png", "image/png"),
        "/icon.ico": ("icon.ico", "image/x-icon"),
    }

    def _send_static(self, path):
        name, ctype = self.STATIC[path]
        f = HERE.parent / name
        if not f.is_file():
            return self._json({"ok": False, "error": "not found"}, 404)
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self._guard(): return
        u = urlparse(self.path)
        if u.path in self.STATIC:
            return self._send_static(u.path)
        if u.path == "/api/ping":
            # 轮2：公开可验证的身份标识（前端核对 service/version，挡住假服务）
            return self._json({"ok": True, "service": SERVICE, "version": VERSION, "port": PORT, "stamp": CODE_STAMP})
        if u.path == "/api/challenge":
            # 轮1：challenge token 只发给来自 studio.html 的请求
            if not self._referer_ok():
                w("CHALLENGE denied (referer=%s)" % (self.headers.get("Referer", "-")))
                return self._json({"ok": False, "error": "challenge requires studio.html referer"}, 403)
            return self._json({"ok": True, "token": _BRIDGE_TOKEN, "service": SERVICE})
        if u.path == "/api/status":
            fresh = parse_qs(u.query).get("fresh", [""])[0] == "1"
            return self._json({"ok": True, "tools": all_status(force=fresh),
                               "cached": not fresh})
        if u.path == "/api/log":
            txt = LOG.read_text(encoding="utf-8")[-4000:] if LOG.exists() else ""
            return self._json({"ok": True, "log": txt})
        # ---- 自动化引擎端点 ----
        if u.path == "/api/engine":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            avail, info = _auto.comfy_available()
            return self._json({"ok": True, "comfy_online": avail, "comfy": info,
                               "comfy_url": _auto.COMFY_URL})
        if u.path == "/api/diag":
            # 第二十轮：只读诊断——谁在占显卡 / 内存（出图忽快忽慢时排查用），不接受任何参数
            return self._json(dict(_diag(), ok=True))
        if u.path == "/api/models":
            # 第二十轮：出图底模列表（是否已下载 / 下载进度）
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            return self._json({"ok": True, "models": _auto.ckpt_status()})
        if u.path == "/api/translate/status":
            # 第十九轮：本地翻译模型状态（只读）
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            return self._json(dict(_auto.translate_state(), ok=True))
        if u.path == "/api/jobs":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            return self._json({"ok": True, "jobs": _auto.list_jobs()})
        if u.path.startswith("/api/job/") and "/file/" in u.path:
            # 第十二轮：产物缩略图——只回本作业目录里的图片，文件名取 basename
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            jid, _, name = u.path[len("/api/job/"):].partition("/file/")
            from urllib.parse import unquote
            f = _auto.job_file(jid, unquote(name))
            ctypes_ = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            if f is None or f.is_dir() or f.suffix.lower() not in ctypes_:
                return self._json({"ok": False, "error": "not found"}, 404)
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctypes_[f.suffix.lower()])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path.startswith("/api/job/"):
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            jid = u.path.split("/api/job/", 1)[1].split("?")[0]
            job = _auto.get_job(jid)
            if not job:
                return self._json({"ok": False, "error": "job not found"}, 404)
            return self._json({"ok": True, "job": job})
        self._json({"ok": False, "error": "not found"}, 404)

    def _plugin_ok(self):
        import hmac
        got = self.headers.get("X-Atlas-Plugin", "")
        return bool(got) and urlparse(self.path).path in PLUGIN_PATHS and hmac.compare_digest(got, _PLUGIN_TOKEN)

    def do_POST(self):
        if self._guard(): return
        if not self._plugin_ok() and self._token_guard(): return
        # 轮11：兑现"不污染下一次请求"的承诺。HTTP/1.1 keep-alive 下，
        # 只读 min(n,65536) 会把剩余字节留在流里，被当成下一个请求的方法行。
        # 因此超限直接 413 并关闭连接；合法大小则精确读满 n 字节。
        try:
            n = int(self.headers.get('Content-Length', '0') or 0)
        except ValueError:
            n = 0
        # 第二十轮：上传输入文件的两个接口放宽到 200MB，其余仍是 64KB
        limit = 200 * 1024 * 1024 if urlparse(self.path).path in UPLOAD_PATHS else 65536
        if n < 0 or n > limit:
            self.close_connection = True
            return self._json({"ok": False, "error": "request body too large (max %s)" % (
                "200MB" if limit > 65536 else "64KB")}, 413)
        if n > 0:
            got = self.rfile.read(n)
            if len(got) != n:          # 对端提前断开，同样不能复用这条连接
                self.close_connection = True
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        tid = (qs.get("id") or [""])[0]
        if u.path == "/api/launch":
            ok, msg = launch(tid)
            w("LAUNCH %s -> %s (%s)" % (tid, "OK" if ok else "FAIL", msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/install":
            # 轮20：并发去重——同一工具正在安装时不重复拉起进程
            with _INSTALL_LOCK:
                if tid in _INSTALLING:
                    return self._json({"ok": False, "message": tid + " 正在安装中，请勿重复点击"})
                _INSTALLING.add(tid)
            try:
                ok, msg = install(tid)
            finally:
                with _INSTALL_LOCK:
                    _INSTALLING.discard(tid)
                invalidate_status_cache()   # 轮15：安装后状态必须立刻重算，不能等 TTL
            w("INSTALL %s -> %s (%s)" % (tid, "OK" if ok else "FAIL", msg))
            return self._json({"ok": ok, "message": msg})
        # ---- 自动化引擎端点（走同一 token 守卫，安全等级与 launch/install 一致）----
        if u.path == "/api/job/create":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            try:
                body = json.loads(got.decode("utf-8") if n > 0 else "{}")
            except Exception:
                return self._json({"ok": False, "error": "invalid JSON body"}, 400)
            if not isinstance(body, dict) or not isinstance(body.get("steps"), list):
                return self._json({"ok": False, "error": "job spec needs 'steps' array"}, 400)
            if len(body["steps"]) > 50:
                return self._json({"ok": False, "error": "too many steps (max 50)"}, 400)
            # 轮18：校验每个 step 是对象且 kind/label 是字符串——畸形作业单会让
            # 引擎 step.get() 崩溃。提前拒绝，返回 400 而不是让作业静默失败。
            bad_steps = [i for i, s in enumerate(body["steps"])
                         if not isinstance(s, dict)
                         or not isinstance(s.get("kind", ""), str)
                         or not isinstance(s.get("label", ""), str)]
            if bad_steps:
                return self._json({"ok": False,
                                   "error": "invalid step at index %s (need object with string kind/label)"
                                            % bad_steps[:3]}, 400)
            jid = _auto.create_job(body)
            w("JOB created %s (%d steps)" % (jid, len(body["steps"])))
            return self._json({"ok": True, "job_id": jid})
        if u.path == "/api/job/resume":
            # 第十二轮：人工接手后继续（人工步骤记为完成；自动步骤因故暂停则重试）
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            ok, msg = _auto.resume_job(tid)
            w("JOB resume %s -> %s" % (tid, msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/translate/install":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            ok, msg = _auto.install_translator(mirror=(qs.get("mirror") or [""])[0] == "1")
            w("TRANSLATE install -> %s" % msg)
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/translate":
            # 第十九轮：中文提示词 → 英文（页面预览 / Krita 面板精修前调用）
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            try:
                body = json.loads(got.decode("utf-8") if n > 0 else "{}")
                texts = [str(t)[:4000] for t in (body.get("texts") or [])][:10]
            except Exception:
                return self._json({"ok": False, "error": "invalid JSON body"}, 400)
            res = [_auto.to_english(t) for t in texts]
            return self._json({"ok": True, "texts": [r[0] for r in res], "untranslated": [m for r in res for m in r[1]]})
        if u.path in UPLOAD_PATHS:
            # 第二十轮：上传输入文件（原始字节作请求体，文件名在 ?name= 里只用来取扩展名）
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            if n <= 0 or len(got) != n:
                return self._json({"ok": False, "message": "上传不完整"}, 400)
            name = (qs.get("name") or [""])[0]
            if u.path == "/api/upload":
                ok, res = _auto.save_upload(got, name)
                w("UPLOAD %s %d bytes -> %s" % (os.path.splitext(name)[1], n, res if ok else "FAIL"))
                return self._json({"ok": ok, "name": res} if ok else {"ok": False, "message": res})
            ok, msg = _auto.add_job_input(tid, got, name)
            w("JOB input %s %d bytes -> %s" % (tid, n, msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/comfy/restart":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            ok, msg = _auto.restart_comfy()
            w("COMFY restart -> %s" % msg)
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/models/install":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            ok, msg = _auto.install_ckpt((qs.get("name") or [""])[0])
            w("MODEL install %s -> %s" % ((qs.get("name") or [""])[0], msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/job/pick":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            ok, msg = _auto.pick_variant(tid, (qs.get("name") or [""])[0])
            w("JOB pick %s -> %s" % (tid, msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/job/spec":
            # 第十八轮：Krita 面板（或页面）改提示词，写回作业单
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            try:
                body = json.loads(got.decode("utf-8") if n > 0 else "{}")
            except Exception:
                return self._json({"ok": False, "error": "invalid JSON body"}, 400)
            ok, msg = _auto.update_spec(tid, body if isinstance(body, dict) else {})
            w("JOB spec %s -> %s" % (tid, msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/job/branch":
            # 第十三轮：接手卡片上的 A/B/C 方案按钮——换成所选方案的后续步骤并继续执行
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            plan = (qs.get("plan") or [""])[0]
            if plan not in getattr(_auto, "PLANS", {}):
                return self._json({"ok": False, "message": "不支持的方案"}, 400)
            detail = (qs.get("detail") or [""])[0]
            ok, msg = _auto.branch_job(tid, plan, detail if detail in ("fine", "fast") else "")
            w("JOB branch %s %s -> %s" % (tid, plan, msg))
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/job/open":
            # 第十二轮：打开产物文件夹 / 用 Krita 打开产物
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            name = (qs.get("name") or [""])[0]
            with_tool = (qs.get("with") or [""])[0]
            if with_tool not in ("", "folder", "krita"):
                return self._json({"ok": False, "message": "不支持的打开方式"}, 400)
            ok, msg = _auto.open_job_output(tid, name, with_tool)
            return self._json({"ok": ok, "message": msg})
        if u.path == "/api/job/stop":
            if not _auto:
                return self._json({"ok": False, "error": "automation engine unavailable"}, 503)
            # 轮3：优先按 jid 停止单个作业；未指定才全局停止
            stop_id = tid or (qs.get("job_id") or [""])[0]
            if stop_id:
                _auto.stop_job(stop_id)
                w("JOB stop requested: " + stop_id)
                return self._json({"ok": True, "message": "已请求停止作业 " + stop_id})
            _auto.stop_engine()
            w("JOB stop requested (global)")
            return self._json({"ok": True, "message": "已请求停止全部（当前步骤结束后生效）"})
        self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass  # 静默，避免刷屏


def _disk_stamp():
    return _hl.sha256(b"".join((HERE / n).read_bytes() for n in ("tool-bridge.py", "automation.py")
                               if (HERE / n).is_file())).hexdigest()[:12]


def _auto_reload_watch(srv):
    """第十九轮：代码文件更新后自动换成新代码，不用用户再双击 start-all.bat。
    条件：磁盘上的代码指纹变了、新代码能编译通过、没有作业正在执行（暂停 / 完成的作业已落盘，重启后照常接着用）。"""
    while True:
        time.sleep(4)
        try:
            stamp = _disk_stamp()
            if stamp == CODE_STAMP:
                continue
            for n in ("tool-bridge.py", "automation.py"):     # 只检查语法，不写 .pyc
                compile((HERE / n).read_text(encoding="utf-8"), str(HERE / n), "exec")
            # 第二十轮：语法对不等于能跑——实测出现过"常量在定义之前被使用"，导入即崩。
            # 切换前在独立进程里真正导入一遍新代码（不启动服务），通过才切换。
            chk = subprocess.run(
                [sys.executable, "-c",
                 "import importlib.util,sys;sys.path.insert(0,sys.argv[1]);import automation;"
                 "s=importlib.util.spec_from_file_location('tb_check',sys.argv[1]+'/tool-bridge.py');"
                 "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print('IMPORT_OK')", str(HERE)],
                capture_output=True, text=True, timeout=90, cwd=str(HERE),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if "IMPORT_OK" not in chk.stdout:
                w("AUTO-RELOAD skipped: new code fails to import: %s" % (chk.stderr or chk.stdout)[-300:].replace("\n", " | "))
                time.sleep(60)
                continue
            if _auto and any(j.get("status") in ("queued", "running") for j in _auto.list_jobs()):
                continue          # 有作业在跑：等它结束再换
            w("AUTO-RELOAD code %s -> %s" % (CODE_STAMP, stamp))
            if _auto:
                _auto._save_jobs(force=True)
                try:
                    p = _auto._TR_PROC.get("p")
                    if p is not None:
                        p.kill()
                except Exception:
                    pass
            flags = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                     | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            subprocess.Popen([sys.executable, str(HERE / "tool-bridge.py")], cwd=str(HERE), creationflags=flags,
                             close_fds=True)
            srv.server_close()
            os._exit(0)
        except SyntaxError as e:
            w("AUTO-RELOAD skipped: new code does not compile: %s" % str(e)[:200])
            time.sleep(30)
        except Exception as e:
            w("AUTO-RELOAD error: %s" % str(e)[:200])
            time.sleep(30)


def main():
    if sys.version_info < (3, 7):
        print("ERROR: tool-bridge needs Python 3.7+; found " + sys.version.split()[0])
        sys.exit(1)
    w("tool-bridge starting on 127.0.0.1:%d" % PORT)
    try:   # 第十八轮：给 Krita 面板的令牌（每次启动更换）
        tmp = HERE / ".krita_token.tmp"
        tmp.write_text(_PLUGIN_TOKEN, encoding="utf-8")
        tmp.replace(HERE / ".krita_token")
    except Exception as e:
        w("write .krita_token failed: %s" % e)
    srv = None
    for _ in range(30):     # 第十九轮：自动更新重启时，旧进程可能还没完全释放端口——最多等 15 秒
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
            break
        except OSError as e:
            last_err = e
            time.sleep(0.5)
    if srv is None:
        e = last_err
        w("tool-bridge FAILED to bind port %d: %s" % (PORT, e))
        w("Maybe another instance is running; use start-tool-bridge.ps1 -Stop first.")
        sys.exit(1)
    atexit.register(lambda: w("tool-bridge exiting."))
    if _auto:
        try:
            _auto.start_engine()
            w("automation engine ready (comfy=" + _auto.COMFY_URL + ")")
        except Exception as e:
            w("automation engine start failed: " + str(e)[:120])
    threading.Thread(target=_auto_reload_watch, args=(srv,), daemon=True).start()
    w("tool-bridge ready.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        w("tool-bridge stopped.")
        srv.shutdown()


if __name__ == "__main__":
    main()
