#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""轻量图像净化（轮10）：白底/纯色背景透明化 + 裁到内容边界 + 输出干净 PNG。

用 ComfyUI 便携版自带的 Pillow，无需 rembg 大模型。
用途：把文生图产出的白底图净化成可喂给图生3D 的干净输入（"脏数据进 3D = 埋雷"）。

用法: python_embeded/python.exe clean_image.py <input.png> <output.png> [tolerance]
"""
import sys
from pathlib import Path


def clean(src, dst, tolerance=18):
    from PIL import Image, ImageChops
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    rgb = im.convert("RGB")
    # 采样四角判断背景色（白底或常见纯色底）
    corners = [rgb.getpixel((0, 0)), rgb.getpixel((w-1, 0)),
               rgb.getpixel((0, h-1)), rgb.getpixel((w-1, h-1))]
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
    # 生成与背景色差 mask：接近背景的像素透明
    px = im.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if abs(r-bg[0]) <= tolerance and abs(g-bg[1]) <= tolerance and abs(b-bg[2]) <= tolerance:
                px[x, y] = (r, g, b, 0)
    # 裁剪到非透明边界，留 2% 边距
    bbox = im.getbbox()
    if bbox:
        pad = max(2, int(min(w, h) * 0.02))
        x0, y0, x1, y1 = bbox
        x0, y0 = max(0, x0-pad), max(0, y0-pad)
        x1, y1 = min(w, x1+pad), min(h, y1+pad)
        im = im.crop((x0, y0, x1, y1))
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst)
    return im.size, bg


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: clean_image.py <in> <out> [tolerance]")
        sys.exit(2)
    tol = int(sys.argv[3]) if len(sys.argv) > 3 else 18
    size, bg = clean(sys.argv[1], sys.argv[2], tol)
    print("CLEANED size=%s bg=%s -> %s" % (size, bg, sys.argv[2]))
