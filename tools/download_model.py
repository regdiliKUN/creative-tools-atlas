#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载一个大模型文件（创作工具星图 第二十轮：可选的插画向出图模型）。

  python download_model.py <repo> <文件名> <保存路径> <进度json>

- 断点续传（.part）；主站失败自动换 hf-mirror.com，每个源重试 3 次；
- 大小以服务器给出的字节数为准，下载完核对；.safetensors 再校验文件头（JSON 头能解析）；
- 进度写进 <进度json>：{state, done, total, host, error}。只用标准库。
"""
import json
import os
import struct
import sys
import time
import urllib.request
from pathlib import Path

HOSTS = ["https://huggingface.co", "https://hf-mirror.com"]


def progress(path, **kw):
    try:
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(dict(kw, time=time.strftime("%H:%M:%S")), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def safetensors_ok(p):
    try:
        with open(p, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if not (0 < n < 100 * 1024 * 1024):
                return False
            json.loads(f.read(n).decode("utf-8"))
        return True
    except Exception:
        return False


def fetch(host, repo, name, dst, prog):
    part = Path(str(dst) + ".part")
    have = part.stat().st_size if part.is_file() else 0
    url = "%s/%s/resolve/main/%s" % (host, repo, name)
    hdr = {"User-Agent": "creator-atlas/2.1"}
    if have:
        hdr["Range"] = "bytes=%d-" % have
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=60) as r:
        if have and r.status != 206:
            have = 0
        if r.status == 206:
            total = int((r.headers.get("Content-Range") or "/0").split("/")[-1] or 0)
        else:
            total = int(r.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as f:
            last = 0
            while True:
                chunk = r.read(4 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if time.time() - last > 1:
                    last = time.time()
                    progress(prog, state="downloading", done=have, total=total, host=host)
    if total and part.stat().st_size != total:
        raise IOError("大小不对：%d / %d 字节" % (part.stat().st_size, total))
    if name.endswith(".safetensors") and not safetensors_ok(part):
        raise IOError("文件头校验失败（不是完整的 safetensors）")
    part.replace(dst)
    return total


def main():
    repo, name, dst, prog = sys.argv[1], sys.argv[2], Path(sys.argv[3]), Path(sys.argv[4])
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and (not name.endswith(".safetensors") or safetensors_ok(dst)):
        progress(prog, state="done", done=dst.stat().st_size, total=dst.stat().st_size)
        print("MODEL_OK")
        return 0
    err = None
    for host in HOSTS:
        for _ in range(3):
            try:
                total = fetch(host, repo, name, dst, prog)
                progress(prog, state="done", done=total, total=total, host=host)
                print("MODEL_OK")
                return 0
            except Exception as e:
                err = "%s: %s" % (host, e)
                time.sleep(3)
    progress(prog, state="failed", error=err)
    print("DOWNLOAD_FAILED " + str(err))
    return 1


if __name__ == "__main__":
    sys.exit(main())
