#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创作工具星图 - 本地启动器 (v1.6.0)。

双击 exe 后：在本程序所在目录寻找 index.html，以应用窗口方式打开，
避免出现传统浏览器的地址栏/标签栏弹窗观感。纯本地、无联网、无第三方依赖。

设计要点：
  · 应用窗口优先：Edge / Chrome 的 --app 模式，无地址栏、无标签栏。
  · 多级回退：应用窗口 -> webbrowser -> 系统原生命令，保证"双击即可用"。
  · 中文/空格路径安全：用 urllib.parse.quote 对 file:// URL 编码。
  · windowed 模式静默：不向无效 stdout 打印中文，避免编码异常。
"""
import os
import sys
import subprocess
from urllib.parse import quote

# 应用窗口候选路径（按优先级，均为绝对安装路径）。--app 打开无地址栏的独立窗口。
# 只保留稳定的绝对安装路径：冻结 exe 里环境变量可能缺失，动态拼路径不可靠。
APP_BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def app_dir():
    """返回程序运行所在文件夹（打包后 = exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def file_url(path):
    """把本地路径转成安全的 file:// URL（兼容中文与空格）。"""
    return "file:///" + quote(os.path.abspath(path).replace("\\", "/"), safe="/:")


def launch_app_window(path):
    """优先用 Edge/Chrome 应用模式打开，返回是否成功提交。

    健壮性：捕获超时与 OSError，单个候选失败不影响后续回退。
    """
    url = file_url(path)
    for exe in APP_BROWSERS:
        if not exe or not os.path.isfile(exe):
            continue
        try:
            subprocess.Popen(
                [exe, "--app=" + url, "--new-window", "--window-size=1280,900"],
                shell=False,
                close_fds=True,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            continue
        except Exception:
            continue
    return False


def _pid_alive(pid):
    """判断 PID 对应进程是否仍存活（跨平台，零依赖）。"""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        # 权限受限等异常时保守视为「活着」，避免误判陈旧锁而多开窗口；
        # 真正的陈旧锁由 5 秒 TTL 兜底，不会永久挡住用户。
        return True


def acquire_single_instance(base):
    """短时去重锁：返回 True 表示本次应继续启动。

    关键约束：本 exe 是「启动器」——把 URL 交给浏览器后立刻退出，并不常驻。
    因此不能用长 TTL 的「单实例锁」（那会在用户关闭窗口后仍挡住再次启动）。
    这里只做「防连点」的毫秒级去重：TTL 设为 5 秒，仅过滤极短时间内重复双击，
    用户正常关闭窗口后再打开（几乎总是 >5 秒）绝不受影响。
    锁文件放系统临时目录，不污染软件包；锁失败降级为允许启动。
    """
    import tempfile
    import time
    import getpass
    # 按用户名隔离锁文件：多用户共享临时目录时互不干扰
    try:
        who = getpass.getuser()
    except Exception:
        who = "user"
    safe_who = "".join(c for c in who if c.isalnum() or c in ("-", "_")) or "user"
    lock = os.path.join(tempfile.gettempdir(), "creator-atlas-" + safe_who + ".lock")
    ttl = 5  # 秒，仅防连点；绝不可设长，否则会挡住正常使用
    try:
        if os.path.isfile(lock):
            age = time.time() - os.path.getmtime(lock)
            if age < ttl:
                # 校验锁内 PID：若记录进程已不存在，视为陈旧锁，立即失效
                try:
                    with open(lock, "r", encoding="ascii") as f:
                        old_pid = int(f.read().strip())
                    if _pid_alive(old_pid):
                        return False  # 进程活着且时间近 → 视为连点
                except Exception:
                    return False  # 读不出 PID 时保守视为有效锁（防连点）
        with open(lock, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        # 锁机制失败不应阻止应用启动，降级为允许多实例
        return True


def open_in_browser(path):
    url = file_url(path)
    # 主路径：应用窗口（无地址栏/标签栏弹窗感）
    if launch_app_window(path):
        return True
    # 回退 1：标准库 webbrowser
    # 注意：webbrowser.open 在 Windows 上成功时也常返回 None，不能用返回值判断
    # 成败（否则会误判失败、再多开一个窗口）。只要不抛异常即视为已提交。
    try:
        import webbrowser
        webbrowser.open(url)
        return True
    except Exception:
        pass
    # 回退 2：系统原生命令（Windows start 对中文路径更稳）
    try:
        if sys.platform == "win32":
            subprocess.Popen(["cmd", "/c", "start", "", path], shell=False)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


MISSING_PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>文件缺失 · 创作工具星图</title></head>
<body style="font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:48px;max-width:640px;margin:auto;color:#222">
<h2>找不到 index.html</h2>
<p>本启动器需要与 <b>index.html</b> 及两个报告 HTML 放在同一个文件夹里。</p>
<p>如果你是双击桌面快捷方式遇到此提示，请右键快捷方式 →「打开文件所在位置」，
确认该文件夹内同时存在 exe 和三个 HTML 文件。</p></body></html>"""


def verify_package(base):
    """静默自检：返回 (ok, 缺失清单)。供 --verify 与自动化终检调用。"""
    # 根本方案：直接读 MANIFEST.md 解析文件清单，而不是硬编码列表。
    # 这样清单增长（如新增迭代记录）时，启动器校验自动同步，永不脱节。
    import re
    manifest = os.path.join(base, "MANIFEST.md")
    missing = []
    if not os.path.isfile(manifest):
        return False, ["MANIFEST.md"]
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            text = f.read()
        required = re.findall(r"^\|\s*`([^`]+)`", text, re.M)
    except Exception:
        return False, ["MANIFEST.md (unreadable)"]
    for rel in required:
        norm = rel.replace("/", os.sep)
        # 安全边界：拒绝绝对路径与 .. 路径穿越，避免被篡改的清单读写到包外
        if os.path.isabs(norm) or ".." in norm.split(os.sep):
            missing.append(rel + " (unsafe path)")
            continue
        if not os.path.isfile(os.path.join(base, norm)):
            missing.append(rel)
    if not required:
        return False, ["MANIFEST.md (no entries)"]
    return (len(missing) == 0), missing


def main():
    base = app_dir()
    index = os.path.join(base, "index.html")

    # --verify：控制台自检模式，逐项打印包完整性，供自动化调用。
    if "--verify" in sys.argv:
        ok, missing = verify_package(base)
        print("VERIFY_OK" if ok else "VERIFY_FAIL")
        for f in missing:
            print("MISSING:" + f)
        sys.exit(0 if ok else 1)

    if not os.path.isfile(index):
        # 兜底页写到系统临时目录，绝不污染软件包本身
        import tempfile
        # ASCII 文件名：避免系统临时目录在 ANSI 代码页下无法正确编码中文名
        tmp = os.path.join(tempfile.gettempdir(), "creator-atlas-missing.html")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(MISSING_PAGE)
        index = tmp

    # 单实例保护：连点快捷方式时不再叠加多个窗口；
    # 锁获取失败时降级为正常启动，绝不阻断用户。
    if acquire_single_instance(base):
        open_in_browser(index)


if __name__ == "__main__":
    main()
