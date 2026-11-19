#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实图生3D 测试：启动 ComfyUI -> 加载 TRELLIS.2 -> 用已有图片生成 GLB。"""
import json, subprocess, sys, time, urllib.request, shutil
from pathlib import Path

PORT = 8188
BASE = "http://127.0.0.1:%d" % PORT
PORTABLE = Path("I:/workbuddy/AI-Engine/portable/ComfyUI_windows_portable")
PY = PORTABLE / "python_embeded" / "python.exe"
MAIN = PORTABLE / "ComfyUI" / "main.py"
IMG = PORTABLE / "ComfyUI" / "output" / "atlas_test_00001_.png"
INPUT = PORTABLE / "ComfyUI" / "input"
OUT = PORTABLE / "ComfyUI" / "output"
WF_PATH = Path("I:/workbuddy/AI-Engine/workflow_pixal3d_schema_api.json")  # 第十二轮：用修复后的转换结果


def api_get(path, timeout=5):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(path, payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    # 轮9：必须在 ComfyUI 启动前把图片放进 input 目录——ComfyUI 启动时扫描文件列表，
    # 之后才复制的文件不在列表里，LoadImage 会报 "Invalid image file"。
    # 第十二轮：根因修复——8188 若已被别的 ComfyUI 占着（如源码克隆版 AI-Engine/ComfyUI，
    # 它的 models/ 为空、input/ 只有 example.png），新进程绑不上端口，脚本却会连上旧服务，
    # 于是出现 UNETLoader 选项为 []、LoadImage "Invalid image file"。启动前先查端口。
    try:
        api_get("/system_stats", timeout=2)
        print("PORT_BUSY: 8188 已有 ComfyUI 在运行（可能是旧的源码克隆版）。请先关闭它再重跑。", flush=True)
        return 2
    except Exception:
        pass
    INPUT.mkdir(parents=True, exist_ok=True)
    # 轮9：用简单文件名——ComfyUI LoadImage 对含连续/结尾下划线的名字校验失败
    INPUT_NAME = "atlas_input.png"
    shutil.copy2(str(IMG), str(INPUT / INPUT_NAME))
    print("input image ready (before ComfyUI start)", flush=True)
    log = open("I:/workbuddy/.creative-atlas-build/comfy_to3d.log", "w", encoding="utf-8")
    proc = subprocess.Popen([str(PY), "-u", str(MAIN), "--listen", "127.0.0.1", "--port", str(PORT)],
                            cwd=str(PORTABLE), stdout=log, stderr=subprocess.STDOUT)
    try:
        for i in range(60):
            try:
                api_get("/system_stats", timeout=3)
                if proc.poll() is not None:
                    print("OUR_COMFY_EXITED code=%s（看 comfy_to3d.log）" % proc.returncode, flush=True); return 1
                print("ComfyUI READY", flush=True); break
            except Exception: time.sleep(2)
        else:
            print("COMFY_NOT_READY", flush=True); return 1

        wf = json.loads(WF_PATH.read_text(encoding="utf-8"))
        # 模型名映射
        # 第十二轮：官方模型已补齐，不再用 trellis_2 / dino_v3_vit_l / pixel_space 顶替；
        # 只保留一处真实的命名差异（UI 工作流里 MoGe 是连字符旧名）
        mapping = {"moge-2-vitl-normal_fp16.safetensors": "moge_2_vitl_normal_fp16.safetensors"}
        for n in wf.values():
            for k in ("ckpt_name", "unet_name", "clip_name", "vae_name", "model_name", "bg_removal_name"):
                v = n.get("inputs", {}).get(k)
                if isinstance(v, str) and v in mapping:
                    n["inputs"][k] = mapping[v]
            if n.get("class_type") == "LoadImage":
                n["inputs"]["image"] = INPUT_NAME
            if n.get("class_type") in ("SaveGLB", "Save3DAdvanced"):
                n["inputs"]["filename_prefix"] = "3d/real_test"
        # 旁路未安装的背景移除模型
        # 第十二轮：birefnet 已补下载，默认不再旁路背景移除（设环境变量 ATLAS_BYPASS_BG=1 可恢复旁路）
        BYPASS_BG = __import__("os").environ.get("ATLAS_BYPASS_BG") == "1"
        load_id = next((k for k, v in wf.items() if v.get("class_type") == "LoadImage"), None)
        rm_ids = {k for k, v in wf.items() if v.get("class_type") == "RemoveBackground"}
        for n in wf.values():
            if n.get("class_type") == "ComfySwitchNode":
                t = n["inputs"].get("on_true")
                if BYPASS_BG and isinstance(t, list) and t[0] in rm_ids and load_id:
                    n["inputs"]["on_true"] = [load_id, 0]

        # 第十二轮：提交前预检——确认连上的是装了模型的那份 ComfyUI，并列出所有缺失模型
        oi = api_get("/object_info", timeout=30)
        missing = []
        # 只检查从输出节点可达的节点（与 ComfyUI 自身校验范围一致；被旁路的节点不算）
        reach, stack = set(), [k for k, v in wf.items() if oi.get(v["class_type"], {}).get("output_node")]
        while stack:
            k = stack.pop()
            if k in reach or k not in wf: continue
            reach.add(k)
            stack += [v[0] for v in wf[k].get("inputs", {}).values() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str)]
        # 第十二轮：保存服务器实时 schema，供转换器后续使用（旧快照可能与运行版本不一致）
        Path("I:/workbuddy/AI-Engine/object_info_live.json").write_text(
            json.dumps(oi, ensure_ascii=False), encoding="utf-8")
        # 第十二轮：必填参数完整性检查（含 DynamicCombo 子参数，键名形如 sign_mode.qef）
        for nid in reach:
            n = wf[nid]
            req = oi.get(n["class_type"], {}).get("input", {}).get("required", {})
            for k, spec in req.items():
                if k not in n.get("inputs", {}):
                    missing.append((nid, n["class_type"], k, "<缺少必填参数>", []))
                elif isinstance(spec, list) and spec and spec[0] == "COMFY_DYNAMICCOMBO_V3":
                    opt = next((o for o in spec[1].get("options", []) if o.get("key") == n["inputs"][k]), None)
                    for sk in (opt or {}).get("inputs", {}).get("required", {}):
                        if k + "." + sk not in n["inputs"]:
                            missing.append((nid, n["class_type"], k + "." + sk, "<缺少动态子参数>", []))
        for nid, n in ((k, wf[k]) for k in reach):
            req = oi.get(n["class_type"], {}).get("input", {})
            specs = dict(req.get("required", {})); specs.update(req.get("optional", {}))
            for k, v in n.get("inputs", {}).items():
                spec = specs.get(k)
                if isinstance(v, str) and isinstance(spec, list) and spec:
                    opts = spec[0] if isinstance(spec[0], list) else (spec[1].get("options") if spec[0] == "COMBO" and len(spec) > 1 else None)
                    if opts is not None and v not in opts:
                        missing.append((nid, n["class_type"], k, v, list(opts)[:6]))
        unet_opts = oi.get("UNETLoader", {}).get("input", {}).get("required", {}).get("unet_name", [[]])[0]
        print("SERVER_UNET_OPTIONS=%s" % unet_opts, flush=True)
        if missing:
            for m in missing: print("PREFLIGHT_MISSING", m, flush=True)
            print("PREFLIGHT_FAIL: %d 个输入值不在服务器可选列表里" % len(missing), flush=True)
            return 1
        print("submit workflow (%d nodes)..." % len(wf), flush=True)
        try:
            res = api_post("/prompt", {"prompt": wf, "client_id": "atlas_to3d_test"})
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")[:800]
            print("SUBMIT_HTTP_ERROR %d: %s" % (e.code, body), flush=True)
            return 1
        pid = res.get("prompt_id")
        if not pid:
            print("SUBMIT_FAIL: %s" % str(res)[:500], flush=True); return 1
        print("prompt_id=%s" % pid, flush=True)

        t0 = time.time()
        while time.time() - t0 < 2400:  # 第十二轮：bf16 首次加载+烘焙较慢，放宽到 40 分钟
            hist = api_get("/history/" + pid, timeout=5)
            node = hist.get(pid)
            if node and node.get("status", {}).get("completed"):
                arts = []
                for o in node.get("outputs", {}).values():
                    arts += [g.get("filename") for g in (o.get("gifs", []) + o.get("images", []))]
                print("DONE %.0fs arts=%s" % (time.time() - t0, arts[:5]), flush=True)
                # 第十二轮：SaveGLB 的输出字段名不是 images/gifs，直接扫 output/3d 下本次生成的 GLB
                found = [p for p in (OUT / "3d").glob("real_test*.glb") if p.stat().st_mtime >= t0 - 5]
                print("GLB_FILES=%s" % [(str(p), p.stat().st_size) for p in found], flush=True)
                print("REAL_TO3D_OK" if found else "NO_GLB", flush=True)
                return 0 if found else 1
            if node and node.get("status", {}).get("status_str") == "error":
                print("COMFY_ERROR: %s" % json.dumps(node.get("status"), ensure_ascii=False)[:600], flush=True)
                return 1
            time.sleep(3)
        print("TIMEOUT", flush=True); return 1
    finally:
        proc.terminate()
        try: proc.wait(timeout=15)
        except Exception: proc.kill()
        log.close()


if __name__ == "__main__":
    sys.exit(main())
