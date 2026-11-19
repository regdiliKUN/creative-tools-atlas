#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 逐笔作画 · 笔触规划器（第十二轮；第十九轮精度版）

把一张参考图（通常是文生图的产物）拆成「像人一样分层落笔」的笔触计划，
供 Krita 插件 atlas_painter 逐笔回放。只依赖 numpy + Pillow。

分层（与人类绘画顺序一致）：
  1. 线稿   —— 沿明暗边缘的细线，带起笔/收笔压力
  2. 底色   —— 大笔刷铺大色块
  3. 明暗   —— 中笔刷塑造体积
  4. 细节   —— 小笔刷补细节
  5. 收边   —— 最细笔刷提亮高光、收紧轮廓
第十九轮精度版（用户反馈"很多地方都不清楚"，按误差 / 清晰度 / 边缘吻合度量化调参）：
  - 笔刷从 24px 一直细到 1px，误差门槛降低，取消每层笔数上限；
  - 细笔只落在有细节的地方，但前面大笔留下的大块错色无论如何都重画；
  - 颜色取落笔点周围的中位数（单个最偏像素会被点成脏点）；
  - 落笔前看一眼当前画面，已被本层前面的长笔画准就跳过（省约四成笔数）；
  - 最后一层「勾线」：沿清晰边缘描 1.2px 细线，颜色取边缘暗侧的真实颜色（发丝、伞骨、五官轮廓）；
  - 起稿线画完后隐藏（hide_after），不再用灰线压在成品上。
  同一张参考图（1024²）：误差 13.3 → 7.5，清晰度 4.6 → 7.1（参考 11.6），边缘吻合 0.27 → 0.53；
  笔数约 8 万（原 1.15 万）。
笔触算法：Hertzmann 1998 "Painterly Rendering with Curved Brush Strokes of
Multiple Sizes" 的简化版——每层只在"当前画面与参考差异大"的地方落笔，
笔触沿等照度线（垂直于梯度）弯曲延伸，颜色偏离过大即收笔。

用法:
  python stroke_planner.py <参考图> <输出.json> [--size 1024] [--preview 预览.png] [--seed 7]
"""
import argparse, json, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# (层名, 笔刷半径占画布短边的比例, 误差阈值, 最大笔触长度(以半径计), 笔触上限)
import os
_P = json.loads(os.environ.get("SP_PARAMS", "null") or "null")
# (层名, 笔刷半径(像素@1024), 误差阈值, 最大笔触长度(以半径计), 笔触上限, 细节门槛 0..1)
# 第十九轮：两档精度。fine = 精细（约 10 万笔，真机约 38 分钟）；fast = 快速（约 2.5 万笔，约 10 分钟）。
PRESETS = {
    "fine": {
        "layers": [
            ("底色", 24, 18.0, 10, 10 ** 9, 0.0),
            ("明暗", 12, 14.0, 10, 10 ** 9, 0.0),
            ("细节", 6, 12.0, 8, 10 ** 9, 0.05),
            ("收边", 3, 10.0, 8, 10 ** 9, 0.12),
            ("精修", 1.5, 12.0, 6, 10 ** 9, 0.30),
            ("点睛", 1.0, 14.0, 4, 15000, 0.45),
        ],
        "contour": dict(pct=86.0, width=1.2, max_lines=12000),
        "sketch_max": 700,
    },
    # 快速档：3px 收边层限 9000 笔（按误差大小优先），把省下的笔数给性价比最高的勾线。
    # 两张参考图实测：约 2.4～2.7 万笔、预计 9～10 分钟；误差约 10.4（精细档约 7），边缘吻合约 0.35～0.42。
    "fast": {
        "layers": [
            ("底色", 24, 18.0, 10, 10 ** 9, 0.0),
            ("明暗", 12, 14.0, 10, 10 ** 9, 0.0),
            ("细节", 6, 13.0, 8, 10 ** 9, 0.08),
            ("收边", 3, 12.0, 8, 9000, 0.15),
        ],
        "contour": dict(pct=85.0, width=1.2, max_lines=9000),
        "sketch_max": 250,
    },
}
if _P and "layers" in _P:
    PRESETS["fine"]["layers"] = _P["layers"]
HARD_BRUSH_MAX_R = 3.0      # 半径 ≤ 3px 的细笔用硬边圆笔（Krita 默认软笔会把细节画柔）
BLUR_K = _P["blur_k"] if _P else 0.4
BIG_K = (_P or {}).get("big_k", 2.0)
PRESETS["fine"]["contour"].update((_P or {}).get("contour_params", {}))
SKETCH_MIN_LEN = 6        # 线稿最短点数


def _lum(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def _sobel(g):
    p = np.pad(g, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return gx, gy


def _blur(img, r):
    return np.asarray(img.filter(ImageFilter.GaussianBlur(max(0.5, r))), dtype=np.float32)


# ---------------------------------------------------------------- 线稿
def plan_sketch(img, rng, sketch_max=700):
    """从模糊亮度图的强边缘抽取折线：非极大抑制 → 贪心串联。"""
    a = _blur(img, 1.6)
    g = _lum(a)
    gx, gy = _sobel(g)
    mag = np.hypot(gx, gy)
    h, w = g.shape
    # 非极大抑制（4 方向量化）
    ang = (np.rad2deg(np.arctan2(gy, gx)) + 180) % 180
    nms = np.zeros_like(mag)
    p = np.pad(mag, 1, mode="constant")
    c = p[1:-1, 1:-1]
    q = [(p[1:-1, 2:], p[1:-1, :-2]), (p[:-2, 2:], p[2:, :-2]), (p[:-2, 1:-1], p[2:, 1:-1]), (p[:-2, :-2], p[2:, 2:])]
    bins = ((ang + 22.5) // 45).astype(int) % 4
    for b in range(4):
        m = (bins == b) & (c >= q[b][0]) & (c >= q[b][1])
        nms[m] = c[m]
    thr = np.percentile(nms[nms > 0], 88) if (nms > 0).any() else 1e9
    edge = nms > thr
    used = np.zeros_like(edge)
    ys, xs = np.nonzero(edge)
    order = np.argsort(-mag[ys, xs])          # 先串最强的边
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    lines = []
    for i in order:
        y, x = int(ys[i]), int(xs[i])
        if used[y, x]:
            continue
        pts = [(x, y)]
        used[y, x] = True
        for _ in range(400):                   # 单向贪心延伸
            nxt = None
            for dy, dx in nb:
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and edge[yy, xx] and not used[yy, xx]:
                    nxt = (xx, yy); break
            if not nxt:
                break
            x, y = nxt
            used[y, x] = True
            pts.append(nxt)
        if len(pts) >= SKETCH_MIN_LEN:
            pts = pts[::3] + ([pts[-1]] if (len(pts) - 1) % 3 else [])   # 抽稀
            n = len(pts)
            # 人类线条：两头轻、中间重
            pr = [round(0.25 + 0.75 * math.sin(math.pi * k / max(1, n - 1)), 2) for k in range(n)]
            lines.append({"c": [40, 36, 44], "w": 2.2, "pts": pts, "p": pr})
        if len(lines) >= sketch_max:
            break
    return lines


# ---------------------------------------------------------------- 勾线（第十九轮精度版）
def plan_contours(img, canvas, rng, sigma=0.8, pct=80.0, min_len=4, max_lines=12000, width=1.6):
    """沿清晰边缘描细线，颜色取边缘较暗一侧的真实颜色（不是统一灰色）。
    一条线能一笔画出几十个像素的发丝、伞骨、五官轮廓，比用小点铺高效得多。画进 canvas。"""
    a = _blur(img, sigma)
    ref = np.asarray(img, dtype=np.float32)
    g = _lum(a)
    gx, gy = _sobel(g)
    mag = np.hypot(gx, gy)
    h, w = g.shape
    ang = (np.rad2deg(np.arctan2(gy, gx)) + 180) % 180
    nms = np.zeros_like(mag)
    p = np.pad(mag, 1, mode="constant")
    c = p[1:-1, 1:-1]
    q = [(p[1:-1, 2:], p[1:-1, :-2]), (p[:-2, 2:], p[2:, :-2]), (p[:-2, 1:-1], p[2:, 1:-1]), (p[:-2, :-2], p[2:, 2:])]
    bins = ((ang + 22.5) // 45).astype(int) % 4
    for b in range(4):
        m = (bins == b) & (c >= q[b][0]) & (c >= q[b][1])
        nms[m] = c[m]
    thr = np.percentile(nms[nms > 0], pct) if (nms > 0).any() else 1e9
    edge = nms > thr
    used = np.zeros_like(edge)
    ys, xs = np.nonzero(edge)
    order = np.argsort(-mag[ys, xs])
    nb = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
    nx_, ny_ = gx / (mag + 1e-6), gy / (mag + 1e-6)
    lines, draw = [], ImageDraw.Draw(canvas)

    def dark_col(x, y):
        # 沿梯度方向两侧各取 1.5px，取较暗的一侧——线条是边缘暗的那一边
        ox, oy = nx_[y, x] * 1.5, ny_[y, x] * 1.5
        c1 = ref[min(h - 1, max(0, int(round(y + oy)))), min(w - 1, max(0, int(round(x + ox))))]
        c2 = ref[min(h - 1, max(0, int(round(y - oy)))), min(w - 1, max(0, int(round(x - ox))))]
        return c1 if _lum(c1) < _lum(c2) else c2

    for i in order:
        y, x = int(ys[i]), int(xs[i])
        if used[y, x]:
            continue
        pts = [(x, y)]
        used[y, x] = True
        for _ in range(600):
            nxt = None
            for dy, dx in nb:
                yy, xx = y + dy, x + dx
                if 0 <= yy < h and 0 <= xx < w and edge[yy, xx] and not used[yy, xx]:
                    nxt = (xx, yy); break
            if not nxt:
                break
            x, y = nxt
            used[y, x] = True
            pts.append(nxt)
        if len(pts) < min_len:
            continue
        # 一条线颜色变化大时切段，每段用自己的颜色
        cols = [dark_col(px, py) for px, py in pts]
        seg = [0]
        for k in range(1, len(pts)):
            if np.abs(cols[k] - cols[seg[0]]).sum() > 60 or k - seg[0] >= 40:
                seg.append(k)
        seg.append(len(pts))
        for a0, a1 in zip(seg[:-1], seg[1:]):
            sp = pts[a0:a1 + 1] if a1 < len(pts) else pts[a0:a1]
            if len(sp) < 2:
                continue
            col = np.median(np.array(cols[a0:a1]), axis=0)
            sp = sp[::2] + ([sp[-1]] if (len(sp) - 1) % 2 else [])
            n = len(sp)
            pr = [round(0.55 + 0.45 * math.sin(math.pi * k / max(1, n - 1)), 2) for k in range(n)]
            s = {"c": [int(v) for v in np.clip(col, 0, 255)], "w": width, "pts": sp, "p": pr}
            draw.line([tuple(q_) for q_ in sp], fill=tuple(s["c"]), width=max(1, int(round(width))), joint="curve")
            lines.append(s)
        if len(lines) >= max_lines:
            break
    return lines


# ---------------------------------------------------------------- 色彩层
def _render_stroke(draw, s):
    r = s["w"] / 2
    col = tuple(s["c"])
    pts = s["pts"]
    if len(pts) == 1:
        x, y = pts[0]; draw.ellipse([x - r, y - r, x + r, y + r], fill=col); return
    draw.line([tuple(p) for p in pts], fill=col, width=max(1, int(round(s["w"]))), joint="curve")
    for x, y in (pts[0], pts[-1]):
        draw.ellipse([x - r, y - r, x + r, y + r], fill=col)


def _detail_map(img):
    """细节强度：清晰原图的局部梯度（3px 平滑后），0..1。平坦区域不需要细笔。"""
    g = _lum(np.asarray(img, dtype=np.float32))
    gx, gy = _sobel(g)
    m = np.hypot(gx, gy)
    m = np.asarray(Image.fromarray(np.clip(m, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(3)), dtype=np.float32)
    return m / (np.percentile(m, 99) + 1e-6)


def plan_paint_layer(ref_img, canvas, radius, thresh, max_len, cap, rng, detail=None, dmin=0.0):
    """在 canvas（PIL RGB，模拟当前画面）上规划一层笔触，并同步画进 canvas。
    第十九轮精度版：细笔只落在有细节的地方（detail >= dmin）；颜色取落笔点周围的中位数，
    不取单个最偏的像素（那会把异常值点成脏点）。"""
    sig = radius * BLUR_K
    ref = _blur(ref_img, sig) if sig >= 0.6 else np.asarray(ref_img, dtype=np.float32)
    g = _lum(ref)
    gx, gy = _sobel(g)
    h, w = g.shape
    cur = np.asarray(canvas, dtype=np.float32)
    diff = np.sqrt(((cur - ref) ** 2).sum(-1))
    step = max(1, int(round(radius)))
    hr = max(1, int(radius * 0.5))
    cands = []
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            cell = diff[y0:y0 + step, x0:x0 + step]
            score = float(cell.mean())
            if score <= thresh:
                continue
            # 细节门槛只筛"小误差"：平坦区域的小色差不值得用细笔；但误差大（前面大笔刷留下的错色块）
            # 不论有没有细节都要重画——否则光滑的脸颊会留下大块棕斑
            if (detail is not None and dmin > 0 and score < thresh * BIG_K
                    and detail[y0:y0 + step, x0:x0 + step].max() < dmin):
                continue
            iy, ix = np.unravel_index(int(cell.argmax()), cell.shape)
            cands.append((x0 + ix, y0 + iy, score))
    cands.sort(key=lambda t: -t[2])            # 差异大的先保留
    cands = cands[:int(cap)]
    rng.shuffle(cands)                         # 打散顺序，避免扫描线感
    strokes, draw = [], ImageDraw.Draw(canvas)
    skip_k = (_P or {}).get("skip_k", 1.0)
    for x, y, _ in cands:
        # 本层前面的长笔触可能已经把这里画对了：落笔前看一眼当前画面，够准就跳过（省掉大量重复笔触）
        if skip_k > 0:
            live = canvas.getpixel((int(x), int(y)))
            if math.sqrt(sum((live[k] - float(ref[y, x, k])) ** 2 for k in range(3))) < thresh * skip_k:
                continue
        win = ref[max(0, y - hr):y + hr + 1, max(0, x - hr):x + hr + 1].reshape(-1, 3)
        col = np.median(win, axis=0)
        pts = [(int(x), int(y))]
        lx, ly = 0.0, 0.0
        cx, cy = float(x), float(y)
        for _ in range(max_len):
            ix, iy = int(cx), int(cy)
            if not (0 <= ix < w and 0 <= iy < h):
                break
            if len(pts) > 1 and np.abs(ref[iy, ix] - col).sum() > np.abs(cur[iy, ix] - ref[iy, ix]).sum():
                break                          # 继续画只会更偏离参考，收笔（Hertzmann 条件）
            ddx, ddy = gx[iy, ix], gy[iy, ix]
            if math.hypot(ddx, ddy) < 1e-3:
                break
            dx, dy = -ddy, ddx                 # 沿等照度线
            if lx * dx + ly * dy < 0:
                dx, dy = -dx, -dy
            dx, dy = 0.6 * dx + 0.4 * lx, 0.6 * dy + 0.4 * ly
            n = math.hypot(dx, dy) or 1.0
            dx, dy = dx / n, dy / n
            cx, cy = cx + radius * dx, cy + radius * dy
            lx, ly = dx, dy
            pts.append((int(round(cx)), int(round(cy))))
        s = {"c": [int(v) for v in np.clip(col, 0, 255)], "w": round(radius * 2, 1), "pts": pts}
        _render_stroke(draw, s)
        strokes.append(s)
    return strokes


def plan(ref_path, size=1024, seed=7, detail="fine"):
    pre = PRESETS.get(detail, PRESETS["fine"])
    rng = random.Random(seed)
    img = Image.open(ref_path).convert("RGB")
    sc = size / max(img.size)
    img = img.resize((max(1, round(img.width * sc)), max(1, round(img.height * sc))), Image.LANCZOS)
    w, h = img.size
    arr = np.asarray(img, dtype=np.float32)
    # 纸色：取四边像素的中位数（文生图多为浅底）
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    paper = [int(v) for v in np.median(border, axis=0)]
    canvas = Image.new("RGB", (w, h), tuple(paper))
    # 起稿线：像画师一样先起稿，画完后隐藏（hide_after），不影响成品精度
    layers = [{"name": "线稿", "kind": "sketch", "opacity": 0.85, "hide_after": True,
               "strokes": plan_sketch(img, rng, pre["sketch_max"])}]
    short = min(w, h)
    dmap = _detail_map(img)       # 注意：别和参数 detail（精度档）重名
    for name, rpx, thr, mlen, cap, dmin in pre["layers"]:
        r = max(1.0, rpx * short / 1024.0)
        layers.append({"name": name, "kind": "paint", "opacity": 1.0,
                       "brush": "hard" if rpx <= HARD_BRUSH_MAX_R else "soft",
                       "strokes": plan_paint_layer(img, canvas, r, thr, mlen, cap, rng, dmap, dmin)})
    if (_P or {}).get("contour", True):
        layers.append({"name": "勾线", "kind": "line", "opacity": 1.0,
                       "brush": "hard", "strokes": plan_contours(img, canvas, rng, **pre["contour"])})
    return {"version": 2, "detail": detail, "width": w, "height": h, "background": paper, "layers": layers}, canvas


def render_preview(job):
    """按 Krita 回放后的最终画面模拟：纸 → 色彩层 → 勾线；起稿线画完会隐藏（hide_after），不进成品。"""
    im = Image.new("RGB", (job["width"], job["height"]), tuple(job["background"]))
    d = ImageDraw.Draw(im)
    for L in job["layers"]:
        if L["kind"] == "paint":
            for s in L["strokes"]:
                _render_stroke(d, s)
    for L in job["layers"]:
        if L["kind"] == "line":
            for s in L["strokes"]:
                d.line([tuple(p) for p in s["pts"]], fill=tuple(s["c"]), width=max(1, int(round(s["w"]))), joint="curve")
    sk = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ds = ImageDraw.Draw(sk)
    for L in job["layers"]:
        if L["kind"] == "sketch" and not L.get("hide_after"):
            a = int(255 * L["opacity"] * 0.55)
            for s in L["strokes"]:
                ds.line([tuple(p) for p in s["pts"]], fill=tuple(s["c"]) + (a,), width=2, joint="curve")
    return Image.alpha_composite(im.convert("RGBA"), sk).convert("RGB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref"); ap.add_argument("out")
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--preview")
    ap.add_argument("--detail", choices=["fine", "fast"], default="fine")
    a = ap.parse_args()
    job, _ = plan(a.ref, a.size, a.seed, a.detail)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, separators=(",", ":"))
    counts = {L["name"]: len(L["strokes"]) for L in job["layers"]}
    print("PLAN_OK %dx%d strokes=%s total=%d" % (job["width"], job["height"], counts, sum(counts.values())))
    if a.preview:
        render_preview(job).save(a.preview)
        print("PREVIEW", a.preview)


if __name__ == "__main__":
    main()
