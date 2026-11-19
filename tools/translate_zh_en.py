#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文提示词 → 英文（创作工具星图 第十九轮）。用 ComfyUI 便携版 Python 运行（自带 torch / transformers / sentencepiece）。

SDXL 的文本编码器基本读不懂中文：中文写"森林守卫"会生成一间客厅。这个脚本负责：
  --download [--mirror]   下载本地翻译模型 Helsinki-NLP/opus-mt-zh-en（CC-BY-4.0，约 315MB），
                          断点续传，逐个文件核对字节数；进度写在模型目录 download_progress.json
  --check                 检查模型是否完整，输出 MODEL_OK / MODEL_MISSING
  （无参数）              从 stdin 读 {"texts": [...]}，输出一行 RESULT:{"texts": [...]}（ASCII 转义，避免控制台编码问题）
  --serve                 常驻：模型只加载一次，逐行读 {"texts": [...]}、逐行回 RESULT:{...}
                          （每次都重新加载要 25 秒左右，常驻后每次 1～2 秒）

模型目录：I:/workbuddy/AI-Engine/translate/opus-mt-zh-en（可用环境变量 ATLAS_TRANSLATE_DIR 覆盖）
"""
import json, os, sys, time, urllib.request, urllib.error
from pathlib import Path

REPO = "Helsinki-NLP/opus-mt-zh-en"
MODEL_DIR = Path(os.environ.get("ATLAS_TRANSLATE_DIR", "I:/workbuddy/AI-Engine/translate/opus-mt-zh-en"))
# 官方仓库文件与字节数（2026-11-18 由 HuggingFace API 核实，commit cf10909）
FILES = {
    "config.json": 1394,
    "generation_config.json": 293,
    "tokenizer_config.json": 44,
    "source.spm": 804677,
    "target.spm": 806530,
    "vocab.json": 1617902,
    "pytorch_model.bin": 312087009,
}
HOSTS = ["https://huggingface.co", "https://hf-mirror.com"]


def model_ok():
    return all((MODEL_DIR / n).is_file() and (MODEL_DIR / n).stat().st_size == s for n, s in FILES.items())


def _progress(**kw):
    try:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        tmp = MODEL_DIR / "download_progress.json.tmp"
        tmp.write_text(json.dumps(dict(kw, time=time.strftime("%H:%M:%S")), ensure_ascii=False), encoding="utf-8")
        tmp.replace(MODEL_DIR / "download_progress.json")
    except Exception:
        pass


def _fetch(host, name, size, done_before, total):
    dst = MODEL_DIR / name
    part = MODEL_DIR / (name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if have > size:
        part.unlink(); have = 0
    req = urllib.request.Request("%s/%s/resolve/main/%s" % (host, REPO, name),
                                 headers={"User-Agent": "creator-atlas/2.1", **({"Range": "bytes=%d-" % have} if have else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:      # 服务器不支持续传：从头来
            have = 0
        with open(part, "ab" if have else "wb") as f:
            last = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                have += len(chunk)
                if time.time() - last > 1:
                    last = time.time()
                    _progress(state="downloading", file=name, done=done_before + have, total=total, host=host)
    if part.stat().st_size != size:
        raise IOError("%s 大小不对：%d / %d 字节" % (name, part.stat().st_size, size))
    part.replace(dst)


def download(prefer_mirror=False):
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    total = sum(FILES.values())
    hosts = HOSTS[::-1] if prefer_mirror else HOSTS
    done = 0
    for name, size in FILES.items():
        dst = MODEL_DIR / name
        if dst.is_file() and dst.stat().st_size == size:
            done += size
            continue
        err = None
        for host in hosts:
            for attempt in range(3):
                try:
                    _fetch(host, name, size, done, total)
                    err = None
                    break
                except Exception as e:
                    err = "%s: %s" % (host, e)
                    time.sleep(2)
            if err is None:
                break
        if err:
            _progress(state="failed", file=name, error=err, done=done, total=total)
            print("DOWNLOAD_FAILED " + err)
            return 1
        done += size
        print("OK %s %d" % (name, size), flush=True)
    _progress(state="done", done=total, total=total)
    print("MODEL_OK")
    return 0


_MODEL = {}


def _load():
    if not _MODEL:
        import warnings
        warnings.filterwarnings("ignore")
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        from transformers import MarianMTModel, MarianTokenizer
        _MODEL["tok"] = MarianTokenizer.from_pretrained(str(MODEL_DIR))
        _MODEL["model"] = MarianMTModel.from_pretrained(str(MODEL_DIR))
        _MODEL["model"].eval()
    return _MODEL["tok"], _MODEL["model"]


def _clean(o):
    # 实测：短句译文常带前导 "- "（"- An orange cat with fire"），去掉首尾的标点
    return o.strip().lstrip("-–—•*·:：;,. ").rstrip(".。 ").strip()


def translate(texts):
    import torch
    tok, model = _load()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 16):
            batch = tok(texts[i:i + 16], return_tensors="pt", padding=True, truncation=True, max_length=256)
            gen = model.generate(**batch, max_new_tokens=128, num_beams=4)
            out += tok.batch_decode(gen, skip_special_tokens=True)
    return [_clean(o) for o in out]


def serve():
    if not model_ok():
        print("MODEL_MISSING", flush=True)
        return 2
    _load()
    print("SERVE_READY", flush=True)
    for line in sys.stdin.buffer:
        try:
            data = json.loads(line.decode("utf-8") or "{}")
            texts = [str(t) for t in data.get("texts", [])][:200]
            res = {"texts": translate(texts) if texts else []}
        except Exception as e:
            res = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
        print("RESULT:" + json.dumps(res, ensure_ascii=True), flush=True)
    return 0


def main():
    args = sys.argv[1:]
    if "--download" in args:
        return download("--mirror" in args)
    if "--serve" in args:
        return serve()
    if "--check" in args:
        print("MODEL_OK" if model_ok() else "MODEL_MISSING")
        return 0
    if not model_ok():
        print("MODEL_MISSING")
        return 2
    data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    texts = [str(t) for t in data.get("texts", [])][:200]
    print("RESULT:" + json.dumps({"texts": translate(texts) if texts else []}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
