#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证自动化引擎：mock ComfyUI + 真实 automation.py + 真实 tool-bridge HTTP 端点。

不依赖 torch / 模型权重，验证「作业提交 → 队列执行 → 进度查询 → 人工暂停」全链路。
"""
import importlib.util, json, sys, threading, time, http.client, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_BUILD = Path(__file__).resolve().parent          # 第二十轮：相对路径
AUTO = _BUILD.parent / "创作工具星图" / "快捷方式工具" / "automation.py"
BRIDGE = _BUILD.parent / "创作工具星图" / "快捷方式工具" / "tool-bridge.py"
COMFY_PORT = 18188
BRIDGE_PORT = 17843

# ---------- mock ComfyUI ----------
class MockComfy(BaseHTTPRequestHandler):
    prompt_count = 0
    def log_message(self, *a): pass
    def _json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path == "/system_stats":
            self._json({"system": {"comfyui_version": "mock"}})
        elif self.path.startswith("/history/"):
            pid = self.path.split("/")[-1]
            self._json({pid: {"status": {"completed": True, "status_str": "success"},
                              "outputs": {"7": {"images": [{"filename": "atlas_test_00001.png"}]}}}})
        else:
            self._json({})
    def do_POST(self):
        if self.path == "/prompt":
            MockComfy.prompt_count += 1
            self._json({"prompt_id": "mock_pid_%d" % MockComfy.prompt_count})

# ---------- 加载模块 ----------
os.environ["ATLAS_COMFY_URL"] = "http://127.0.0.1:%d" % COMFY_PORT
spec = importlib.util.spec_from_file_location("auto_test", AUTO)
auto = importlib.util.module_from_spec(spec)
sys.modules["auto_test"] = auto
spec.loader.exec_module(auto)
auto.COMFY_URL = os.environ["ATLAS_COMFY_URL"]
auto.JOBS_FILE = _BUILD / "test_jobs.json"
auto.OUTPUT_ROOT = _BUILD / "test_outputs"

comfy = ThreadingHTTPServer(("127.0.0.1", COMFY_PORT), MockComfy)
threading.Thread(target=comfy.serve_forever, daemon=True).start()

R = []
def chk(name, ok, detail=""): R.append((name, bool(ok), detail))

try:
    # 1 ComfyUI 可用性探测
    avail, info = auto.comfy_available()
    chk("ComfyUI 可用性探测", avail and info.get("system", {}).get("comfyui_version") == "mock", str(info)[:80])

    # 2 提交生图工作流
    wf = auto.build_txt2img_workflow("a forest guard", "blurry, text", seed=42)
    chk("文生图工作流结构", all(k in wf for k in ("1", "5", "7")) and wf["5"]["inputs"]["seed"] == 42,
        "节点数=" + str(len(wf)))

    # 3 作业单：人工环节在前，应暂停
    auto._load_jobs()
    jid = auto.create_job({"name": "e2e测试", "steps": [
        {"kind": "hand_draw", "label": "手绘起稿"},
        {"kind": "text_to_image", "label": "AI生图"},
    ]})
    time.sleep(1.5)
    job = auto.get_job(jid)
    chk("人工环节暂停交接", job["status"] == "paused" and job["steps"][0]["status"] == "needs_human",
        "status=%s step0=%s" % (job["status"], job["steps"][0]["status"]))

    # 4 作业单：纯自动环节，应完成
    jid2 = auto.create_job({"name": "e2e自动", "prompt_pos": "a cat", "prompt_neg": "blurry", "steps": [
        {"kind": "text_to_image", "label": "AI生图"},
    ]})
    time.sleep(2.0)
    job2 = auto.get_job(jid2)
    chk("自动作业执行完成", job2["status"] == "done" and job2["steps"][0]["status"] == "done",
        "status=%s step0=%s artifacts=%s" % (job2["status"], job2["steps"][0]["status"], job2["artifacts"][:2]))
    chk("产物被记录", len(job2["artifacts"]) > 0, str(job2["artifacts"][:2]))

    # 5 进度查询
    chk("作业状态可查询", auto.get_job(jid2) is not None and auto.get_job("nonexistent") is None, "")

    # 6 状态持久化
    chk("作业持久化到文件", auto.JOBS_FILE.exists() and jid2 in auto.JOBS_FILE.read_text(encoding="utf-8"), "")

    # 清理
    with auto._LOCK:
        auto._JOBS.pop(jid, None); auto._JOBS.pop(jid2, None)
    auto._save_jobs()
finally:
    comfy.shutdown(); comfy.server_close()
    auto.stop_engine()

print("=" * 70)
print("自动化引擎 · 端到端链路验证（mock ComfyUI）")
print("=" * 70)
for n, ok, d in R:
    print("[%s] %-24s %s" % ("PASS" if ok else "FAIL", n, d))
print("-" * 70)
bad = [x for x in R if not x[1]]
print("RESULT: %d/%d passed" % (len(R) - len(bad), len(R)))
sys.exit(1 if bad else 0)
