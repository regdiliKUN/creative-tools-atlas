# -*- coding: utf-8 -*-
"""Atlas 工坊面板 —— 让 Krita 成为创作工坊的主操作界面（创作工具星图 第十八轮）。

面板做四件事：
  ① 接手工坊作业：读工具桥目录下的 krita_session.json。方案A 时把图分层打开——
     底层「AI 原图」锁定，上面一层空白「我的修改」，另存为同名 .kra；
  ② 「完成，回传工坊」：保存 .kra、导出 PNG，调用工具桥让作业继续，不用回浏览器；
  ③ 「AI 精修当前画布」「AI 去背景」：直接调本机 ComfyUI，结果作为新图层 / 透明蒙版放回画布，
     删掉图层或关掉蒙版即可撤销，原图层不动；
  ④ 提示词在面板里改，可以保存回作业，后续步骤沿用。

和工坊的通信：
  - 会话文件 <bridge_dir>/krita_session.json（引擎写，面板读；面板处理后写 krita_session.ack）
  - 工具桥 http://127.0.0.1:7843，面板令牌在 <bridge_dir>/.krita_token（工具桥每次启动更换）
  - ComfyUI http://127.0.0.1:8188（上传 → /prompt → /history → /view）
bridge_dir 由安装脚本写进本目录 atlas_config.json。

网络请求都在后台线程里跑，结果由主线程 QTimer 取回再改画布（Krita 对象只能在主线程碰）。
"""
import json, os, threading, time, traceback, uuid, urllib.request, urllib.parse, urllib.error

from krita import Krita, DockWidget, DockWidgetFactory, DockWidgetFactoryBase, InfoObject
try:
    from PyQt5.QtCore import QTimer, Qt, QByteArray
    from PyQt5.QtGui import QImage
    from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
                                 QSlider, QGroupBox, QDockWidget, QScrollArea, QFrame)
except ImportError:  # Krita 6 (Qt6)
    from PyQt6.QtCore import QTimer, Qt, QByteArray
    from PyQt6.QtGui import QImage
    from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
                                 QSlider, QGroupBox, QDockWidget, QScrollArea, QFrame)

HERE = os.path.dirname(os.path.abspath(__file__))
DOCKER_ID = "atlas_studio_docker"
FMT_ARGB32 = getattr(QImage, "Format_ARGB32", None) or QImage.Format.Format_ARGB32
FMT_GRAY8 = getattr(QImage, "Format_Grayscale8", None) or QImage.Format.Format_Grayscale8


def _cfg():
    try:
        with open(os.path.join(HERE, "atlas_config.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _norm(p):
    return os.path.normcase(os.path.abspath(p or ""))


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def _img_bytes(img, fmt):
    """QImage → 紧凑字节（去掉每行的对齐填充）。"""
    img = img.convertToFormat(fmt)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    bpp = 4 if fmt == FMT_ARGB32 else 1
    ptr = img.constBits()
    ptr.setsize(bpl * h)
    raw = bytes(ptr)
    if bpl == w * bpp:
        return raw
    return b"".join(raw[y * bpl:y * bpl + w * bpp] for y in range(h))


# ------------------------------------------------------------------ ComfyUI 客户端（后台线程用）
class Comfy:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def _req(self, path, data=None, headers=None, timeout=30):
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()

    def upload(self, png_path):
        name = "atlas_krita_%s.png" % uuid.uuid4().hex[:8]
        boundary = "----atlas" + uuid.uuid4().hex
        with open(png_path, "rb") as f:
            payload = f.read()
        body = (("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\n"
                 "Content-Type: image/png\r\n\r\n" % (boundary, name)).encode("utf-8") + payload +
                ("\r\n--%s\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--%s--\r\n"
                 % (boundary, boundary)).encode("utf-8"))
        res = json.loads(self._req("/upload/image", body,
                                   {"Content-Type": "multipart/form-data; boundary=" + boundary}, 60))
        return res.get("name", name)

    def run(self, workflow, on_tick=None, timeout=900):
        res = json.loads(self._req("/prompt", json.dumps({"prompt": workflow, "client_id": "atlas-krita"}).encode("utf-8"),
                                   {"Content-Type": "application/json"}))
        if res.get("node_errors"):
            raise RuntimeError("ComfyUI 工作流校验失败：" + json.dumps(res["node_errors"], ensure_ascii=False)[:300])
        pid = res["prompt_id"]
        t0 = time.time()
        while time.time() - t0 < timeout:
            time.sleep(1.0)
            h = json.loads(self._req("/history/" + pid, timeout=10)).get(pid)
            if h and h.get("status", {}).get("status_str") == "error":
                raise RuntimeError("ComfyUI 执行出错：" + json.dumps(h.get("status"), ensure_ascii=False)[:300])
            if h and h.get("status", {}).get("completed"):
                for node in h.get("outputs", {}).values():
                    for im in node.get("images", []):
                        q = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                    "type": im.get("type", "output")})
                        return self._req("/view?" + q, timeout=60)
                raise RuntimeError("ComfyUI 完成了，但没有输出图片")
            if on_tick:
                on_tick(int(time.time() - t0))
        raise RuntimeError("等待 ComfyUI 超时")


def wf_refine(image, pos, neg, denoise, ckpt, seed):
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": pos, "clip": ["3", 1]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": neg, "clip": ["3", 1]}},
        "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["3", 2]}},
        "7": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 20, "cfg": 6.0, "sampler_name": "euler",
                                                    "scheduler": "normal", "denoise": denoise, "model": ["3", 0],
                                                    "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "atlas/krita_refine"}},
    }


def wf_mask(image):
    # RemoveBackground 输出"前景=1"的遮罩；转成灰度图：白=保留，黑=透明，正好是 Krita 透明蒙版的含义
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": image}},
        "2": {"class_type": "LoadBackgroundRemovalModel", "inputs": {"bg_removal_name": "birefnet.safetensors"}},
        "3": {"class_type": "RemoveBackground", "inputs": {"bg_removal_model": ["2", 0], "image": ["1", 0]}},
        "4": {"class_type": "MaskToImage", "inputs": {"mask": ["3", 0]}},
        "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": "atlas/krita_mask"}},
    }


# ------------------------------------------------------------------ 面板
class AtlasStudioDocker(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Atlas 工坊")
        self.cfg = _cfg()
        self.bridge_dir = self.cfg.get("bridge_dir", "")
        self.session = None
        self.session_mtime = 0
        self._job = None            # 后台任务：{"kind","thread","result","error","msg"}
        self._build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(1500)
        QTimer.singleShot(800, self._poll)

    # -------------------------------------------------------------- UI
    def _build_ui(self):
        root = QWidget()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(6, 6, 6, 6)

        g1 = QGroupBox("① 工坊作业")
        l1 = QVBoxLayout(g1)
        self.lbl_job = QLabel("还没有工坊作业。下面的 AI 工具可以直接处理当前画布。")
        self.lbl_job.setWordWrap(True)
        l1.addWidget(self.lbl_job)
        # 第十八轮修正：面板常被挤在右侧窄栏里，按钮一行一个、占满宽度，避免文字被截断
        self.btn_done = QPushButton("✓ 完成，回传工坊")
        self.btn_done.setStyleSheet("font-weight:bold;padding:6px")
        self.btn_done.clicked.connect(self._handback)
        self.btn_reopen = QPushButton("重新打开这张图")
        self.btn_reopen.clicked.connect(self._reopen)
        l1.addWidget(self.btn_done)
        l1.addWidget(self.btn_reopen)
        lay.addWidget(g1)

        g2 = QGroupBox("② AI 工具（作用于当前画布）")
        l2 = QVBoxLayout(g2)
        l2.addWidget(QLabel("正向提示词："))
        self.ed_pos = QPlainTextEdit()
        self.ed_pos.setFixedHeight(64)
        l2.addWidget(self.ed_pos)
        l2.addWidget(QLabel("反向提示词："))
        self.ed_neg = QPlainTextEdit()
        self.ed_neg.setFixedHeight(48)
        self.ed_neg.setPlainText("lowres, blurry, jpeg artifacts, watermark, text, bad anatomy")
        l2.addWidget(self.ed_neg)
        self.btn_save_prompt = QPushButton("把提示词保存到作业")
        self.btn_save_prompt.clicked.connect(self._save_prompt)
        l2.addWidget(self.btn_save_prompt)
        srow = QHBoxLayout()
        self.lbl_str = QLabel()
        self.sld = QSlider(Qt.Horizontal if hasattr(Qt, "Horizontal") else Qt.Orientation.Horizontal)
        self.sld.setRange(10, 80)
        self.sld.setValue(35)
        self.sld.valueChanged.connect(self._str_label)
        self._str_label()
        srow.addWidget(self.lbl_str)
        srow.addWidget(self.sld)
        l2.addLayout(srow)
        self.btn_refine = QPushButton("✨ AI 精修当前画布 → 新图层")
        self.btn_refine.clicked.connect(self._refine)
        l2.addWidget(self.btn_refine)
        self.btn_bg = QPushButton("✂ AI 去背景 → 透明蒙版")
        self.btn_bg.clicked.connect(self._remove_bg)
        l2.addWidget(self.btn_bg)
        tip = QLabel("结果都是新加的图层 / 蒙版，原图层不动：不满意就删掉那个图层，或在图层面板里关掉蒙版。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:gray;font-size:11px")
        l2.addWidget(tip)
        lay.addWidget(g2)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        lay.addStretch(1)
        for b in (self.btn_refine, self.btn_bg, self.btn_save_prompt):
            b.setMinimumHeight(28)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame if hasattr(QFrame, "NoFrame") else QFrame.Shape.NoFrame)
        sc.setWidget(root)
        self.setWidget(sc)
        self._sync_buttons()

    def _str_label(self):
        v = self.sld.value()
        self.lbl_str.setText("精修强度 %.2f（越大改得越多）" % (v / 100.0))

    def say(self, msg, err=False):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet("color:%s" % ("#e0884a" if err else "#4caf7a"))
        try:
            v = Krita.instance().activeWindow().activeView()
            if v:
                v.showFloatingMessage(msg[:120], self.windowIcon(), 3000, 1)
        except Exception:
            pass

    def _sync_buttons(self):
        s = self.session or {}
        busy = self._job is not None
        edit = s.get("mode") == "edit" and not s.get("_handed_back")
        self.btn_done.setVisible(edit)
        self.btn_reopen.setVisible(s.get("mode") in ("edit", "paint"))
        self.btn_done.setEnabled(not busy)
        self.btn_refine.setEnabled(not busy)
        self.btn_bg.setEnabled(not busy)
        self.btn_save_prompt.setEnabled(bool(s.get("jid")) and not busy)

    def canvasChanged(self, canvas):
        pass

    # -------------------------------------------------------------- 会话
    def _session_path(self):
        return os.path.join(self.bridge_dir, "krita_session.json") if self.bridge_dir else ""

    def _poll(self):
        self._poll_job()
        p = self._session_path()
        if not p or not os.path.isfile(p):
            return
        mt = os.path.getmtime(p)
        if mt == self.session_mtime:
            self._paint_progress()
            return
        self.session_mtime = mt
        s = _read_json(p)
        if not s or not s.get("id"):
            return
        ack = _read_json(p.replace(".json", ".ack")) or {}
        first_time = ack.get("id") != s.get("id")
        self.session = s
        if s.get("prompt_pos"):
            self.ed_pos.setPlainText(s.get("prompt_pos", ""))
        if s.get("prompt_neg"):
            self.ed_neg.setPlainText(s.get("prompt_neg", ""))
        if s.get("mode") == "edit":
            self.lbl_job.setText("方案A · 在 Krita 里修改\n在「我的修改」层上画（「AI 原图」已锁定）。\n改完点下面的「✓ 完成，回传工坊」。")
            self.lbl_job.setToolTip("作业：%s\n文件：%s" % (s.get("job_name", ""), s.get("kra", "")))
            if first_time:
                self._show_self()
                self._open_layered(s)
                _write_json(p.replace(".json", ".ack"), {"id": s["id"], "opened": time.strftime("%H:%M:%S")})
        elif s.get("mode") == "paint":
            if first_time:
                self._show_self()
                _write_json(p.replace(".json", ".ack"), {"id": s["id"], "opened": time.strftime("%H:%M:%S")})
            self._paint_progress()
        self._sync_buttons()

    def _paint_progress(self):
        s = self.session or {}
        if s.get("mode") != "paint":
            return
        done = _read_json(s.get("done_file", "")) if os.path.isfile(s.get("done_file", "")) else None
        if done:
            self.lbl_job.setText("作业「%s」· 方案C：AI 逐笔作画%s\n分层画稿：%s\n可以直接在上面接着画，或用下面的 AI 工具精修 / 去背景；下一步怎么做回工坊页面选。"
                                 % (s.get("job_name", ""), "完成" if done.get("ok") else "出错",
                                    os.path.basename(s.get("kra", ""))))
            return
        pr = _read_json(s.get("progress_file", "")) or {}
        self.lbl_job.setText("作业「%s」· 方案C：AI 正在逐笔作画\n%s：%s / %s 笔（%ss）\n画完之前不要关闭这幅画。"
                             % (s.get("job_name", ""), pr.get("layer", "准备中"), pr.get("painted", 0),
                                pr.get("total", "?"), pr.get("elapsed", 0)))

    def _show_self(self):
        try:
            self.show()
            self.raise_()
        except Exception:
            pass

    def _find_doc(self, path):
        for d in Krita.instance().documents():
            if _norm(d.fileName()) == _norm(path):
                return d
        return None

    def _open_layered(self, s):
        """方案A：把图分层打开——底层「AI 原图」锁定，上面一层空白「我的修改」，另存为 .kra。"""
        app = Krita.instance()
        kra, img = s.get("kra", ""), s.get("image", "")
        try:
            doc = self._find_doc(kra)
            if doc is None and os.path.isfile(kra):
                doc = app.openDocument(kra)
            fresh = False
            if doc is None:
                doc = app.openDocument(img)
                if doc is None:
                    raise RuntimeError("Krita 打不开 " + img)
                fresh = True
            win = app.activeWindow() or (app.windows()[0] if app.windows() else None)
            if win is None:
                raise RuntimeError("Krita 窗口还没准备好")
            view = next((v for v in win.views() if v.document() == doc), None) or win.addView(doc)
            if fresh:
                root = doc.rootNode()
                base = root.childNodes()[-1]
                base.setName("AI 原图")
                mine = doc.createNode("我的修改", "paintlayer")
                root.addChildNode(mine, base)
                base.setLocked(True)
                doc.setBatchmode(True)
                try:
                    doc.saveAs(kra)
                finally:
                    doc.setBatchmode(False)
                QTimer.singleShot(200, lambda: doc.setActiveNode(mine))
            self.say("已分层打开 %s：在「我的修改」层上画。" % os.path.basename(kra))
        except Exception as e:
            self.say("分层打开失败：%s" % e, True)

    def _reopen(self):
        s = self.session or {}
        if s.get("mode") == "edit":
            self._open_layered(s)
        elif s.get("kra") and os.path.isfile(s["kra"]):
            app = Krita.instance()
            doc = self._find_doc(s["kra"]) or app.openDocument(s["kra"])
            if doc and app.activeWindow():
                app.activeWindow().addView(doc)

    # -------------------------------------------------------------- 回传 / 提示词
    def _bridge_post(self, path, body=None):
        tok_file = os.path.join(self.bridge_dir, ".krita_token")
        try:
            with open(tok_file, encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            raise RuntimeError("找不到工具桥令牌：请先双击 %s 启动工具桥"
                               % os.path.join(self.bridge_dir, "start-all.bat"))
        url = self.cfg.get("bridge_url", "http://127.0.0.1:7843") + path
        req = urllib.request.Request(url, data=json.dumps(body or {}).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "X-Atlas-Plugin": token})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return json.loads(e.read().decode("utf-8") or "{}") or {"ok": False, "message": str(e)}
        except urllib.error.URLError:
            raise RuntimeError("连不上工具桥：请先双击 %s" % os.path.join(self.bridge_dir, "start-all.bat"))

    def _handback(self):
        s = self.session or {}
        if s.get("mode") != "edit":
            return
        doc = self._find_doc(s.get("kra", "")) or Krita.instance().activeDocument()
        if doc is None:
            self.say("找不到这幅画：点「重新打开这张图」后再回传。", True)
            return
        try:
            doc.setBatchmode(True)
            try:
                if _norm(doc.fileName()) == _norm(s["kra"]):
                    doc.save()
                else:
                    doc.saveAs(s["kra"])
                doc.exportImage(s["png"], InfoObject())
            finally:
                doc.setBatchmode(False)
            r = self._bridge_post("/api/job/resume?id=" + urllib.parse.quote(s["jid"]))
            if r.get("ok"):
                s["_handed_back"] = True
                self.lbl_job.setText("作业「%s」：已回传，工坊正在继续执行。\n结果在工坊页面上看；想接着加工，在页面上选下一个方案。"
                                     % s.get("job_name", ""))
                self.say("已回传工坊：%s" % os.path.basename(s["png"]))
            else:
                self.say("回传失败：%s" % (r.get("message") or r.get("error")), True)
        except Exception as e:
            self.say("回传失败：%s" % e, True)
        self._sync_buttons()

    def _save_prompt(self):
        s = self.session or {}
        if not s.get("jid"):
            return
        try:
            r = self._bridge_post("/api/job/spec?id=" + urllib.parse.quote(s["jid"]),
                                  {"prompt_pos": self.ed_pos.toPlainText(), "prompt_neg": self.ed_neg.toPlainText()})
            self.say(r.get("message", "") if r.get("ok") else "保存失败：%s" % (r.get("message") or r.get("error")),
                     not r.get("ok"))
        except Exception as e:
            self.say("保存失败：%s" % e, True)

    # -------------------------------------------------------------- AI 工具
    def _canvas_png(self, doc):
        w, h = doc.width(), doc.height()
        img = doc.projection(0, 0, w, h) if hasattr(doc, "projection") else doc.thumbnail(w, h)
        path = os.path.join(os.environ.get("TEMP", HERE), "atlas_krita_canvas.png")
        if not img.save(path, "PNG"):
            raise RuntimeError("导出画布失败")
        return path

    def _start(self, kind, fn):
        doc = Krita.instance().activeDocument()
        if doc is None:
            self.say("先打开一幅画。", True)
            return
        if doc.colorModel() != "RGBA" or doc.colorDepth() != "U8":
            self.say("AI 工具目前只支持 8 位 RGBA 的画布（当前 %s/%s）。" % (doc.colorModel(), doc.colorDepth()), True)
            return
        try:
            png = self._canvas_png(doc)
        except Exception as e:
            self.say(str(e), True)
            return
        comfy = Comfy(self.cfg.get("comfy_url", "http://127.0.0.1:8188"))
        job = {"kind": kind, "doc": doc, "w": doc.width(), "h": doc.height(), "result": None, "error": None,
               "msg": "", "denoise": self.sld.value() / 100.0}

        def work():
            try:
                job["msg"] = "上传画布到 ComfyUI…"
                name = comfy.upload(png)
                job["msg"] = "ComfyUI 处理中…"
                job["result"] = fn(comfy, name, job)
            except urllib.error.URLError:
                job["error"] = "连不上 ComfyUI：请先双击 %s 启动" % os.path.join(self.bridge_dir or "工具桥目录", "start-all.bat")
            except Exception as e:
                job["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        self._job = job
        job["thread"] = threading.Thread(target=work, daemon=True)
        job["thread"].start()
        self._sync_buttons()
        self.say("开始：%s" % ("AI 精修" if kind == "refine" else "AI 去背景"))

    def _poll_job(self):
        job = self._job
        if job is None:
            return
        if job["thread"].is_alive():
            self.lbl_status.setText(job["msg"])
            return
        self._job = None
        self._sync_buttons()
        if job["error"]:
            self.say(job["error"], True)
            return
        try:
            img = QImage()
            img.loadFromData(QByteArray(job["result"]))
            if img.isNull():
                raise RuntimeError("ComfyUI 返回的图片无法读取")
            w, h, doc = job["w"], job["h"], job["doc"]
            if img.width() != w or img.height() != h:   # VAE 会把尺寸裁到 8 的倍数，拉回画布尺寸对齐
                img = img.scaled(w, h, Qt.IgnoreAspectRatio if hasattr(Qt, "IgnoreAspectRatio") else Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.SmoothTransformation if hasattr(Qt, "SmoothTransformation") else Qt.TransformationMode.SmoothTransformation)
            root = doc.rootNode()
            if job["kind"] == "refine":
                node = doc.createNode("AI 精修 %.2f" % job["denoise"], "paintlayer")
                node.setPixelData(QByteArray(_img_bytes(img, FMT_ARGB32)), 0, 0, w, h)
                root.addChildNode(node, None)
                doc.setActiveNode(node)
                miss = job.get("untranslated") or []
                self.say("AI 精修完成：结果在最上面的「%s」图层，不满意就删掉它。%s" % (
                    node.name(), ("\n注意：有中文没翻译成功（%s），模型读不懂这部分。" % "、".join(miss[:3])) if miss else ""),
                    bool(miss))
                if job.get("prompt_en"):
                    self.lbl_status.setToolTip("实际发给模型的英文提示词：\n" + job["prompt_en"])
            else:
                mask = doc.createTransparencyMask("AI 去背景")
                mask.setPixelData(QByteArray(_img_bytes(img, FMT_GRAY8)), 0, 0, w, h)
                group = self._picture_group(doc)
                group.addChildNode(mask, None)
                self.say("AI 去背景完成：蒙版加在「%s」组上；在图层面板里关掉蒙版就恢复原样。" % group.name())
            doc.refreshProjection()
        except Exception:
            self.say("放回画布失败：" + traceback.format_exc()[-300:], True)

    def _picture_group(self, doc):
        """去背景要作用于整幅画：把顶层图层收进一个「画面」组，蒙版加在组上（已有就复用）。"""
        root = doc.rootNode()
        tops = [n for n in root.childNodes()]
        for n in tops:
            if n.type() == "grouplayer" and n.name() == "画面":
                return n
        group = doc.createGroupLayer("画面")
        movable = [n for n in tops if n.type() not in ("transparencymask", "selectionmask")]
        for n in movable:
            n.remove()
        group.setChildNodes(movable)
        root.addChildNode(group, None)
        return group

    def _refine(self):
        pos, neg = self.ed_pos.toPlainText(), self.ed_neg.toPlainText()
        ckpt = (self.session or {}).get("ckpt") or self.cfg.get("ckpt", "sd_xl_base_1.0.safetensors")

        def fn(comfy, name, job):
            def tick(sec):
                job["msg"] = "AI 精修中…（%ds）" % sec
            p_en, n_en = pos, neg
            if any("\u3400" <= ch <= "\u9fff" for ch in pos + neg):
                # 第十九轮：SDXL 读不懂中文，先经工具桥翻成英文（对照表 + 本地翻译模型）
                job["msg"] = "把中文提示词翻译成英文…"
                try:
                    r = self._bridge_post("/api/translate", {"texts": [pos, neg]})
                    if r.get("ok"):
                        p_en, n_en = r["texts"]
                        job["untranslated"] = r.get("untranslated", [])
                except Exception:
                    job["untranslated"] = ["（工具桥未连接，提示词没翻译）"]
            job["prompt_en"] = p_en
            return comfy.run(wf_refine(name, p_en, n_en, job["denoise"], ckpt, int(time.time()) % 2147483647), tick)
        self._start("refine", fn)

    def _remove_bg(self):
        def fn(comfy, name, job):
            def tick(sec):
                job["msg"] = "AI 去背景中…（%ds）" % sec
            return comfy.run(wf_mask(name), tick)
        self._start("bg", fn)


def register():
    Krita.instance().addDockWidgetFactory(
        DockWidgetFactory(DOCKER_ID, DockWidgetFactoryBase.DockRight, AtlasStudioDocker))
