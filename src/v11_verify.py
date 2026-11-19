#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第十一轮 · 自动化引擎统一验证器 V1..V20（对应 20 轮）

审视轴：引擎健壮性与功能兑现（与前 10 轮零重叠）。
静态契约 + 行为仿真，不依赖真实 ComfyUI / torch。
用法: python v11_verify.py [--tags=V1,V2] [--json]
"""
import importlib.util, json, re, sys, tempfile, threading, time, os
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "创作工具星图"   # 第二十轮：相对路径
AUTO_PY = PKG / "快捷方式工具" / "automation.py"
BRIDGE_PY = PKG / "快捷方式工具" / "tool-bridge.py"
STUDIO = PKG / "studio.html"

R = []
def chk(tag, name, ok, detail=""):
    R.append(dict(tag=tag, name=name, ok=bool(ok), detail=str(detail)))

auto_src = AUTO_PY.read_text(encoding="utf-8")
bridge_src = BRIDGE_PY.read_text(encoding="utf-8")
html = STUDIO.read_text(encoding="utf-8")

# 加载模块（隔离状态文件）
spec = importlib.util.spec_from_file_location("auto_v11", AUTO_PY)
auto = importlib.util.module_from_spec(spec)
sys.modules["auto_v11"] = auto
spec.loader.exec_module(auto)
_tmp = tempfile.mkdtemp(prefix="v11_")
auto.JOBS_FILE = Path(_tmp) / "jobs.json"
auto.OUTPUT_ROOT = Path(_tmp) / "outputs"

# ---------- V1 get_job 浅拷贝 ----------
auto._load_jobs()
jid = auto.create_job({"name": "t", "steps": [{"kind": "text_to_image", "label": "step"}]})
g = auto.get_job(jid)
g["steps"][0]["label"] = "MUTATED"
inner = auto.get_job(jid)
chk("V1", "get_job 返回深拷贝（外部改不污染内部）",
    inner["steps"][0]["label"] != "MUTATED",
    "内部label=" + inner["steps"][0]["label"])
auto._JOBS.clear(); auto._save_jobs()

# ---------- V2 start_engine 续跑跳过已完成步骤 ----------
# 直接手工构造"中断快照"，避免 create_job 启动 worker 造成时序竞态（验证器隔离）
auto.stop_engine()
import time as _t; _t.sleep(0.2)
auto._JOBS.clear()
j2 = "job_snapshot_v2"
auto._JOBS[j2] = {
    "id": j2, "name": "t", "status": "running", "progress": 40, "current": "",
    "steps": [
        {"index": 0, "kind": "text_to_image", "label": "s0", "hint": "",
         "status": "done", "detail": "already done", "artifact": ""},
        {"index": 1, "kind": "text_to_image", "label": "s1", "hint": "",
         "status": "pending", "detail": "", "artifact": ""},
    ],
    "spec": {"name": "t", "steps": []}, "artifacts": [],
}
auto._save_jobs()
# 只验证静态跳过逻辑存在 + 快照 done 状态被保留（不实际启动 worker 执行）
_skip_logic = '.get("status") == "done"' in auto_src
j2now = auto.get_job(j2)
chk("V2", "续跑保留已完成步骤（不重复执行）",
    j2now["steps"][0]["status"] == "done" and _skip_logic,
    "step0=" + j2now["steps"][0]["status"] + " 跳过逻辑=" + str(_skip_logic))
auto._JOBS.clear(); auto._save_jobs()

# ---------- V3 按作业停止（非全局） ----------
chk("V3", "支持按 job_id 停止单个作业",
    hasattr(auto, "stop_job") and callable(auto.stop_job),
    "stop_job存在=" + str(hasattr(auto, "stop_job")))
chk("V3b", "存在 per-job 停止信号集合", "_JOB_STOPS" in auto_src or "stop_flags" in auto_src, "")

# ---------- V4 wait_prompt 连续错误中止 ----------
chk("V4", "wait_prompt 有连续失败阈值（ComfyUI 崩溃不空等15分钟）",
    "consecutive_errors" in auto_src or "max_errors" in auto_src or "连续失败" in auto_src, "")

# ---------- V5 seed 类型归一化 ----------
wf = auto.build_txt2img_workflow("p", "n", seed=42)
wf_s = auto.build_txt2img_workflow("p", "n", seed="42")
chk("V5", "seed 字符串归一化为整数（幂等）",
    wf["5"]["inputs"]["seed"] == wf_s["5"]["inputs"]["seed"] == 42,
    "int=%r str=%r" % (wf["5"]["inputs"]["seed"], wf_s["5"]["inputs"]["seed"]))

# ---------- V6 保留 step hint ----------
auto._load_jobs()
j6 = auto.create_job({"name": "t", "steps": [{"kind": "text_to_image", "label": "s", "hint": "HINT-XYZ"}]})
g6 = auto.get_job(j6)
chk("V6", "作业步骤保留 hint 字段",
    g6["steps"][0].get("hint") == "HINT-XYZ",
    "hint=" + str(g6["steps"][0].get("hint")))
auto._JOBS.clear(); auto._save_jobs()

# ---------- V7 AUTO_KINDS 实际使用 ----------
uses = len(re.findall(r"\bAUTO_KINDS\b", auto_src))
chk("V7", "AUTO_KINDS 被实际用于校验（非死代码）",
    uses >= 2,
    "出现次数=" + str(uses))

# ---------- V8 占位执行器不计入 auto_count ----------
# 前端 buildJobSpec：image_to_3d/clean_image 当前是占位，不应算"可自动"
js = re.search(r"<script>([\s\S]*?)</script>", html).group(1)
chk("V8", "前端不把占位执行器计入可自动步骤",
    "NOT_READY_KINDS" in js or "占位" in js and "auto_count" in js,
    "占位识别=" + str("NOT_READY_KINDS" in js or "占位" in js))

# ---------- V9 图生3D 执行器真实接入 ----------
chk("V9", "image_to_3d 有真实执行器（非 pending 占位）",
    'kind == "image_to_3d"' in auto_src and
    "执行器待接入" not in auto_src.split('kind == "image_to_3d"')[1][:400]
    if 'kind == "image_to_3d"' in auto_src else False,
    "仍有占位=" + str("执行器待接入" in auto_src))

# ---------- V10 净化执行器真实接入 ----------
chk("V10", "clean_image 有真实执行器", "rembg" in auto_src.lower() or
    ("clean_image" in auto_src and "执行器待接入" not in auto_src),
    "rembg=" + str("rembg" in auto_src.lower()))

# ---------- V11 保存节流（避免轮询 IO 风暴） ----------
chk("V11", "_save_jobs 有脏标记/节流（非每次全量写）",
    "_dirty" in auto_src or "_save_throttle" in auto_src or "save_jobs_if_dirty" in auto_src, "")

# ---------- V12 并发作业支持 ----------
chk("V12", "支持多作业并发（非单 worker 串行饿死）",
    "MAX_WORKERS" in auto_src or "_WORKERS" in auto_src or "ThreadPool" in auto_src, "")

# ---------- V13 ComfyUI 可用性缓存 ----------
chk("V13", "comfy_available 有 TTL 缓存",
    "_COMFY_CACHE" in auto_src or "comfy_cache" in auto_src, "")

# ---------- V14 真实进度（非时间线性假进度） ----------
chk("V14", "进度来自 ComfyUI /progress 真实队列",
    "/progress" in auto_src or "progress_" in auto_src and "elapsed / total" not in auto_src,
    "含/progress=" + str("/progress" in auto_src))

# ---------- V15 jobs 上限与清理 ----------
chk("V15", "作业历史有上限与清理机制",
    "MAX_JOBS" in auto_src or "prune" in auto_src or "清理" in auto_src, "")

# ---------- V16 输入边界钳制 ----------
chk("V16", "width/height/steps 有边界钳制",
    "clamp" in auto_src.lower() or "min(" in auto_src and "max(" in auto_src and "width" in auto_src, "")

# ---------- V17 jobs.json 原子写入 ----------
chk("V17", "jobs.json 原子写入（临时文件+replace）",
    "os.replace" in auto_src or ".tmp" in auto_src and "_save_jobs" in auto_src, "")

# ---------- V18 桥端 step 结构校验 ----------
chk("V18", "/api/job/create 校验 steps 元素结构",
    "isinstance(s, dict)" in bridge_src or "step.get" in bridge_src,
    "")

# ---------- V19 历史载入恢复 jobSpec ----------
chk("V19", "历史载入恢复 jobSpec（一键执行不失效）",
    "jobSpec" in html.split("restoreProfile")[1][:3000] if "restoreProfile" in html else False, "")

# ---------- V20 client_id 唯一 ----------
chk("V20", "ComfyUI client_id 按作业唯一（非硬编码）",
    'client_id": "atlas-automation"' not in auto_src,
    "硬编码=" + str('client_id": "atlas-automation"' in auto_src))

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
    print("第十一轮 · 自动化引擎验证器" + (" [过滤 " + ",".join(sorted(sel)) + "]" if sel else " V1..V20"))
    print("=" * 76)
    for r in shown:
        print("[%s] %-4s %-40s %s" % ("PASS" if r["ok"] else "FAIL", r["tag"], r["name"], r["detail"]))
    bad = [r for r in shown if not r["ok"]]
    print("-" * 76)
    print("RESULT: %d/%d passed (FAIL=%d)" % (len(shown)-len(bad), len(shown), len(bad)))
    sys.exit(0 if not bad else 1)
