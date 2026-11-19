#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""创作工具星图 · 自动化执行引擎（automation engine）

职责：把「任务包作业单」翻译成可执行作业，调度 ComfyUI（生图 / 图生3D），
追踪进度，归档产物。被 tool-bridge.py 导入，通过 /api/job/* 端点对外服务。

设计原则：
- 只用标准库（urllib / threading / json），不引入新依赖。
- 作业与进度持久化到 jobs.json，桥重启后可查询历史。
- 人工环节（Krita 手绘 / 审美精修）不尝试自动化，标记 needs_human 并暂停。
- 所有产物路径限制在 OUTPUT_ROOT 内，防路径穿越。
"""
import json
import os
import re
import shutil
import subprocess   # 第十二轮：clean_image 一直在用 subprocess.run 却从未导入（真跑必 NameError）
import threading
import time
import urllib.request
import urllib.error
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMFY_ROOT = Path("I:/workbuddy/AI-Engine/portable/ComfyUI_windows_portable")   # 第二十轮：放在最前面，底模目录等模块级常量都依赖它


# 第十三轮：Krita 官方安装包把 krita.exe 放在 bin\ 下（实测 C:\Program Files\Krita (x64)\bin\krita.exe），
# 之前只查安装根目录，导致「用 Krita 打开」和「AI 逐笔作画」都报"未找到 Krita"。
KRITA_CANDIDATES = (r"C:\Program Files\Krita (x64)\bin\krita.exe",
                    r"C:\Program Files\Krita\bin\krita.exe",
                    r"C:\Program Files\Krita (x64)\krita.exe",
                    r"C:\Program Files\Krita\krita.exe")


def find_krita():
    for p in KRITA_CANDIDATES:
        if Path(p).is_file():
            return Path(p)
    return None


# 第十八轮：Krita「Atlas 工坊」面板——引擎把"要在 Krita 里做的事"写进会话文件，
# 面板每 1.5 秒读一次：Krita 开着就立刻接手，没开就在启动后接手（不依赖命令行参数和环境变量）。
KRITA_SESSION = HERE / "krita_session.json"
PLUGIN_SRC = HERE / "painter" / "pykrita" / "atlas_painter"


def _krita_running():
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq krita.exe", "/NH"],
                             capture_output=True, text=True, timeout=10).stdout
        return "krita.exe" in out.lower()
    except Exception:
        return False


def krita_plugin_state():
    """enabled = 已装且是当前版本且已启用；outdated = 装的是旧版；disabled = 装了没启用；missing = 没装。"""
    appdata, local = os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA")
    if not appdata:
        return "missing"
    dst = Path(appdata) / "krita" / "pykrita" / "atlas_painter"
    if not (dst / "atlas_studio.py").is_file():
        return "missing"
    for name in ("atlas_studio.py", "atlas_painter.py", "__init__.py"):
        src = PLUGIN_SRC / name
        if src.is_file() and (not (dst / name).is_file() or src.read_bytes() != (dst / name).read_bytes()):
            return "outdated"
    rc = Path(local) / "kritarc" if local else None
    if rc and rc.is_file() and "enable_atlas_painter=true" in rc.read_text(encoding="utf-8", errors="ignore"):
        return "enabled"
    return "disabled"


def ensure_krita_plugin():
    """Krita 关闭时安装 / 更新 / 启用面板插件。返回 (是否可用, 说明)。"""
    st = krita_plugin_state()
    if st == "enabled":
        return True, ""
    if _krita_running():
        return False, ("Krita 正在运行，Atlas 面板要在 Krita 关闭时才能%s；这次先直接打开图片，"
                       "下次关掉 Krita 再选方案A 就有面板了" % ("更新" if st == "outdated" else "安装"))
    try:
        r = subprocess.run([sys.executable, str(HERE / "painter" / "install_krita_plugin.py")],
                           capture_output=True, text=True, timeout=60)
        last = (r.stdout.strip().splitlines() or [""])[-1]
    except Exception as e:
        return False, "面板插件安装失败：%s" % e
    if last == "INSTALLED":
        return True, ""
    return False, "面板插件安装失败：" + (r.stderr or r.stdout)[-150:]


# ------------------------------------------------------------ 第十九轮：中文提示词 → 英文
# （真机实测 2026-11-18：中文「古风，汉服，少女，手持油纸伞，站在桃花树下」翻译后生成的图与描述一致。）
# SDXL 的文本编码器读不懂中文（实测中文"森林守卫"生成一间客厅，英文才生成人物）。
# 模板里固定的中文标签用对照表换成准确的绘画术语；用户自由写的中文交给本地翻译模型。
PORTABLE_PY = Path("I:/workbuddy/AI-Engine/portable/ComfyUI_windows_portable/python_embeded/python.exe")
TRANSLATE_DIR = Path(os.environ.get("ATLAS_TRANSLATE_DIR", "I:/workbuddy/AI-Engine/translate/opus-mt-zh-en"))
TRANSLATE_CACHE = HERE / "translate_cache.json"
_CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
GLOSSARY = {
    # 画风选项
    "干净赛璐璐平涂": "clean cel shading, flat colors", "厚涂概念设定": "painterly concept art, impasto",
    "日系插画": "japanese anime illustration", "写实 PBR": "photorealistic, PBR materials",
    "低多边形 / 风格化": "low poly, stylized", "像素风": "pixel art", "水彩 / 手绘": "watercolor, hand-drawn",
    "原创角色": "original character",
    # 提示词模板里的固定标签
    "角色立绘": "character illustration", "完整全身": "full body", "单人": "solo",
    "居中构图": "centered composition", "浅色纯净背景": "plain light background",
    "平光均匀照明": "flat even lighting", "色块分明": "distinct color blocks", "形体清晰": "clear forms",
    "轮廓明确": "clear silhouette", "少碎细节": "few small details", "角色设定图": "character design sheet",
    "干净白底": "clean white background", "高细节": "highly detailed", "清晰线稿": "clean lineart",
    "锐利焦点": "sharp focus", "正面视角": "front view", "比例准确": "accurate proportions",
    "无遮挡": "unobstructed view", "角色三视图设定": "character turnaround sheet",
    "正面/侧面/背面并列": "front view, side view, back view side by side", "同一角色": "same character",
    "尺寸一致": "consistent scale", "顺序固定": "fixed view order", "白色背景": "white background",
    "平光": "flat lighting", "均匀照明": "even lighting", "比例统一": "consistent proportions",
    "无透视变形": "no perspective distortion",
    # 第十九轮补：常用绘画词。通用翻译模型不懂这些（实测"古风女子"→"old woman"、"汉服"→"kimono"），
    # 用逗号分开写成短词时直接查表，保证准确
    "古风": "ancient Chinese style", "国风": "traditional Chinese art style", "汉服": "hanfu, traditional Chinese clothing",
    "仙侠": "xianxia fantasy", "武侠": "wuxia", "剑客": "swordsman", "侠客": "wandering swordsman",
    "少女": "young girl", "少年": "young boy", "女子": "young woman", "男子": "young man", "美女": "beautiful woman",
    "萝莉": "cute little girl", "御姐": "mature elegant woman", "大叔": "middle-aged man", "老人": "elderly person",
    "赛博朋克": "cyberpunk", "蒸汽朋克": "steampunk", "机甲": "mecha", "科幻": "sci-fi", "奇幻": "fantasy",
    "Q版": "chibi", "q版": "chibi", "二次元": "anime style", "萌系": "cute style", "写实": "realistic", "水墨": "ink wash painting",
    "油画": "oil painting", "素描": "pencil sketch", "厚涂": "impasto painting", "赛璐璐": "cel shading",
    "半身像": "upper body portrait", "全身": "full body", "特写": "close-up", "侧脸": "side profile", "背影": "back view",
    "长发": "long hair", "短发": "short hair", "马尾": "ponytail", "白发": "white hair", "黑发": "black hair",
    "金发": "blonde hair", "银发": "silver hair", "红发": "red hair", "微笑": "smiling", "冷酷": "cold expression",
    "樱花": "cherry blossoms", "桃花": "peach blossoms", "竹林": "bamboo forest", "森林": "forest", "雪景": "snowy landscape",
    "城市夜景": "city at night", "星空": "starry sky", "月光": "moonlight", "逆光": "backlighting", "黄昏": "dusk",
    "油纸伞": "oil-paper umbrella", "长剑": "long sword", "法杖": "magic staff", "斗篷": "cloak", "盔甲": "armor",
    "精灵": "elf", "龙": "dragon", "猫": "cat", "狗": "dog", "狐狸": "fox", "九尾狐": "nine-tailed fox",
    # 第二十轮再补：人物 / 动作 / 服饰 / 场景 / 光线 / 构图 / 画风
    "骑士": "knight", "圣骑士": "paladin", "法师": "mage", "魔法师": "wizard", "刺客": "assassin", "弓箭手": "archer",
    "武士": "samurai", "忍者": "ninja", "公主": "princess", "王子": "prince", "女王": "queen", "国王": "king",
    "巫女": "shrine maiden", "修女": "nun", "女仆": "maid", "学生": "student", "机器人": "robot", "天使": "angel",
    "恶魔": "demon", "吸血鬼": "vampire", "猫娘": "catgirl", "兽耳": "animal ears", "狐耳": "fox ears",
    "站立": "standing", "坐着": "sitting", "奔跑": "running", "回眸": "looking back", "挥剑": "swinging a sword",
    "拔剑": "drawing a sword", "施法": "casting a spell", "张开双臂": "arms spread", "双手抱胸": "arms crossed",
    "旗袍": "qipao", "和服": "kimono", "长袍": "long robe", "铠甲": "plate armor", "披风": "cape", "围巾": "scarf",
    "发簪": "hairpin", "耳环": "earrings", "面纱": "veil", "眼镜": "glasses", "帽子": "hat", "斗笠": "bamboo hat",
    "双马尾": "twin tails", "丸子头": "hair bun", "卷发": "curly hair", "蓝发": "blue hair", "粉发": "pink hair",
    "红瞳": "red eyes", "蓝瞳": "blue eyes", "金瞳": "golden eyes", "异色瞳": "heterochromia",
    "古镇": "ancient town", "宫殿": "palace", "城堡": "castle", "神社": "shrine", "寺庙": "temple", "江湖": "jianghu",
    "山水": "mountains and rivers", "云海": "sea of clouds", "瀑布": "waterfall", "湖边": "lakeside", "海边": "seaside",
    "沙漠": "desert", "废墟": "ruins", "雨夜": "rainy night", "下雪": "snowing", "落叶": "falling leaves",
    "火焰": "flames", "闪电": "lightning", "光晕": "halo", "侧光": "side lighting", "柔光": "soft lighting",
    "电影感": "cinematic", "景深": "depth of field", "俯视": "high angle view", "仰视": "low angle view",
    "大头照": "headshot", "远景": "wide shot", "插画": "illustration", "国画": "chinese ink painting",
    "工笔": "gongbi meticulous painting", "漫画": "manga style", "3D 渲染": "3D render", "黏土": "claymation style",
    "剪纸": "paper cut art", "浮世绘": "ukiyo-e",
}
_TR_STATE = {"proc": None}


def translate_state():
    """installed / downloading(进度) / failed / missing"""
    ok = False
    try:
        r = subprocess.run([str(PORTABLE_PY), str(HERE / "translate_zh_en.py"), "--check"],
                           capture_output=True, text=True, timeout=30)
        ok = "MODEL_OK" in r.stdout
    except Exception:
        pass
    prog = {}
    try:
        prog = json.loads((TRANSLATE_DIR / "download_progress.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    running = _TR_STATE["proc"] is not None and _TR_STATE["proc"].poll() is None
    state = "installed" if ok else ("downloading" if running else ("failed" if prog.get("state") == "failed" else "missing"))
    return {"state": state, "done": prog.get("done", 0), "total": prog.get("total", 0),
            "file": prog.get("file", ""), "error": prog.get("error", ""), "size_mb": 315, "license": "CC-BY-4.0"}


def install_translator(mirror=False):
    if _TR_STATE["proc"] is not None and _TR_STATE["proc"].poll() is None:
        return True, "翻译模型正在下载中"
    if not PORTABLE_PY.is_file():
        return False, "找不到 ComfyUI 便携版 Python：" + str(PORTABLE_PY)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    args = [str(PORTABLE_PY), str(HERE / "translate_zh_en.py"), "--download"] + (["--mirror"] if mirror else [])
    _TR_STATE["proc"] = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return True, "开始下载翻译模型（约 315MB）"


def _tr_cache():
    try:
        d = json.loads(TRANSLATE_CACHE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


_TR_PROC = {"p": None, "q": None}
_TR_PROC_LOCK = threading.Lock()


def _tr_serve_call(texts, timeout=180):
    """第十九轮：常驻翻译进程——模型只加载一次（单次调用要 25 秒左右，常驻后 1～2 秒）。"""
    import queue
    with _TR_PROC_LOCK:
        p = _TR_PROC["p"]
        if p is None or p.poll() is not None:
            p = subprocess.Popen([str(PORTABLE_PY), str(HERE / "translate_zh_en.py"), "--serve"],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            q = queue.Queue()

            def pump(out=p.stdout, q=q):
                for raw in out:
                    q.put(raw.decode("utf-8", "replace").strip())
                q.put(None)
            threading.Thread(target=pump, daemon=True).start()
            _TR_PROC.update(p=p, q=q)
        q = _TR_PROC["q"]
        try:
            p.stdin.write((json.dumps({"texts": texts}, ensure_ascii=True) + "\n").encode("utf-8"))
            p.stdin.flush()
            t0 = time.time()
            while time.time() - t0 < timeout:
                line = q.get(timeout=max(1, timeout - (time.time() - t0)))
                if line is None or line == "MODEL_MISSING":
                    break
                if line.startswith("RESULT:"):
                    out = json.loads(line[7:]).get("texts")
                    return out if isinstance(out, list) and len(out) == len(texts) else None
        except Exception:
            pass
        try:            # 出错 / 超时：结束进程，下次重新拉起
            p.kill()
        except Exception:
            pass
        _TR_PROC["p"] = None
        return None


def _tr_model(texts):
    """调用本地模型翻译一批中文片段；模型没装或失败返回 None。"""
    got = _tr_serve_call(texts)
    if got is not None:
        return got
    try:
        r = subprocess.run([str(PORTABLE_PY), str(HERE / "translate_zh_en.py")],
                           input=json.dumps({"texts": texts}, ensure_ascii=False).encode("utf-8"),
                           capture_output=True, timeout=180,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((l for l in r.stdout.decode("utf-8", "replace").splitlines() if l.startswith("RESULT:")), "")
        if not line:
            return None
        out = json.loads(line[7:]).get("texts", [])
        return out if len(out) == len(texts) else None
    except Exception:
        return None


def to_english(text):
    """返回 (英文提示词, 没能翻译的中文片段列表)。不含中文的原样返回。"""
    text = text or ""
    if not _CJK.search(text):
        return text, []
    segs = [x.strip() for x in re.split(r"[，,、。；;：\n]+", text)]
    segs = [x for x in segs if x]
    cache = _tr_cache()
    need = []
    for x in segs:
        if _CJK.search(x) and x not in GLOSSARY and x not in cache and x not in need:
            need.append(x)
    if need:
        got = _tr_model(need)
        if got:
            for k, v in zip(need, got):
                if v and not _CJK.search(v):
                    cache[k] = v
            try:
                with _LOCK:
                    tmp = TRANSLATE_CACHE.with_suffix(".json.tmp")
                    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
                    tmp.replace(TRANSLATE_CACHE)
            except Exception:
                pass
    out, missing = [], []
    for x in segs:
        if not _CJK.search(x):
            out.append(x)
        elif x in GLOSSARY:
            out.append(GLOSSARY[x])
        elif x in cache:
            out.append(cache[x])
        else:
            out.append(x)          # 没法翻译：保留原文，并报告给用户
            missing.append(x)
    return ", ".join(out), missing


# 第二十轮：出图底模。SDXL 基础版不擅长插画 / 动漫角色，可选下载 Animagine XL 4.0 Opt
# （SDXL 官方微调，CreativeML Open RAIL++-M，可商用，6.94GB）。每个底模带推荐参数和训练时的质量标签。
CKPT_DIR = COMFY_ROOT / "ComfyUI" / "models" / "checkpoints"
CKPT_PROFILES = {
    "sd_xl_base_1.0.safetensors": {
        "label": "SDXL 基础版（通用）", "cfg": 7.0, "steps": 25, "sampler": "euler",
        "pos_suffix": "", "neg_suffix": ""},
    "animagine-xl-4.0-opt.safetensors": {
        "label": "Animagine XL 4.0 Opt（插画 / 动漫角色）", "repo": "cagliostrolab/animagine-xl-4.0",
        "file": "animagine-xl-4.0-opt.safetensors", "size_gb": 6.94, "license": "CreativeML Open RAIL++-M（可商用）",
        "cfg": 5.0, "steps": 28, "sampler": "euler_ancestral",
        "pos_suffix": "masterpiece, high score, great score, absurdres",
        "neg_suffix": "worst quality, low score, bad score, average score"},
}
DEFAULT_CKPT = "sd_xl_base_1.0.safetensors"
_CKPT_DL = {}


def _dl_progress(name):
    """下载进度文件放在 outputs/_downloads/（运行时数据，不进交付清单）。"""
    d = OUTPUT_ROOT / "_downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("download_%s.json" % Path(name).stem)


def ckpt_profile(spec):
    """作业要用的底模：选了但还没下载好的，退回 SDXL 基础版。返回 (文件名, 档案)。"""
    name = spec.get("ckpt") if spec.get("ckpt") in CKPT_PROFILES else DEFAULT_CKPT
    if not (CKPT_DIR / name).is_file():
        name = DEFAULT_CKPT
    return name, CKPT_PROFILES[name]


def _dl_live(name):
    """下载是否正在进行：以进度文件为准（最近 30 秒内更新过）。
    工具桥自动更新会换进程，内存里的下载句柄会丢，但下载子进程还在跑——只看句柄会误判成"没在下载"，
    用户再点一次就会两个进程写同一个文件。"""
    try:
        f = _dl_progress(name)
        return (time.time() - f.stat().st_mtime < 30
                and json.loads(f.read_text(encoding="utf-8")).get("state") == "downloading")
    except Exception:
        return False


def ckpt_status():
    out = []
    for name, p in CKPT_PROFILES.items():
        st = {"name": name, "label": p["label"], "installed": (CKPT_DIR / name).is_file(),
              "size_gb": p.get("size_gb"), "license": p.get("license", "")}
        proc = _CKPT_DL.get(name)
        if (proc is not None and proc.poll() is None) or (not st["installed"] and _dl_live(name)):
            st["downloading"] = True
            try:
                st.update({k: v for k, v in json.loads((_dl_progress(name))
                                                        .read_text(encoding="utf-8")).items() if k in ("done", "total", "host")})
            except Exception:
                pass
        elif proc is not None and proc.returncode not in (0, None) and not st["installed"]:
            st["failed"] = True
            try:
                st["error"] = json.loads((_dl_progress(name)).read_text(encoding="utf-8")).get("error", "")
            except Exception:
                pass
        out.append(st)
    return out


def install_ckpt(name):
    p = CKPT_PROFILES.get(name)
    if not p or "repo" not in p:
        return False, "不支持下载这个模型"
    if (CKPT_DIR / name).is_file():
        return True, "已经下载好了"
    proc = _CKPT_DL.get(name)
    if (proc is not None and proc.poll() is None) or _dl_live(name):
        return True, "正在下载中"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    _CKPT_DL[name] = subprocess.Popen(
        [sys.executable, str(HERE / "download_model.py"), p["repo"], p["file"], str(CKPT_DIR / name),
         str(_dl_progress(name))],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    return True, "开始下载 %s（约 %.1f GB）" % (p["label"], p.get("size_gb", 0))


def english_prompts(jid, spec):
    """作业用的正 / 反向英文提示词；记进作业（页面显示"实际发给模型的提示词"）。"""
    # 第十九轮：页面上"英文提示词"框改过的版本优先（通用翻译模型不懂绘画词，让用户能纠正）
    ue_pos, ue_neg = spec.get("prompt_pos_en"), spec.get("prompt_neg_en")
    if isinstance(ue_pos, str) and ue_pos.strip() and not _CJK.search(ue_pos):
        pos, m1 = ue_pos.strip(), []
    else:
        pos, m1 = to_english(spec.get("prompt_pos", ""))
    if isinstance(ue_neg, str) and ue_neg.strip() and not _CJK.search(ue_neg):
        neg, m2 = ue_neg.strip(), []
    else:
        neg, m2 = to_english(spec.get("prompt_neg", ""))
    _, prof = ckpt_profile(spec)        # 第二十轮：底模训练时用的质量标签
    if prof.get("pos_suffix") and prof["pos_suffix"] not in pos:
        pos = pos.rstrip(" ,") + ", " + prof["pos_suffix"]
    if prof.get("neg_suffix") and prof["neg_suffix"] not in neg:
        neg = neg.rstrip(" ,") + ", " + prof["neg_suffix"]
    with _LOCK:
        j = _JOBS.get(jid)
        if j is not None:
            j["prompt_en"] = {"pos": pos, "neg": neg, "untranslated": m1 + m2,
                              "source": {"pos": spec.get("prompt_pos", ""), "neg": spec.get("prompt_neg", "")}}
    return pos, neg, m1 + m2


def write_krita_session(data):
    data = dict(data, id=uuid.uuid4().hex[:12], created=time.strftime("%Y-%m-%d %H:%M:%S"),
                bridge="http://127.0.0.1:7843", comfy=COMFY_URL)
    tmp = KRITA_SESSION.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(KRITA_SESSION)
    return data["id"]


def kra_to_png(kra, png):
    """.kra 是 zip，里面自带全尺寸合成图 mergedimage.png——不用开 Krita 也能拿到"拼合后"的结果。"""
    import zipfile
    try:
        with zipfile.ZipFile(str(kra)) as z:
            data = z.read("mergedimage.png")
        tmp = Path(str(png) + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(png)
        return True
    except Exception:
        return False
PACKAGE = HERE.parent
OUTPUT_ROOT = PACKAGE / "outputs"
JOBS_FILE = HERE / "jobs.json"
COMFY_URL = os.environ.get("ATLAS_COMFY_URL", "http://127.0.0.1:8188")

# 轮1：用可重入锁——_save_jobs() 内部也要拿锁，而 create_job/_set_step 等
# 常在已持锁的状态下调用它。普通 Lock 会自锁死锁（faulthandler 实测抓到）。
_LOCK = threading.RLock()
_JOBS = {}          # job_id -> job dict（内存镜像，持久化到 jobs.json）
MAX_WORKERS = 2   # 第十二轮：并发 worker 数——单 worker 会被一个长作业（图生3D）阻塞全部后续作业
MAX_JOBS = 100    # 轮15：最多保留 100 个作业记录，防止 jobs.json 无限增长拖慢加载
_WORKERS = []
_WORKER = None
_STOP = threading.Event()
# 轮3：按作业停止信号——全局 _STOP 停止后会被 _ensure_worker() 的 clear() 复活，
# 且无法只停一个作业。每个作业有独立停止标志。
_JOB_STOPS = {}     # jid -> threading.Event
_JOB_STOPS_LOCK = threading.Lock()

# 可自动化的步骤类型 → 执行器
AUTO_KINDS = {"text_to_image", "image_to_3d", "clean_image", "krita_paint",
              "ai_upscale", "remove_bg",     # 第十三轮：方案B（AI 自动精修）的两步
              "input_image", "variants", "note"}   # 第二十轮：输入 / 一致性变体 / 说明
UPLOAD_EXT = {".png", ".jpg", ".jpeg", ".webp", ".glb", ".gltf", ".obj", ".stl", ".fbx", ".ply"}
UPLOAD_MAX = 200 * 1024 * 1024
# 第十三轮：半自动步骤——引擎先做准备动作（如复制产物并用 Krita 打开），再暂停等人改完
ASSIST_KINDS = {"krita_edit"}
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# 第十三轮：接手时可选的三套后续方案（页面上的 A/B/C 三个按钮）
PLANS = {
    "krita_edit": {"title": "方案A · 我在 Krita 里改", "steps": [
        {"kind": "krita_edit", "label": "[方案A] 在 Krita 里修改",
         "hint": "引擎复制一份上一步的图并用 Krita 打开；你改完按 Ctrl+S 保存，回到这里点「我改完了」。"}]},
    "ai_refine": {"title": "方案B · AI 自动精修", "steps": [
        {"kind": "ai_upscale", "label": "[方案B] AI 高清重绘（放大 1.5 倍）",
         "hint": "ComfyUI 把图放大 1.5 倍后低强度重绘（denoise 0.35），补细节、保构图。"},
        {"kind": "remove_bg", "label": "[方案B] AI 去背景（BiRefNet）",
         "hint": "BiRefNet 抠出主体，输出透明底 PNG。"}]},
    "ai_paint": {"title": "方案C · AI 在 Krita 里逐笔画", "steps": [
        {"kind": "krita_paint", "label": "[方案C] AI 在 Krita 里逐笔作画",
         "hint": "以上一步的图为参考，AI 打开 Krita 用真实笔刷分层一笔一笔画，保存分层 .kra 和 PNG。"}]},
}
MAX_STEPS = 40
# 必须人工的步骤类型（暂停并交接）
# 第十二轮：补 "human"——前端把未识别的步骤一律编成 kind="human"，漏掉它会被误报为"未知步骤类型"
HUMAN_KINDS = {"hand_draw", "aesthetic_refine", "rigging", "facecap", "painting", "human"}


# --------------------------------------------------------------- 持久化
def _load_jobs():
    global _JOBS
    try:
        d = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            _JOBS = d
    except Exception:
        _JOBS = {}


_last_save_ts = 0.0
_save_dirty = False


def _save_jobs(force=False):
    """轮11：节流写盘——进度轮询每秒都调 _update/_set_step，若每次全量写
    jobs.json（可能几十 KB），一次生图要写几十次。改为脏标记 + 最多 2 秒落盘一次。
    force=True 用于关键状态（创建/结束），立即落盘。
    """
    global _last_save_ts, _save_dirty
    with _LOCK:
        _save_dirty = True
        now = time.time()
        if not force and (now - _last_save_ts) < 2.0:
            return
        _flush_jobs_locked()
        _last_save_ts = now
        _save_dirty = False


def _flush_jobs_locked():
    """在已持锁状态下真正写盘（轮17 会改成原子写）。"""
    try:
        tmp = JOBS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_JOBS, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(JOBS_FILE)   # 轮17：原子替换，防写到一半崩溃损坏
    except Exception:
        pass


def get_job(jid):
    # 轮2：深拷贝——dict() 是浅拷贝，steps/spec/artifacts 等嵌套容器与内部共享引用。
    # 对外返回（HTTP/前端）后任何改动都会污染引擎内部状态。
    import copy
    with _LOCK:
        j = _JOBS.get(jid)
        return copy.deepcopy(j) if j else None


def list_jobs():
    import copy
    with _LOCK:
        return [copy.deepcopy(j) for j in _JOBS.values()]


# --------------------------------------------------------------- ComfyUI 客户端
_COMFY_CACHE = {"ts": 0.0, "data": None}
_COMFY_TTL = 10.0   # 秒


def comfy_available(force=False):
    """探测 ComfyUI 是否在线。返回 (bool, info)。

    轮13：TTL 缓存——生图/图生3D/探测都会调它，每次发 HTTP 浪费；
    10 秒内复用上次结果。作业执行前用 force=True 确保实时性。
    """
    now = time.time()
    if not force and _COMFY_CACHE["data"] is not None and (now - _COMFY_CACHE["ts"]) < _COMFY_TTL:
        return _COMFY_CACHE["data"]
    try:
        r = urllib.request.urlopen(COMFY_URL + "/system_stats", timeout=3)
        d = json.loads(r.read().decode("utf-8"))
        result = (True, d)
    except Exception as e:
        result = (False, {"error": str(e)[:120]})
    _COMFY_CACHE["ts"] = now
    _COMFY_CACHE["data"] = result
    return result


def _comfy_cancel(prompt_id):
    """第二十轮：作业被停止时，ComfyUI 那边的任务也要停——否则引擎停了，显卡还在白算。
    排队中的直接删掉；正在算的发中断（新版 ComfyUI 支持按 prompt_id 中断，旧版会中断当前任务）。"""
    for path, payload in (("/queue", {"delete": [prompt_id]}), ("/interrupt", {"prompt_id": prompt_id})):
        try:
            _comfy_post(path, payload)
        except Exception:
            pass


def _comfy_post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        COMFY_URL + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _comfy_get(path, timeout=10):
    with urllib.request.urlopen(COMFY_URL + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def adapt_workflow_models(workflow):
    """把官方工作流里的模型名对齐到本机实际文件名。

    第十二轮：官方 Pixal3D 所需模型已按原名补齐（pixal3d_bf16 / dino_v3_L_naf_fp32 /
    moge_2_vitl_normal_fp16 / birefnet），不再用 trellis_2 / dino_v3_vit_l 顶替——
    那是不同模型，顶替能提交但结果不对。只保留一处纯命名差异：UI 工作流里 MoGe
    是连字符旧名。（另：旧版遍历的键 clip_vision_name 并不存在，CLIPVisionLoader
    的真实参数是 clip_name，所以旧 DINO 映射其实从未生效。）
    """
    mapping = {
        "moge-2-vitl-normal_fp16.safetensors": "moge_2_vitl_normal_fp16.safetensors",
    }
    import copy
    wf = copy.deepcopy(workflow)
    for node in wf.values():
        inputs = node.get("inputs", {})
        for key in ("ckpt_name", "unet_name", "clip_name", "vae_name", "model_name", "bg_removal_name"):
            if key in inputs and isinstance(inputs[key], str) and inputs[key] in mapping:
                inputs[key] = mapping[inputs[key]]
    return wf


def bg_model_missing(workflow):
    """第十二轮：查询 ComfyUI 实时 schema，判断工作流要的背景移除模型是否已安装。
    查询失败时按"未缺失"处理（不旁路），让 ComfyUI 自己报出准确错误。"""
    wanted = {n["inputs"].get("bg_removal_name") for n in workflow.values()
              if n.get("class_type") == "LoadBackgroundRemovalModel"} - {None}
    if not wanted:
        return False
    try:
        info = _comfy_get("/object_info/LoadBackgroundRemovalModel", timeout=10)
        spec = info["LoadBackgroundRemovalModel"]["input"]["required"]["bg_removal_name"]
        opts = spec[0] if isinstance(spec[0], list) else spec[1].get("options", [])
        return not wanted.issubset(set(opts))
    except Exception:
        return False


def bypass_bg_removal(workflow):
    """轮9：把 RemoveBackground 旁路，让下游 Switch 直接取原始 LoadImage 输出。
    第十二轮：不再无条件调用——只有 bg_model_missing() 为真（本机没装 birefnet）时才用；
    装了就走官方流程，输入图自带地面/背景时效果明显更好。
    """
    import copy
    wf = copy.deepcopy(workflow)
    load_img = next((nid for nid, n in wf.items() if n.get("class_type") == "LoadImage"), None)
    if not load_img:
        return wf
    for nid, n in wf.items():
        if n.get("class_type") == "ComfySwitchNode":
            ins = n.get("inputs", {})
            if isinstance(ins.get("on_true"), list) and ins["on_true"][0] in {
                k for k, v in wf.items() if v.get("class_type") == "RemoveBackground"}:
                ins["on_true"] = [load_img, 0]
    return wf


_COMFY_START = {"t": 0.0}
_COMFY_START_LOCK = threading.Lock()


def _launch_comfy():
    """启动 ComfyUI 便携版：最小化、不抢焦点。--disable-dynamic-vram / --cache-classic 的原因见 start-all.bat。"""
    py = COMFY_ROOT / "python_embeded" / "python.exe"
    _COMFY_START["t"] = time.time()
    kw = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7                       # SW_SHOWMINNOACTIVE：最小化、不抢焦点
        kw = dict(startupinfo=si, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    subprocess.Popen([str(py), "-s", "ComfyUI\\main.py", "--windows-standalone-build", "--disable-auto-launch",
                      "--disable-dynamic-vram", "--cache-classic"], cwd=str(COMFY_ROOT), **kw)


def restart_comfy():
    """第二十轮：重启 ComfyUI（释放显存 / 换启动参数）。只结束便携版自己的 ComfyUI 进程；有作业在跑时拒绝。"""
    with _LOCK:
        busy = [j["id"] for j in _JOBS.values() if j.get("status") in ("queued", "running")]
    if busy:
        return False, "有作业正在执行（%s），等它结束或先停止再重启" % busy[0]
    if not (COMFY_ROOT / "python_embeded" / "python.exe").is_file():
        return False, "找不到 ComfyUI 便携版"
    killed = ""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { "
              "$_.CommandLine -like '*ComfyUI\\main.py*' -and $_.ExecutablePath -like '*python_embeded*' } | "
              "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        killed = " ".join(r.stdout.split())
    t0 = time.time()
    while time.time() - t0 < 20 and comfy_available(force=True)[0]:
        time.sleep(1)
    _launch_comfy()
    return True, "已重启 ComfyUI（结束的进程：%s），约 30 秒后就绪" % (killed or "无")


def ensure_comfy(jid, label, wait=900):
    """第二十轮：ComfyUI 没开就自动启动并等它就绪（实测：关掉再开后首次加载模型要几分钟）。
    返回 (是否就绪, info)。等待期间每 3 秒更新一次作业进度文字，可被"停止"打断。"""
    ok, info = comfy_available(force=True)
    if ok:
        return True, info
    py = COMFY_ROOT / "python_embeded" / "python.exe"
    if not py.is_file():
        return False, {"error": "ComfyUI 没有运行，也找不到便携版：" + str(py)}
    with _COMFY_START_LOCK:
        if time.time() - _COMFY_START["t"] > 180:      # 3 分钟内不重复拉起（并发作业 / 刚启动还没就绪）
            _launch_comfy()
    t0 = time.time()
    while time.time() - t0 < wait:
        if _job_stopped(jid):
            return False, {"error": "作业被停止"}
        _update(jid, current="%s · ComfyUI 没在运行，已自动启动，等它就绪（%ds，首次加载模型可能要几分钟）"
                % (label, int(time.time() - t0)))
        time.sleep(3)
        ok, info = comfy_available(force=True)
        if ok:
            return True, info
    return False, {"error": "自动启动 ComfyUI 后等了 %d 秒仍未就绪" % wait}


def _share_ckpt_node(workflow):
    """第二十轮：所有工作流里的底模加载节点统一叫 "ckpt"。
    实测：出主图（节点 "1"）和出变体（节点 "3"）编号不同，ComfyUI 的缓存按节点编号认，
    认不出是同一个底模，又载一份；旧的还占着显存，24GB 只剩 2.9GB，变体卡在 VAE 那步好几分钟。
    （试过先让 ComfyUI 释放旧模型——但从 I 盘重读 7GB 底模要两分多钟，更慢。）
    统一编号后，同一个底模直接复用，不重载也不重复占显存。"""
    ids = [k for k, n in workflow.items()
           if isinstance(n, dict) and n.get("class_type") == "CheckpointLoaderSimple"]
    if len(ids) != 1 or ids[0] == "ckpt" or "ckpt" in workflow:
        return workflow
    old = ids[0]
    out = {}
    for k, n in workflow.items():
        n = dict(n)
        n["inputs"] = {ik: (["ckpt", v[1]] if isinstance(v, list) and len(v) == 2 and v[0] == old else v)
                       for ik, v in n.get("inputs", {}).items()}
        out["ckpt" if k == old else k] = n
    return out


def submit_prompt(workflow, client_id=None):
    """提交 ComfyUI API 格式工作流。返回 prompt_id。

    轮20：client_id 按作业唯一（传入 jid）——硬编码会让多作业共享标识，
    ComfyUI 无法区分来源，并发时进度/事件可能串台。
    """
    workflow = _share_ckpt_node(workflow)
    res = _comfy_post("/prompt", {"prompt": workflow,
                                  "client_id": client_id or ("atlas-" + uuid.uuid4().hex[:8])})
    if "prompt_id" not in res:
        raise RuntimeError("ComfyUI 未返回 prompt_id: " + str(res)[:200])
    # 第十二轮：ComfyUI 对"部分输出校验失败"仍返回 200 + prompt_id，只在 node_errors 里注明，
    # 并把受影响的输出丢弃（日志 "Output will be ignored"）——表现为很快"跑完"却没有产物。
    # 这里直接报出节点与缺失项，不让它静默失败。
    errs = res.get("node_errors") or {}
    if errs:
        parts = []
        for nid, e in list(errs.items())[:5]:
            msgs = ["%s(%s)" % (x.get("message", ""), x.get("details", "")) for x in e.get("errors", [])[:3]]
            parts.append("%s#%s: %s" % (e.get("class_type", "?"), nid, "; ".join(msgs)))
        raise RuntimeError("ComfyUI 工作流校验失败，部分输出会被丢弃：" + " | ".join(parts))
    return res["prompt_id"]


def comfy_progress(prompt_id):
    """轮14：从 ComfyUI /progress 取真实采样进度，返回 0..100 或 None。"""
    try:
        d = _comfy_get("/progress", timeout=2)
        # ComfyUI /progress 可能返回单个字典或按 prompt_id 索引的字典
        node = d.get(prompt_id, d) if isinstance(d, dict) else None
        if not isinstance(node, dict):
            return None
        val, mx = node.get("value"), node.get("max")
        if isinstance(val, (int, float)) and isinstance(mx, (int, float)) and mx > 0:
            return min(100, int(val / mx * 100))
        # 有些版本返回 node_progress
        np = node.get("node_progress") or {}
        if isinstance(np, dict) and np:
            vals = [v for v in np.values() if isinstance(v, dict)]
            if vals:
                v, m = vals[0].get("value"), vals[0].get("max")
                if isinstance(v, (int, float)) and isinstance(m, (int, float)) and m > 0:
                    return min(100, int(v / m * 100))
    except Exception:
        pass
    return None


def wait_prompt(prompt_id, timeout=900, poll=1.5, on_tick=None, jid=None):
    """轮询等待工作流完成。返回 history 节点。

    轮4：连续失败阈值——ComfyUI 崩溃时不应空等满 15 分钟。
    连续 max_errors 次请求异常即判定服务不可用，立即中止并给出清晰错误。
    """
    max_errors = 5          # 连续 5 次失败即中止（轮4：配合 2s 探测超时，约 5 秒内判定）
    consecutive_errors = 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _STOP.is_set():
            _comfy_cancel(prompt_id)
            raise RuntimeError("作业被停止")
        if jid and _job_stopped(jid):
            _comfy_cancel(prompt_id)
            raise RuntimeError("作业被停止（per-job）")
        try:
            hist = _comfy_get("/history/" + prompt_id, timeout=2)
            consecutive_errors = 0      # 成功一次就清零
            node = hist.get(prompt_id)
            if node and node.get("status", {}).get("completed"):
                return node
            if node and node.get("status", {}).get("status_str") == "error":
                raise RuntimeError("ComfyUI 执行失败: " + json.dumps(node.get("status"), ensure_ascii=False)[:300])
        except urllib.error.HTTPError:
            consecutive_errors += 1
        except RuntimeError:
            raise
        except Exception:
            consecutive_errors += 1
        if consecutive_errors >= max_errors:
            raise RuntimeError("ComfyUI 连续 %d 次无响应，判定服务不可用（已中止，未空等至超时）" % max_errors)
        if on_tick:
            real = comfy_progress(prompt_id)   # 轮14：优先真实采样进度
            on_tick(time.time() - t0, timeout, real)
        time.sleep(poll)
    raise TimeoutError("等待 ComfyUI 超时（%ds）" % timeout)


# --------------------------------------------------------------- 工作流模板
def build_txt2img_workflow(prompt_pos, prompt_neg, steps=25, cfg=7.0,
                           width=1024, height=1024, seed=None, ckpt="sd_xl_base_1.0.safetensors", sampler="euler"):
    """构造 SDXL 文生图的 ComfyUI API 工作流（标准 5 节点链）。"""
    import random
    # 轮16：参数边界钳制——恶意/畸形作业单若传 width=99999 会 OOM 崩 ComfyUI，
    # steps=-5 / cfg=0 会产生难懂的下游错误。在构造工作流前统一钳制到安全范围。
    def clamp(v, lo, hi, default):
        try:
            v = float(v)
            return int(max(lo, min(hi, v))) if v == v else default  # NaN 回退
        except (ValueError, TypeError):
            return default
    width = clamp(width, 256, 2048, 1024)
    height = clamp(height, 256, 2048, 1024)
    steps = clamp(steps, 1, 100, 25)
    cfg = max(1.0, min(30.0, float(cfg) if str(cfg).replace(".", "", 1).isdigit() else 7.0))
    # 轮5：seed 归一化——前端 JSON 常把数字传成字符串 "42"，
    # 原 isinstance(int) 判定会把它丢弃并随机生成，破坏同作业单的幂等性。
    try:
        if isinstance(seed, bool):        # bool 是 int 子类，须排除
            raise ValueError
        seed = int(seed) if seed is not None and str(seed).strip() != "" else None
    except (ValueError, TypeError):
        seed = None
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_pos, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt_neg, "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": sampler if sampler in ("euler", "euler_ancestral", "dpmpp_2m") else "euler",
                         "scheduler": "normal",
                         "denoise": 1.0, "model": ["1", 0],
                         "positive": ["2", 0], "negative": ["3", 0],
                         "latent_image": ["4", 0]}},
        "6": {"class_type": "VAEDecode",
              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",
              "inputs": {"images": ["6", 0],
                         "filename_prefix": "atlas/" + time.strftime("%Y%m%d_%H%M%S")}},
    }


def build_img2img_workflow(image_name, prompt_pos, prompt_neg, scale=1.5, denoise=0.35,
                           steps=20, cfg=6.0, seed=None, ckpt="sd_xl_base_1.0.safetensors"):
    """第十三轮：方案B 第一步——放大后低强度重绘（img2img），补细节、保构图。
    节点均为 ComfyUI 内置；已在本机 0.45.0 上实际提交验证。"""
    import random
    try:
        seed = int(seed) if seed is not None and str(seed).strip() != "" and not isinstance(seed, bool) else None
    except (ValueError, TypeError):
        seed = None
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "ImageScaleBy",
              "inputs": {"image": ["1", 0], "upscale_method": "lanczos", "scale_by": float(scale)}},
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_pos, "clip": ["3", 1]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_neg, "clip": ["3", 1]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["2", 0], "vae": ["3", 2]}},
        "7": {"class_type": "KSampler",
              "inputs": {"seed": seed, "steps": int(steps), "cfg": float(cfg),
                         "sampler_name": "euler", "scheduler": "normal", "denoise": float(denoise),
                         "model": ["3", 0], "positive": ["4", 0], "negative": ["5", 0],
                         "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 2]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": "atlas/refine_" + time.strftime("%Y%m%d_%H%M%S")}},
    }


def build_variants_workflow(image_name, prompt_pos, prompt_neg, n=4, denoise=0.45, seed=None,
                            ckpt="sd_xl_base_1.0.safetensors"):
    """第二十轮：锁定角色一致性——以选定的主图为基底，同一个种子、低重绘强度批量出 n 张变体。
    RepeatLatentBatch 让同一张图复制成一批，批内每张的噪声不同，构图和角色保持一致、细节各有变化。"""
    import random
    try:
        seed = int(seed) if seed is not None and str(seed).strip() != "" and not isinstance(seed, bool) else None
    except (ValueError, TypeError):
        seed = None
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_pos, "clip": ["3", 1]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_neg, "clip": ["3", 1]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["3", 2]}},
        "10": {"class_type": "RepeatLatentBatch", "inputs": {"samples": ["6", 0], "amount": int(n)}},
        "7": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 22, "cfg": 6.5, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": float(denoise), "model": ["3", 0],
                                                    "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["10", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "atlas/var_" + time.strftime("%Y%m%d_%H%M%S")}},
    }


def build_remove_bg_workflow(image_name, model="birefnet.safetensors"):
    """第十三轮：方案B 第二步——BiRefNet 抠图输出透明 PNG。
    RemoveBackground 输出的是"前景=1"的遮罩，而 JoinImageWithAlpha 内部做 alpha = 1 - mask，
    所以中间必须 InvertMask，否则会把主体抠掉、留下背景。"""
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": model}},
        "3": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "InvertMask", "inputs": {"mask": ["3", 0]}},
        "5": {"class_type": "JoinImageWithAlpha", "inputs": {"image": ["1", 0], "alpha": ["4", 0]}},
        "6": {"class_type": "SaveImage",
              "inputs": {"images": ["5", 0], "filename_prefix": "atlas/nobg_" + time.strftime("%Y%m%d_%H%M%S")}},
    }


def _png_size(path):
    """读 PNG 头拿宽高（工具桥用系统 Python，不保证有 Pillow）。非 PNG 返回 None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            import struct
            return struct.unpack(">II", head[16:24])
    except Exception:
        pass
    return None


# --------------------------------------------------------------- 作业执行
def _safe_output_dir(jid):
    """产物目录必须落在 OUTPUT_ROOT 内。"""
    d = (OUTPUT_ROOT / jid).resolve()
    if OUTPUT_ROOT.resolve() not in d.parents and d != OUTPUT_ROOT.resolve():
        raise RuntimeError("非法产物路径")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_prev_artifacts(jid, idx):
    """轮9：收集当前步骤之前所有已完成步骤的产物文件名（供图生3D 取输入图）。"""
    job = get_job(jid)
    if not job:
        return []
    out = []
    for s in job.get("steps", [])[:idx]:
        if s.get("status") == "done" and s.get("artifact"):
            # artifact 形如 "outputs/<jid>/a.png, b.png"，取逗号分隔的文件名
            for part in s["artifact"].split(","):
                part = part.strip().split("/")[-1]
                if part:
                    out.append(part)
    return out


def _latest_prev_image(jid, idx):
    """第十三轮：取当前步骤之前最新的一张图片产物，返回 (文件名, 路径或 None)。"""
    srcs = _get_prev_artifacts(jid, idx)
    name = next((p for p in reversed(srcs) if p.lower().endswith(IMG_EXT)), "")
    if not name:
        return "", None
    p = _safe_output_dir(jid) / Path(name).name
    if not p.is_file():
        p = _comfy_output_dir() / Path(name).name
    return name, (p if p.is_file() else None)


def _to_comfy_input(path):
    """LoadImage 只认 ComfyUI input 目录里的文件：复制过去，返回文件名。"""
    comfy_input = _comfy_output_dir().parent / "input"
    comfy_input.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(path), str(comfy_input / path.name))
    return path.name


def _run_comfy_images(jid, idx, label, wf, phase):
    """第十三轮：提交一个出图工作流，等完成，归档图片产物，并把本步记为完成。"""
    pid = submit_prompt(wf, client_id=jid)

    def tick(elapsed, total, real=None):
        pct = real if real is not None else min(95, int(elapsed / total * 100))
        _update(jid, progress=min(99, pct),
                current="%s · %s %s（%ds）" % (label, phase, "%d%%" % pct if real is not None else "进行中", int(elapsed)))

    hist = wait_prompt(pid, on_tick=tick, jid=jid)
    arts = [img.get("filename", "") for node in hist.get("outputs", {}).values()
            for img in node.get("images", []) if img.get("type", "output") == "output"]
    saved = archive_artifacts(jid, arts, subdir="atlas")
    if not saved:
        _set_step(jid, idx, "error", detail="%s完成，但没找到输出图片（%s）" % (phase, ", ".join(arts) or "无"))
        _update(jid, status="failed", current=phase + "没有产出")
        return False
    _set_step(jid, idx, "done", detail="%s完成：%s" % (phase, saved[0]),
              artifact="outputs/%s/%s" % (jid, ", ".join(saved)))
    with _LOCK:
        _JOBS[jid]["artifacts"].extend(saved)
    _update(jid, progress=100)
    return True


def _comfy_output_dir():
    """ComfyUI 的产物输出目录（便携版）。可用环境变量覆盖。"""
    env = os.environ.get("ATLAS_COMFY_OUTPUT")
    if env:
        return Path(env)
    # 便携版默认 output 目录
    default = Path("I:/workbuddy/AI-Engine/portable/ComfyUI_windows_portable/ComfyUI/output")
    return default if default.is_dir() else (HERE / "outputs")


def archive_artifacts(jid, filenames, subdir=""):
    """把 ComfyUI 产物复制到 outputs/<jid>/ 归档，返回相对路径列表。
    兼容 ComfyUI 把子目录产物放在 output/<subdir>/ 的情况。
    """
    src_root = _comfy_output_dir()
    dst = _safe_output_dir(jid)
    saved = []
    for fn in filenames:
        if not fn:
            continue
        # 只取文件名，防路径穿越
        base = Path(fn).name
        candidates = [src_root / base, src_root / subdir / base] if subdir else [src_root / base]
        src = next((c for c in candidates if c.is_file()), None)
        if not src:
            continue
        try:
            shutil.copy2(str(src), str(dst / base))
            saved.append(base)
        except Exception:
            pass
    return saved


def create_job(spec):
    """创建一个作业。spec 来自前端『作业单』。"""
    jid = "job_" + uuid.uuid4().hex[:12]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    steps = spec.get("steps", [])
    job = {
        "id": jid,
        "name": spec.get("name", "未命名任务包"),
        "created": now,
        "updated": now,
        "status": "queued",       # queued/running/paused/done/failed/stopped
        "progress": 0,
        "current": "",
        "steps": [
            {"index": i, "kind": s.get("kind", "human"),
             "label": s.get("label", "步骤%d" % (i + 1)),
             # 轮6：保留 hint（阶段说明）——前端作业单里有，原代码构造 step 时丢弃，
             # 用户看进度时不知道"这一步该做什么"。
             "hint": s.get("hint", ""),
             "fallback": s.get("fallback", "") if s.get("fallback") in ("skip", "") else "",
             "status": "pending", "detail": "", "artifact": ""}
            for i, s in enumerate(steps)
            if isinstance(s, dict)   # 轮18：跳过非对象元素，防畸形作业单崩溃
        ],
        "spec": spec,
        "artifacts": [],
    }
    with _LOCK:
        _JOBS[jid] = job
        # 轮15：清理旧作业——只保留最近 MAX_JOBS 个，且绝不删除未完成的
        if len(_JOBS) > MAX_JOBS:
            done = [k for k, v in _JOBS.items()
                    if v.get("status") in ("done", "failed", "stopped", "paused")]
            done.sort(key=lambda k: _JOBS[k].get("created", ""))
            for k in done[:len(_JOBS) - MAX_JOBS]:
                del _JOBS[k]
    _save_jobs(force=True)   # 轮11：创建是关键状态，立即落盘
    _ensure_worker()
    return jid


def _update(jid, **kw):
    with _LOCK:
        j = _JOBS.get(jid)
        if not j:
            return
        j.update(kw)
        j["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_jobs()


def _set_step(jid, idx, status, detail="", artifact=""):
    with _LOCK:
        j = _JOBS.get(jid)
        if not j or idx >= len(j["steps"]):
            return
        s = j["steps"][idx]
        s["status"] = status
        if detail:
            s["detail"] = detail
        if artifact:
            s["artifact"] = artifact
    _save_jobs()


def _run_step(jid, idx, step, spec):
    """执行单个步骤。返回 (是否继续后续步骤)。"""
    kind = step["kind"]
    label = step["label"]
    _update(jid, current=label)
    _set_step(jid, idx, "running")

    # 人工环节：暂停并交接
    if kind in HUMAN_KINDS:
        _set_step(jid, idx, "needs_human",
                  detail="此步骤需要人工创意操作（%s），引擎已备好前置产物，请在此接手。" % label)
        _update(jid, status="paused",
                current="暂停：等待人工接手 —— " + label)
        return False

    outdir = _safe_output_dir(jid)
    try:
        if kind == "text_to_image":
            ok, info = ensure_comfy(jid, label)
            if not ok:
                _set_step(jid, idx, "error", detail="ComfyUI 不可用：" + str(info.get("error")))
                _update(jid, status="failed", current="ComfyUI 不可用")
                return False
            pos_en, neg_en, untr = english_prompts(jid, spec)
            ck, prof = ckpt_profile(spec)
            wf = build_txt2img_workflow(
                pos_en, neg_en,
                steps=spec.get("sample_steps", prof["steps"]), cfg=spec.get("cfg", prof["cfg"]),   # spec["steps"] 是步骤列表，不是采样步数
                width=spec.get("width", 1024), height=spec.get("height", 1024),
                seed=spec.get("seed"), ckpt=ck, sampler=prof["sampler"])
            pid = submit_prompt(wf, client_id=jid)

            def tick(elapsed, total, real=None):
                # 轮14：真实采样进度优先；拿不到才回退时间估算
                pct = real if real is not None else min(95, int(elapsed / total * 100))
                _update(jid, progress=min(99, pct),
                        current="%s · ComfyUI %s（%ds）" % (
                            label, "采样 %d%%" % pct if real is not None else "生成中", int(elapsed)))

            hist = wait_prompt(pid, on_tick=tick, jid=jid)   # 轮4：传 jid 支持 per-job 停止
            # 收集并归档产物（从 ComfyUI output 复制到 outputs/<jid>/）
            arts = []
            for node in hist.get("outputs", {}).values():
                for img in node.get("images", []):
                    arts.append(img.get("filename", ""))
            saved = archive_artifacts(jid, arts, subdir="atlas")
            display = saved if saved else arts
            rel = "outputs/%s/%s" % (jid, ", ".join(display[:3]))
            _set_step(jid, idx, "done",
                      detail="生成 %d 张图，归档 %d 张%s" % (len(arts), len(saved),
                             "；注意：有 %d 段中文没能翻译（%s），模型读不懂它们——请下载翻译模型或改用英文" % (len(untr), "、".join(untr[:3]))
                             if untr else ""), artifact=rel)
            with _LOCK:
                _JOBS[jid]["artifacts"].extend(display)
            _update(jid, progress=100)
            return True

        if kind == "image_to_3d":
            # 轮9：真实图生3D 执行器——用官方 TRELLIS.2 工作流（已转 API 格式），
            # 输入图取自上一步已归档的产物，形成"文生图→图生3D"自动链。
            wf_path = HERE / "workflows" / "trellis2_image_to_3d.json"
            if not wf_path.is_file():
                _set_step(jid, idx, "error", detail="图生3D 工作流文件缺失：" + str(wf_path))
                _update(jid, status="failed", current="工作流缺失")
                return False
            ok, info = ensure_comfy(jid, label)
            if not ok:
                _set_step(jid, idx, "error", detail="ComfyUI 不可用：" + str(info.get("error")))
                _update(jid, status="failed", current="ComfyUI 不可用")
                return False
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            wf = adapt_workflow_models(wf)
            if bg_model_missing(wf):     # 第十二轮：仅在 birefnet 未安装时旁路
                wf = bypass_bg_removal(wf)
            # 找上一步产物作为输入图
            prev_img = ""
            for p in reversed(j["steps"][:idx] if False else _get_prev_artifacts(jid, idx)):
                if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    prev_img = p
                    break
            if not prev_img:
                _set_step(jid, idx, "needs_human",
                          detail="图生3D 需要一张输入图，但前面步骤没有产出图片。请先执行文生图步骤，或手动提供一张干净图。")
                _update(jid, status="paused", current="暂停：图生3D 缺少输入图")
                return False
            # 轮9：LoadImage 只认 ComfyUI input 目录里的文件——把上一步产物复制过去
            comfy_input = _comfy_output_dir().parent / "input"
            comfy_input.mkdir(parents=True, exist_ok=True)
            src_img = _safe_output_dir(jid) / Path(prev_img).name
            if not src_img.is_file():
                src_img = _comfy_output_dir() / Path(prev_img).name
            if src_img.is_file():
                shutil.copy2(str(src_img), str(comfy_input / Path(prev_img).name))
            for node in wf.values():
                if node.get("class_type") == "LoadImage":
                    node["inputs"]["image"] = Path(prev_img).name
                if node.get("class_type") in ("SaveGLB", "Save3DAdvanced"):
                    node["inputs"]["filename_prefix"] = "3d/" + jid
            pid = submit_prompt(wf, client_id=jid)
            def tick3d(elapsed, total, real=None):
                pct = real if real is not None else min(95, int(elapsed / total * 100))
                _update(jid, progress=min(99, pct),
                        current="%s · 图生3D %s（%ds）" % (
                            label, "采样 %d%%" % pct if real is not None else "计算中", int(elapsed)))
            # 第十二轮：首次加载 11GB 权重 + 烘焙较慢（实测热机 271s），超时放宽到 40 分钟
            hist = wait_prompt(pid, timeout=2400, on_tick=tick3d, jid=jid)   # 轮14：真实进度
            glbs = []
            for node in hist.get("outputs", {}).values():
                # 第十二轮：ComfyUI 0.45 的 SaveGLB 把产物放在 "3d" 键（Saved3DModels），
                # 不在 images/gifs；预览节点的临时文件 type=temp，不归档。
                for g in node.get("3d", []) + node.get("images", []) + node.get("gifs", []):
                    if (isinstance(g, dict) and str(g.get("filename", "")).lower().endswith(".glb")
                            and g.get("type", "output") == "output" and g["filename"] not in glbs):
                        glbs.append(g["filename"])
            saved = archive_artifacts(jid, glbs, subdir="3d")
            _set_step(jid, idx, "done" if (glbs or saved) else "error",
                      detail="图生3D 完成，GLB %d 个" % len(glbs),
                      artifact="outputs/%s/%s" % (jid, ", ".join(saved or glbs)[:200]))
            if glbs or saved:
                with _LOCK:
                    _JOBS[jid]["artifacts"].extend(saved or glbs)
                _update(jid, progress=100)
                return True
            return False

        if kind == "note":
            # 第二十轮：说明类步骤（如"进入重建（下一支线）"）——只是提示去向，不卡住作业
            _set_step(jid, idx, "done", detail=step.get("hint", "") or "说明")
            return True

        if kind == "input_image":
            # 第二十轮：用户上传的图片 / 3D 模型；没上传就沿用前面步骤的图片；都没有就暂停等上传
            ups = [u for u in (spec.get("inputs") or []) if isinstance(u, str) and _UPLOAD_RE.match(u)]
            got = []
            for u in ups:
                src = UPLOAD_DIR / u
                if src.is_file():
                    shutil.copy2(str(src), str(outdir / u))
                    got.append(u)
            if got:
                _set_step(jid, idx, "done", detail="使用上传的文件：" + "、".join(got),
                          artifact="outputs/%s/%s" % (jid, ", ".join(got)))
                with _LOCK:
                    _JOBS[jid]["artifacts"].extend(x for x in got if x not in _JOBS[jid]["artifacts"])
                return True
            name, src = _latest_prev_image(jid, idx)
            if src:
                _set_step(jid, idx, "done", detail="沿用上一步的图片：" + name,
                          artifact="outputs/%s/%s" % (jid, name))
                return True
            if step.get("fallback") == "skip":
                _set_step(jid, idx, "skipped", detail="没有上传图片，跳过这一步")
                return True
            _set_step(jid, idx, "needs_human",
                      detail="这一步需要一张输入图片（或 3D 模型）：在下方卡片里上传，然后点「上传并继续」。")
            _update(jid, status="paused", current="暂停：等待上传输入文件 —— " + label)
            return False

        if kind == "variants":
            # 第二十轮：锁定角色一致性——自动出 4 张同种子变体，暂停让用户挑一张作为定稿
            ok, info = ensure_comfy(jid, label)
            if not ok:
                _set_step(jid, idx, "error", detail="ComfyUI 不可用：" + str(info.get("error")))
                _update(jid, status="failed", current="ComfyUI 不可用")
                return False
            name, src = _latest_prev_image(jid, idx)
            if not src:
                _set_step(jid, idx, "needs_human", detail="没有找到主图，无法出变体。")
                _update(jid, status="paused", current="暂停：出变体缺主图")
                return False
            img_name = _to_comfy_input(src)
            pos_en, neg_en, _ = english_prompts(jid, spec)
            # 逐张出：一次出 4 张（批量 4 × 1024²）时，ComfyUI 估算显存不够，把部分权重放到内存里算，
            # 真机实测一步 92 秒；逐张出每步约 1.7 秒，4 张合计约 2–3 分钟。种子依次 +1，构图仍跟主图一致。
            import random as _rnd
            try:
                base_seed = int(spec.get("seed"))
            except (TypeError, ValueError):
                base_seed = _rnd.randint(1, 2**31 - 5)
            arts, n_var = [], 4
            for vi in range(n_var):
                wf = build_variants_workflow(img_name, pos_en, neg_en, n=1, seed=base_seed + vi,
                                             ckpt=ckpt_profile(spec)[0])
                pid = submit_prompt(wf, client_id=jid)

                def tick(elapsed, total, real=None, _vi=vi):
                    pct = real if real is not None else min(95, int(elapsed / total * 100))
                    overall = int((_vi * 100 + pct) / n_var)
                    _update(jid, progress=min(99, overall), current="%s · 出变体 第 %d/%d 张 %s（%ds）" % (
                        label, _vi + 1, n_var, "%d%%" % pct if real is not None else "进行中", int(elapsed)))
                hist = wait_prompt(pid, on_tick=tick, jid=jid)
                arts += [im.get("filename", "") for node in hist.get("outputs", {}).values()
                         for im in node.get("images", []) if im.get("type", "output") == "output"]
                if _job_stopped(jid):
                    break
            saved = archive_artifacts(jid, arts, subdir="atlas")
            if not saved:
                _set_step(jid, idx, "error", detail="变体生成完成，但没找到输出图片")
                _update(jid, status="failed", current="变体没有产出")
                return False
            with _LOCK:
                _JOBS[jid]["artifacts"].extend(saved)
            _set_step(jid, idx, "needs_human",
                      detail="已出 %d 张同一角色的变体：在下方点「选这张」定稿；都不满意就点「重新出 4 张」。" % len(saved),
                      artifact="outputs/%s/%s" % (jid, ", ".join(saved)))
            _update(jid, status="paused", progress=100, current="暂停：挑一张变体定稿 —— " + label)
            return False

        if kind == "krita_edit":
            # 第十三轮 · 方案A：复制一份上一步的图（原图不动），用 Krita 打开，然后暂停等人改完
            name, src = _latest_prev_image(jid, idx)
            if not src:
                _set_step(jid, idx, "needs_human", detail="没有找到上一步的图片，无法在 Krita 里打开。")
                _update(jid, status="paused", current="暂停：方案A 缺少图片")
                return False
            exe = find_krita()
            if not exe:
                _set_step(jid, idx, "error", detail="未找到 Krita：请在执行台对 Krita 点「一键安装」后重试")
                _update(jid, status="failed", current="未安装 Krita")
                return False
            base = Path(name).stem
            while base.startswith("edit_"):
                base = base[5:]
            edit_name = "edit_%s_%s.png" % (base, time.strftime("%H%M%S"))
            edit_path = outdir / edit_name
            shutil.copy2(str(src), str(edit_path))
            panel_ok, why = ensure_krita_plugin()
            if panel_ok:
                kra_path = edit_path.with_suffix(".kra")
                job = get_job(jid) or {}
                write_krita_session({
                    "mode": "edit", "jid": jid, "step": idx, "job_name": job.get("name", ""),
                    "image": str(edit_path), "png": str(edit_path), "kra": str(kra_path),
                    "prompt_pos": spec.get("prompt_pos", ""), "prompt_neg": spec.get("prompt_neg", ""),
                    "ckpt": ckpt_profile(spec)[0]})
                if not _krita_running():
                    subprocess.Popen([str(exe)], cwd=str(exe.parent))   # 面板启动后从会话文件接手
                detail = ("Krita 里已分层打开 %s：底层「AI 原图」已锁定，在「我的修改」层上画。"
                          "改完在 Krita 右侧「Atlas 工坊」面板点「完成，回传工坊」（也可以 Ctrl+S 保存后回这里点「我改完了」）。"
                          % edit_name)
            else:
                subprocess.Popen([str(exe), str(edit_path)], cwd=str(exe.parent))
                detail = ("已在 Krita 打开 %s：改完按 Ctrl+S 保存（弹出 PNG 选项直接点确定），再回来点「我改完了」。（%s）"
                          % (edit_name, why))
            _set_step(jid, idx, "needs_human", detail=detail,
                      artifact="outputs/%s/%s" % (jid, edit_name))
            with _LOCK:
                _JOBS[jid]["artifacts"].append(edit_name)
            _update(jid, status="paused", progress=100, current="方案A：在 Krita 里修改中 —— 改完保存后点「我改完了」")
            return False

        if kind in ("ai_upscale", "remove_bg"):
            # 第十三轮 · 方案B：AI 自动精修（高清重绘 / 去背景），全部在 ComfyUI 里完成
            ok, info = ensure_comfy(jid, label)
            if not ok:
                _set_step(jid, idx, "error", detail="ComfyUI 不可用：" + str(info.get("error")))
                _update(jid, status="failed", current="ComfyUI 不可用")
                return False
            name, src = _latest_prev_image(jid, idx)
            if not src:
                _set_step(jid, idx, "needs_human", detail="没有找到上一步的图片，无法精修。")
                _update(jid, status="paused", current="暂停：精修缺少输入图")
                return False
            img_name = _to_comfy_input(src)
            if kind == "ai_upscale":
                size = _png_size(src)
                scale = 1.5
                if size:   # 长边封顶 2048，避免显存爆掉；已经够大就只重绘不放大
                    scale = min(1.5, 2048.0 / max(size))
                    if scale < 1.05:
                        scale = 1.0
                pos_en, neg_en, _ = english_prompts(jid, spec)
                wf = build_img2img_workflow(img_name, pos_en, neg_en,
                                            scale=scale, seed=spec.get("seed"),
                                            ckpt=ckpt_profile(spec)[0])
                return _run_comfy_images(jid, idx, label, wf, "高清重绘")
            wf = build_remove_bg_workflow(img_name)
            if bg_model_missing(wf):
                _set_step(jid, idx, "error", detail="ComfyUI 里没有 birefnet 去背景模型（models/background_removal/birefnet.safetensors）")
                _update(jid, status="failed", current="缺少去背景模型")
                return False
            return _run_comfy_images(jid, idx, label, wf, "去背景")

        if kind == "clean_image":
            # 轮10：真实净化执行器——用便携版 Python + Pillow 做白底透明化 + 裁剪，
            # 把文生图产物净化成可喂给图生3D 的干净输入。
            cleaner = HERE / "clean_image.py"
            portable_py = Path("I:/workbuddy/AI-Engine/portable/ComfyUI_windows_portable/python_embeded/python.exe")
            if not cleaner.is_file() or not portable_py.is_file():
                _set_step(jid, idx, "error", detail="净化脚本或便携版 Python 缺失")
                _update(jid, status="failed", current="净化环境缺失")
                return False
            srcs = _get_prev_artifacts(jid, idx)
            src = next((p for p in srcs if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))), "")
            if not src:
                _set_step(jid, idx, "needs_human", detail="净化需要一张输入图，前面步骤没产出图片")
                _update(jid, status="paused", current="暂停：净化缺输入图")
                return False
            src_path = _safe_output_dir(jid) / Path(src).name
            if not src_path.is_file():
                src_path = _comfy_output_dir() / Path(src).name
            out_name = "clean_" + Path(src).stem + ".png"
            out_path = _safe_output_dir(jid) / out_name
            proc = subprocess.run([str(portable_py), str(cleaner), str(src_path), str(out_path)],
                                  capture_output=True, text=True, timeout=120)
            if out_path.is_file():
                _set_step(jid, idx, "done", detail="净化完成：" + proc.stdout.strip()[:80],
                          artifact="outputs/%s/%s" % (jid, out_name))
                with _LOCK:
                    _JOBS[jid]["artifacts"].append(out_name)
                _update(jid, progress=100)
                return True
            _set_step(jid, idx, "error", detail="净化失败：" + (proc.stderr or proc.stdout)[:150])
            _update(jid, status="failed", current="净化失败")
            return False

        if kind == "krita_paint":
            # 第十二轮：AI 在 Krita 里逐笔作画——参考图 → 笔触规划 → 启动 Krita（插件自动回放）→ 归档 .kra/.png
            painter_dir = HERE / "painter"
            portable_py = Path("I:/workbuddy/AI-Engine/portable/ComfyUI_windows_portable/python_embeded/python.exe")
            krita_exe = find_krita()
            if not portable_py.is_file() or not (painter_dir / "stroke_planner.py").is_file():
                _set_step(jid, idx, "error", detail="逐笔作画环境缺失（便携版 Python 或 painter/ 脚本）")
                _update(jid, status="failed", current="逐笔作画环境缺失")
                return False
            if not krita_exe:
                _set_step(jid, idx, "error", detail="未找到 Krita：请在执行台对 Krita 点「一键安装」后重试")
                _update(jid, status="failed", current="未安装 Krita")
                return False
            srcs = _get_prev_artifacts(jid, idx)
            src = next((p for p in reversed(srcs) if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))), "")
            if not src:
                _set_step(jid, idx, "needs_human", detail="逐笔作画需要一张参考图，但前面步骤没有产出图片。")
                _update(jid, status="paused", current="暂停：逐笔作画缺参考图")
                return False
            src_path = outdir / Path(src).name
            if not src_path.is_file():
                src_path = _comfy_output_dir() / Path(src).name
            # 1) 安装/启用插件（Krita 必须关闭：插件只在启动时加载，且 Krita 退出会重写 kritarc）
            inst = subprocess.run([str(portable_py), str(painter_dir / "install_krita_plugin.py")],
                                  capture_output=True, text=True, timeout=60)
            last = (inst.stdout.strip().splitlines() or [""])[-1]
            if last == "KRITA_RUNNING":
                _set_step(jid, idx, "needs_human",
                          detail="Krita 正在运行：请先关闭 Krita（保存好手头的画），再点「一键自动执行任务包」继续。")
                _update(jid, status="paused", current="暂停：请先关闭 Krita")
                return False
            if last != "INSTALLED":
                _set_step(jid, idx, "error", detail="插件安装失败：" + (inst.stderr or inst.stdout)[-150:])
                _update(jid, status="failed", current="逐笔作画插件安装失败")
                return False
            # 2) 笔触规划
            _update(jid, current="%s · 规划笔触" % label)
            job_path = outdir / "paint_job.json"
            plan = subprocess.run([str(portable_py), str(painter_dir / "stroke_planner.py"), str(src_path),
                                   str(job_path), "--size", "1024", "--preview", str(outdir / "paint_preview.png"),
                                   "--detail", spec.get("paint_detail", "fine") if spec.get("paint_detail") in ("fine", "fast") else "fine"],
                                  capture_output=True, text=True, timeout=300)
            if not job_path.is_file():
                _set_step(jid, idx, "error", detail="笔触规划失败：" + (plan.stderr or plan.stdout)[-150:])
                _update(jid, status="failed", current="笔触规划失败")
                return False
            pj = json.loads(job_path.read_text(encoding="utf-8"))
            stem = "paint_" + Path(src).stem
            pj.update({"output_kra": str(outdir / (stem + ".kra")), "output_png": str(outdir / (stem + ".png")),
                       "progress_file": str(outdir / "paint_progress.json"),
                       "done_file": str(job_path) + ".done"})
            job_path.write_text(json.dumps(pj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            done_file = Path(pj["done_file"]); prog_file = Path(pj["progress_file"])
            for f in (done_file, prog_file):
                if f.exists():
                    f.unlink()
            total = sum(len(L["strokes"]) for L in pj["layers"])
            # 第十八轮：面板据此显示作画进度，画完提示下一步
            try:
                write_krita_session({"mode": "paint", "jid": jid, "step": idx,
                                     "job_name": (get_job(jid) or {}).get("name", ""),
                                     "progress_file": pj["progress_file"], "done_file": pj["done_file"],
                                     "kra": pj["output_kra"], "png": pj["output_png"],
                                     "prompt_pos": spec.get("prompt_pos", ""), "prompt_neg": spec.get("prompt_neg", ""),
                                     "ckpt": ckpt_profile(spec)[0]})
            except Exception:
                pass
            # 3) 启动 Krita，插件读 ATLAS_PAINT_JOB 自动开画
            env = dict(os.environ, ATLAS_PAINT_JOB=str(job_path))
            proc = subprocess.Popen([str(krita_exe)], env=env)
            t0 = time.time()
            while time.time() - t0 < 3 * 3600:   # 第十九轮：精度版约 9 万笔，上限放宽到 3 小时
                if done_file.is_file():
                    break
                if _job_stopped(jid):
                    _set_step(jid, idx, "error", detail="已停止（Krita 窗口保留，可手动保存）")
                    return False
                if proc.poll() is not None:
                    _set_step(jid, idx, "error", detail="Krita 在作画完成前被关闭")
                    _update(jid, status="failed", current="Krita 被关闭")
                    return False
                try:
                    pr = json.loads(prog_file.read_text(encoding="utf-8"))
                    pct = int(pr.get("painted", 0) * 100 / max(1, total))
                    _update(jid, progress=min(99, pct),
                            current="%s · Krita 逐笔作画 · %s（%d/%d 笔，%ds）" % (
                                label, pr.get("layer", ""), pr.get("painted", 0), total, int(time.time() - t0)))
                except Exception:
                    _update(jid, current="%s · 等待 Krita 启动并加载插件（%ds）" % (label, int(time.time() - t0)))
                time.sleep(1.5)
            else:
                _set_step(jid, idx, "error", detail="逐笔作画超时（3 小时）")
                _update(jid, status="failed", current="逐笔作画超时")
                return False
            res = json.loads(done_file.read_text(encoding="utf-8"))
            if not res.get("ok"):
                _set_step(jid, idx, "error", detail="Krita 插件报错：" + str(res.get("error", ""))[-160:])
                _update(jid, status="failed", current="逐笔作画失败")
                return False
            arts = [Path(res["png"]).name, Path(res["kra"]).name]
            _set_step(jid, idx, "done", detail="逐笔作画完成：%d 笔，%ss，分层 .kra 已保存" % (res.get("strokes", 0), res.get("seconds")),
                      artifact="outputs/%s/%s" % (jid, ", ".join(arts)))
            with _LOCK:
                _JOBS[jid]["artifacts"].extend(arts)
            _update(jid, progress=100)
            return True

        # 轮7：用 AUTO_KINDS 做兜底校验——未知类型一律当人工处理，
        # 绝不静默跳过（原代码走到这里直接当人工，AUTO_KINDS 成了死代码）。
        if kind not in AUTO_KINDS and kind not in HUMAN_KINDS:
            _set_step(jid, idx, "needs_human",
                      detail="未知步骤类型 %s（不属于可执行集 %s），需人工处理" % (kind, sorted(AUTO_KINDS)))
            _update(jid, status="paused", current="暂停：未知步骤 " + kind)
            return False
        # 已知人工类型但漏在上面分支处理：同样保守暂停
        _set_step(jid, idx, "needs_human", detail="步骤类型 %s 需人工处理" % kind)
        _update(jid, status="paused", current="暂停：" + kind)
        return False
    except Exception as e:
        if _job_stopped(jid):           # 第二十轮：用户点了停止，记为"已停止"而不是"失败"
            _set_step(jid, idx, "error", detail="已停止")
            _update(jid, status="stopped", current="已停止")
            return False
        _set_step(jid, idx, "error", detail=("%s: %s" % (type(e).__name__, str(e)[:180])))
        _update(jid, status="failed", current="步骤失败：" + label)
        return False


_JID_RE = re.compile(r"^job_[0-9a-f]{12}$")


def resume_job(jid):
    """第十二轮：人工接手后继续执行。

    暂停在人工步骤 → 视为已由人完成，标 done，从下一步继续；
    暂停在自动步骤（如"Krita 正在运行"、缺输入）→ 状态复位为 pending，重跑这一步。
    """
    with _LOCK:
        j = _JOBS.get(jid)
        if not j:
            return False, "作业不存在"
        if j.get("status") != "paused":
            return False, "作业当前不在暂停状态（%s）" % j.get("status")
        st = next((s for s in j["steps"] if s.get("status") == "needs_human"), None)
        if st is None:
            return False, "没有等待接手的步骤"
        if st.get("kind") in AUTO_KINDS:
            st["status"], st["detail"] = "pending", "已请求重试"
        else:
            if st.get("kind") == "krita_edit" and st.get("artifact"):
                png = OUTPUT_ROOT / jid / st["artifact"].split(",")[-1].strip().split("/")[-1]
                kra = png.with_suffix(".kra")
                if kra.is_file() and (not png.is_file() or kra.stat().st_mtime > png.stat().st_mtime + 1):
                    kra_to_png(kra, png)
            st["status"], st["detail"] = "done", "人工已确认完成"
        j["status"] = "queued"
        j["current"] = "继续执行中…"
        j["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with _JOB_STOPS_LOCK:
        ev = _JOB_STOPS.get(jid)
        if ev:
            ev.clear()
    _save_jobs(force=True)
    _ensure_worker()
    return True, "已继续"


UPLOAD_DIR = OUTPUT_ROOT / "_uploads"
_UPLOAD_RE = re.compile(r"^up_[0-9a-f]{12}\.(png|jpg|jpeg|webp|glb|gltf|obj|stl|fbx|ply)$")


def save_upload(data, orig_name):
    """第二十轮：保存上传的输入文件。文件名只用随机 id + 白名单扩展名，不用原名（防路径穿越 / 怪字符）。"""
    ext = Path(str(orig_name or "")).suffix.lower()
    if ext not in UPLOAD_EXT:
        return False, "不支持的文件类型（支持图片 png/jpg/webp 与 3D 模型 glb/gltf/obj/stl/fbx/ply）"
    if not data:
        return False, "文件是空的"
    if len(data) > UPLOAD_MAX:
        return False, "文件太大（上限 200MB）"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = "up_%s%s" % (uuid.uuid4().hex[:12], ext)
    (UPLOAD_DIR / name).write_bytes(data)
    return True, name


def add_job_input(jid, data, orig_name):
    """作业停在"等待上传"时：保存文件、写进作业单、继续执行。"""
    ok, name = save_upload(data, orig_name)
    if not ok:
        return False, name
    with _LOCK:
        j = _JOBS.get(jid)
        if not j:
            return False, "作业不存在"
        j.setdefault("spec", {}).setdefault("inputs", []).append(name)
    ok, msg = resume_job(jid)
    return ok, ("已上传并继续" if ok else msg)


def pick_variant(jid, name):
    """第二十轮：从 4 张变体里选一张定稿——这一步的产物只留选中的那张，然后继续。"""
    with _LOCK:
        j = _JOBS.get(jid)
        if not j or j.get("status") != "paused":
            return False, "作业不在等待挑选的状态"
        st = next((s for s in j["steps"] if s.get("status") == "needs_human" and s.get("kind") == "variants"), None)
        if st is None:
            return False, "没有等待挑选的变体"
        names = [x.strip().split("/")[-1] for x in st.get("artifact", "").split(",") if x.strip()]
        base = Path(str(name)).name
        if base not in names:
            return False, "不是这一步的变体"
        st["status"], st["detail"], st["artifact"] = "done", "已选定：" + base, "outputs/%s/%s" % (jid, base)
        j["status"], j["current"] = "queued", "已选定变体，继续执行…"
        j["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_jobs(force=True)
    _ensure_worker()
    return True, "已选定 " + base


def update_spec(jid, fields):
    """第十八轮：Krita 面板里改的提示词写回作业单，后续步骤（如方案B 精修）沿用。"""
    allowed = {k: v for k, v in (fields or {}).items()
               if k in ("prompt_pos", "prompt_neg") and isinstance(v, str) and len(v) <= 4000}
    if not allowed:
        return False, "没有可更新的字段"
    with _LOCK:
        j = _JOBS.get(jid)
        if not j:
            return False, "作业不存在"
        j.setdefault("spec", {}).update(allowed)
        for k in allowed:              # 中文提示词改了，之前页面上改的英文版本作废，重新翻译
            j["spec"].pop(k + "_en", None)
        j["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_jobs(force=True)
    return True, "提示词已保存到作业"


def branch_job(jid, plan, detail=""):
    """第十三轮：用户在接手卡片上选了 A/B/C 方案——把后续步骤换成该方案的步骤并继续执行。

    - 暂停在人工 / 半自动步骤：该步记为完成（半自动步骤保留它的产物，如 Krita 改过的图），
      其后原有的步骤丢弃，换成方案步骤；
    - 暂停在自动步骤（如"请先关闭 Krita"）：该步记为 skipped，同样换成方案步骤；
    - 作业已完成：在末尾追加方案步骤（对最终产物继续加工）。
    - 作业失败 / 被停止：出错的那一步记为 skipped，从那里换成方案步骤。
    """
    if plan not in PLANS:
        return False, "未知方案：%s" % plan
    with _LOCK:
        j = _JOBS.get(jid)
        if not j:
            return False, "作业不存在"
        steps = j["steps"]
        if j.get("status") == "paused":
            cut = next((i for i, s in enumerate(steps) if s.get("status") == "needs_human"), None)
            if cut is None:
                return False, "没有等待接手的步骤"
            st = steps[cut]
            if st.get("kind") in AUTO_KINDS:
                st["status"] = "skipped"
            else:
                st["status"] = "done"
            st["detail"] = "已改走 " + PLANS[plan]["title"]
        elif j.get("status") == "done":
            cut = len(steps) - 1
        elif j.get("status") in ("failed", "stopped"):
            # 某个方案失败 / 被停止后，允许改选其他方案：出错的那一步记为 skipped
            cut = next((i for i, s in enumerate(steps) if s.get("status") in ("error", "running", "needs_human")),
                       None)
            if cut is None:
                cut = len(steps) - 1
            else:
                steps[cut]["status"] = "skipped"
        else:
            return False, "作业正在执行（%s），请等它结束或先停止" % j.get("status")
        if not _latest_prev_image(jid, cut + 1)[0]:
            return False, "还没有可以继续加工的图片产物"
        new_steps = steps[:cut + 1] + [dict(s, status="pending", detail="", artifact="") for s in PLANS[plan]["steps"]]
        if len(new_steps) > MAX_STEPS:
            return False, "步骤太多（上限 %d），请重新生成任务包" % MAX_STEPS
        for i, s in enumerate(new_steps):
            s["index"] = i
        j["steps"] = new_steps
        j["plan"] = plan
        j["plan_start"] = cut + 1
        if plan == "ai_paint" and detail in ("fine", "fast"):
            j.setdefault("spec", {})["paint_detail"] = detail     # 第十九轮：逐笔作画 精细 / 快速
        j.setdefault("plan_history", []).append({"plan": plan, "at": cut + 1,
                                                 "time": time.strftime("%Y-%m-%d %H:%M:%S")})
        j["status"] = "queued"
        j["progress"] = 0
        j["current"] = "已选择 " + PLANS[plan]["title"] + "，准备执行…"
        j["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with _JOB_STOPS_LOCK:
        ev = _JOB_STOPS.get(jid)
        if ev:
            ev.clear()
    _save_jobs(force=True)
    _ensure_worker()
    return True, "已切换到 " + PLANS[plan]["title"]


def job_file(jid, name):
    """第十二轮：安全地取作业产物路径——jid 必须合法且存在，name 只取文件名，必须真实存在。"""
    if not _JID_RE.match(jid or "") or jid not in _JOBS:
        return None
    base = (OUTPUT_ROOT / jid).resolve()
    if not base.is_dir():
        return None
    if not name:
        return base
    f = (base / Path(name).name).resolve()
    return f if (f.parent == base and f.is_file()) else None


def open_job_output(jid, name="", with_tool=""):
    """第十二轮：打开产物文件夹，或用 Krita 打开某个产物（让人工接手有落点）。"""
    target = job_file(jid, name)
    if target is None:
        return False, "找不到该产物"
    if with_tool == "krita":
        exe = find_krita()
        if not exe:
            return False, "未找到 Krita，请先在执行台一键安装"
        if target.is_dir():
            return False, "请选择一个产物文件"
        subprocess.Popen([str(exe), str(target)], cwd=str(exe.parent))
        return True, "已用 Krita 打开 " + target.name
    folder = target if target.is_dir() else target.parent
    if os.name == "nt":
        os.startfile(str(folder))   # 资源管理器
        return True, "已打开产物文件夹"
    return False, "仅 Windows 支持打开文件夹"


def _worker_loop():
    while not _STOP.is_set():
        with _LOCK:
            # 轮12：领取即改状态，避免多个 worker 抢到同一个作业
            pending = [j for j in _JOBS.values() if j["status"] == "queued"]
            if not pending:
                j = None
            else:
                j = pending[0]
                j["status"] = "running"   # 原子领取
                jid = j["id"]
                j["progress"] = 0
        if j is None:
            time.sleep(0.8)
            continue
        # 已在上锁时标记 running；这里只落盘一次
        _save_jobs(force=True)
        spec = j.get("spec", {})
        steps = j["steps"]
        for idx, step in enumerate(steps):
            # 轮3：每步前检查该作业是否被单独停止
            if _job_stopped(jid):
                _update(jid, status="stopped", current="已停止")
                break
            # 轮2：续跑时跳过已完成的步骤，避免重复生成（浪费 GPU 时间、覆盖产物）
            if step.get("status") in ("done", "skipped"):   # 第十三轮：改走其他方案时被跳过的步骤
                continue
            cont = _run_step(jid, idx, step, spec)
            if not cont:
                break
        else:
            if not _job_stopped(jid):
                _update(jid, status="done", progress=100, current="全部步骤完成")
        _save_jobs(force=True)   # 第十八轮：结束状态（完成 / 暂停 / 失败）立即落盘，节流写盘不能把它丢在内存里


def _ensure_worker():
    """第十二轮：维持 MAX_WORKERS 个存活 worker，长作业不再阻塞整条队列。"""
    global _WORKER
    _STOP.clear()
    alive = [w for w in _WORKERS if w.is_alive()]
    _WORKERS[:] = alive
    for i in range(MAX_WORKERS - len(_WORKERS)):
        w = threading.Thread(target=_worker_loop, daemon=True,
                             name="atlas-automation-worker-%d" % i)
        w.start()
        _WORKERS.append(w)
    _WORKER = _WORKERS[0] if _WORKERS else None   # 兼容旧引用


def start_engine():
    _load_jobs()
    # 把上次中断的 running 作业改回 queued（可续跑）
    with _LOCK:
        for j in _JOBS.values():
            if j["status"] == "running":
                j["status"] = "queued"
    _save_jobs()
    _ensure_worker()


def stop_job(jid):
    """轮3：停止单个作业（只影响该作业，不动其他作业/全局 worker）。"""
    with _JOB_STOPS_LOCK:
        ev = _JOB_STOPS.get(jid)
        if ev is None:
            ev = threading.Event()
            _JOB_STOPS[jid] = ev
        ev.set()
    job = get_job(jid)
    if job and job["status"] in ("queued", "running"):
        _update(jid, status="stopped", current="已请求停止（当前步骤结束后生效）")
    return True


def _job_stopped(jid):
    with _JOB_STOPS_LOCK:
        ev = _JOB_STOPS.get(jid)
        return bool(ev and ev.is_set())


def stop_engine():
    _STOP.set()
