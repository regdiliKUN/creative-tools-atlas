#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装并启用 Krita 插件 Atlas AI Painter + 「Atlas 工坊」面板（创作工具星图 第十二轮 / 第十八轮）。

做两件事（幂等，可重复运行）：
  1. 把 pykrita/atlas_painter(.desktop) 复制到 %APPDATA%\\krita\\pykrita\\
  2. 在 %LOCALAPPDATA%\\kritarc 的 [python] 段写入 enable_atlas_painter=true
     （首次修改前备份为 kritarc.atlas.bak）

Krita 退出时会重写 kritarc，所以必须在 Krita 关闭时运行。
输出最后一行：INSTALLED / KRITA_RUNNING / ERROR: ...
"""
import os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "pykrita"


def krita_running():
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq krita.exe", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
        return "krita.exe" in out.lower()
    except Exception:
        return False


def enable_in_kritarc(rc: Path):
    raw = rc.read_bytes() if rc.is_file() else b""
    nl = "\r\n" if b"\r\n" in raw else "\n"     # 保留原换行风格，不动无关内容
    text = raw.decode("utf-8")
    bak = rc.with_name("kritarc.atlas.bak")
    if rc.is_file() and not bak.exists():
        shutil.copy2(rc, bak)
    lines = text.splitlines()
    key = "enable_atlas_painter=true"
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "[python]")
    except StopIteration:
        lines += ["", "[python]", key]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
        for i in range(start + 1, end):
            if lines[i].split("=")[0].strip() == "enable_atlas_painter":
                lines[i] = key
                break
        else:
            lines.insert(start + 1, key)
    rc.write_bytes((nl.join(lines) + nl).encode("utf-8"))


def main():
    if krita_running():
        print("KRITA_RUNNING"); return 2
    appdata = os.environ.get("APPDATA"); local = os.environ.get("LOCALAPPDATA")
    if not appdata or not local:
        print("ERROR: APPDATA/LOCALAPPDATA 未设置（仅支持 Windows）"); return 1
    dst = Path(appdata) / "krita" / "pykrita"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / "atlas_painter.desktop", dst / "atlas_painter.desktop")
    shutil.copytree(SRC / "atlas_painter", dst / "atlas_painter", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "atlas_config.json"))
    # 第十八轮：告诉面板工具桥在哪个目录（会话文件、面板令牌都在那里）
    cfg = {"bridge_dir": str(HERE.parent), "bridge_url": "http://127.0.0.1:7843",
           "comfy_url": "http://127.0.0.1:8188", "ckpt": "sd_xl_base_1.0.safetensors"}
    import json
    (dst / "atlas_painter" / "atlas_config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
    enable_in_kritarc(Path(local) / "kritarc")
    print("INSTALLED"); return 0


if __name__ == "__main__":
    sys.exit(main())
