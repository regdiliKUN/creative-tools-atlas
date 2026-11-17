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
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 7843
_LOG_LOCK = threading.Lock()          # 轮20：多线程日志串行化
_INSTALL_LOCK = threading.Lock()      # 轮20：安装去重（同一时刻只允许一个）
_INSTALLING = set()
# 安全白名单：只允许本机来源，防止任意网页/DNS rebinding 跨站触发 launch/install
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
HERE = Path(__file__).resolve().parent
LOG = HERE / "tool-bridge.log"

# 工具定义：id -> {name, kind, winget, pip, exe(glob 候选), args, note}
# kind: desktop=有 exe 可启动 / cli=pip 包 / suite=依附宿主(ComfyUI/Blender) / web=云端或源码
TOOLS = {
    "krita":        {"name":"Krita","kind":"desktop","winget":"KDE.Krita","exe":[r"C:\Program Files\Krita (x64)\krita.exe",r"C:\Program Files\Krita\krita.exe"],"reg":["Krita"]},
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
    "comfyui":      {"name":"ComfyUI","kind":"suite","exe":[r"C:\ComfyUI\run_nvidia_gpu.bat",r"D:\ComfyUI\run_nvidia_gpu.bat"]},
    "trimesh":      {"name":"trimesh","kind":"cli","pip":"trimesh"},
    "cadquery":     {"name":"CadQuery","kind":"cli","pip":"cadquery"},
    "assimp":       {"name":"Assimp","kind":"cli","pip":"pyassimp"},
    "smplx":        {"name":"smplx","kind":"cli","pip":"smplx"},
    "excalidraw":   {"name":"excalidraw","kind":"web","url":"https://excalidraw.com"},
    "charstudio":   {"name":"CharacterStudio","kind":"web","url":"https://m3-org.github.io/CharacterStudio/"},
    "threestudio":  {"name":"threestudio","kind":"web","url":"https://github.com/threestudio-project/threestudio"},
}


def w(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with _LOG_LOCK:
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
        roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                 (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
        for hive, sub in roots:
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
                    if v.lower().endswith(".exe") and Path(v).is_file():
                        return v
                    if v and Path(v).is_dir():
                        for exe in Path(v).rglob("*.exe"):
                            low = exe.name.lower()
                            # 轮13：用工具的 reg 名称/可执行名匹配，而非全局 6 词白名单
                            if any(n.lower() in low for n in names) or any(
                                    k in low for k in ("slicer","krita","freecad","cura",
                                                      "uvtools","blender","openscad","meshlab",
                                                      "opentoonz","aseprite")):
                                return str(exe)
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


def all_status():
    return [status_of(tid, t) for tid, t in TOOLS.items()]


def launch(tid):
    t = TOOLS.get(tid)
    if not t:
        return False, "未知工具 id: " + tid
    if t["kind"] == "web":
        webbrowser.open(t.get("url", ""))
        return True, "已在浏览器打开 " + t["name"]
    if t["kind"] == "cli":
        return False, t["name"] + " 是 Python 命令行库，无 GUI 可启动；在脚本里 import 使用即可。"
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
        return True, "已启动 " + t["name"] + " :: " + exe
    except Exception as e:
        return False, "启动失败: " + str(e)


def install(tid):
    t = TOOLS.get(tid)
    if not t:
        return False, "未知工具 id: " + tid
    try:
        if t["kind"] == "cli" and t.get("pip"):
            r = subprocess.run([sys.executable, "-m", "pip", "install", t["pip"]],
                               capture_output=True, text=True, timeout=600)
            ok = r.returncode == 0
            return ok, ("pip 安装成功: " + t["pip"]) if ok else ("pip 失败: " + r.stderr[-300:])
        if t.get("winget"):
            cmd = ["winget", "install", "--id", t["winget"], "--exact", "--silent",
                   "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            out = r.stdout + r.stderr
            # 轮15：returncode 为主，兼容中英文"已安装"文案
            already = ("already installed" in out.lower() or
                       "已安装" in out or "已安装的版本" in out)
            ok = r.returncode == 0 or already
            return ok, ("winget 安装完成: " + t["winget"]) if ok else ("winget 失败: " + out[-300:])
        return False, t["name"] + " 需要手动安装（无 winget/pip 一键路径），已为你打开官方页面"
    except subprocess.TimeoutExpired:
        # 轮15：按分支给正确超时数字（pip=10分钟 / winget=15分钟）
        limit = "10 分钟" if (t.get("kind") == "cli") else "15 分钟"
        return False, "安装超时（>" + limit + "），请手动检查"
    except Exception as e:
        return False, "安装异常: " + str(e)


class Handler(BaseHTTPRequestHandler):
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _guard(self):
        """统一入口守卫：不合法直接 403 并返回 True。"""
        if self._forbidden():
            w("FORBIDDEN host=%s origin=%s" % (
                self.headers.get("Host", ""), self.headers.get("Origin", "-")))
            self._json({"ok": False, "error": "forbidden origin/host"}, 403)
            return True
        return False

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        if self._guard(): return
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self._guard(): return
        u = urlparse(self.path)
        if u.path == "/api/ping":
            return self._json({"ok": True, "service": "atlas-tool-bridge", "port": PORT})
        if u.path == "/api/status":
            return self._json({"ok": True, "tools": all_status()})
        if u.path == "/api/log":
            txt = LOG.read_text(encoding="utf-8")[-4000:] if LOG.exists() else ""
            return self._json({"ok": True, "log": txt})
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if self._guard(): return
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
            w("INSTALL %s -> %s (%s)" % (tid, "OK" if ok else "FAIL", msg))
            return self._json({"ok": ok, "message": msg})
        self._json({"ok": False, "error": "not found"}, 404)

    def log_message(self, fmt, *args):
        pass  # 静默，避免刷屏


def main():
    w("tool-bridge starting on 127.0.0.1:%d" % PORT)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        w("tool-bridge FAILED to bind port %d: %s" % (PORT, e))
        w("Maybe another instance is running; use start-tool-bridge.ps1 -Stop first.")
        sys.exit(1)
    w("tool-bridge ready.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        w("tool-bridge stopped.")
        srv.shutdown()


if __name__ == "__main__":
    main()
