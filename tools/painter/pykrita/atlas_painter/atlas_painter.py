# -*- coding: utf-8 -*-
"""Atlas AI Painter —— 在 Krita 里按笔触计划逐层逐笔作画（创作工具星图 第十二轮）。

触发方式：
  1. 自动：Krita 启动时若环境变量 ATLAS_PAINT_JOB 指向一个作业 JSON，且旁边没有 .done 标记，
     窗口创建后自动开画（由工坊「一键执行」启动 Krita 时设置）。
  2. 手动：菜单 工具 > 脚本 > 「Atlas · AI 逐笔作画（选择作业文件）…」。

作业 JSON 由 stroke_planner.py 生成：{width,height,background,layers:[{name,kind,opacity,strokes:[{c,w,pts,p?}]}]}
可选字段 output_kra / output_png / progress_file / done_file（工坊引擎会填好）。

实现要点：
  - 只用 libkis 公开接口：View.setForeGroundColor / setBrushSize / setCurrentBrushPreset，
    Node.paintLine（线稿，带起收笔压力）/ Node.paintPath（色彩笔触），用当前笔刷真实落笔。
  - QTimer 分片执行（每片约 40ms），界面不卡，用户能看着一笔一笔画出来。
  - 结束时导出 PNG、另存 .kra，并写 .done 标记供引擎轮询。
"""
import json, os, time, traceback

from krita import Extension, Krita, ManagedColor, InfoObject
try:
    from PyQt5.QtCore import QTimer, QPoint, QPointF, QRectF
    from PyQt5.QtGui import QColor, QPainterPath, QIcon
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
except ImportError:  # Krita 6 (Qt6)
    from PyQt6.QtCore import QTimer, QPoint, QPointF, QRectF
    from PyQt6.QtGui import QColor, QPainterPath, QIcon
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

# 每层优先使用的笔刷（按名字片段匹配，找不到就用基础圆笔，再不行保持当前笔刷）
PRESET_HINTS = {
    "sketch": ["Pencil-2", "Pencil 2", "Pencil", "Fineliner", "Ink"],
    "paint": ["Basic-5 Size Opacity", "Basic-5 Size", "Basic-2 Opacity", "Basic-1"],
    "line": ["Basic-1", "Fineliner", "Ink"],      # 第十九轮：勾线层用硬边圆笔，细线才干净
    "hard": ["Basic-1", "Basic-2 Opacity"],       # 第十九轮：≤3px 的细笔用硬边圆笔（默认软笔会把细节画柔）
    "soft": ["Basic-5 Size Opacity", "Basic-5 Size", "Basic-2 Opacity", "Basic-1"],
}
SLICE_MS = 100          # 第十九轮：每片 100ms（原 40ms），配合限频刷新，笔数多时快得多
REFRESH_MS = 300        # 画布刷新最多 300ms 一次（原来每片都刷新整个画布，是最大的开销）


def _ip(x, y):
    """第十九轮真机修正：Krita 5 的 Node.paintLine 只收整数坐标 QPoint，传 QPointF 会报
    "argument 1 has unexpected type 'QPointF'"（paintPath 用的 QPainterPath 照常用浮点）。"""
    return QPoint(int(round(x)), int(round(y)))


def _find_preset(kind):
    try:
        res = Krita.instance().resources("preset")
    except Exception:
        return None
    names = list(res.keys())
    for hint in PRESET_HINTS.get(kind, []):
        for n in names:
            if hint.lower() in n.lower():
                return res[n]
    return None


class _Painter:
    def __init__(self, job_path):
        self.job_path = job_path
        with open(job_path, encoding="utf-8") as f:
            self.job = json.load(f)
        base = os.path.splitext(job_path)[0]
        self.out_kra = self.job.get("output_kra") or base + ".kra"
        self.out_png = self.job.get("output_png") or base + ".png"
        self.progress_file = self.job.get("progress_file") or base + ".progress.json"
        self.done_file = self.job.get("done_file") or job_path + ".done"
        self.total = sum(len(L["strokes"]) for L in self.job["layers"])
        self.painted = 0
        self.t0 = time.time()

    # ------------------------------------------------------------ 状态文件
    def _write(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)

    def _progress(self, layer_name):
        self._write(self.progress_file, {"painted": self.painted, "total": self.total,
                                         "layer": layer_name, "elapsed": round(time.time() - self.t0, 1)})

    def _finish(self, ok, error=None):
        data = {"ok": ok, "strokes": self.painted, "total": self.total,
                "seconds": round(time.time() - self.t0, 1)}
        if ok:
            data.update({"kra": self.out_kra, "png": self.out_png})
        else:
            data["error"] = error
        self._write(self.done_file, data)

    def _say(self, msg):
        try:
            self.view.showFloatingMessage(msg, QIcon(), 2500, 1)
        except Exception:
            pass

    # ------------------------------------------------------------ 主流程
    def start(self):
        app = Krita.instance()
        w, h = int(self.job["width"]), int(self.job["height"])
        self.doc = app.createDocument(w, h, "AI 逐笔作画", "RGBA", "U8", "", 300.0)
        win = app.activeWindow()
        self.view = win.addView(self.doc)
        root = self.doc.rootNode()

        paper = self.doc.createNode("纸", "paintlayer")
        r, g, b = self.job.get("background", [245, 245, 240])
        paper.setPixelData(bytes([b, g, r, 255]) * (w * h), 0, 0, w, h)   # RGBA/U8 内存序为 BGRA

        # 叠放顺序：纸 → 色彩层（底色…收边）→ 线稿置顶（像人一样先起稿，最后把线稿调淡）
        self.layers = []
        nodes = [paper]
        sketch_nodes = []
        for L in self.job["layers"]:
            node = self.doc.createNode(L["name"], "paintlayer")
            self.layers.append((L, node))
            (sketch_nodes if L["kind"] == "sketch" else nodes).append(node)
        root.setChildNodes(nodes + sketch_nodes)
        self.doc.refreshProjection()

        # 绘制顺序就是 job 里的层顺序（线稿 → 底色 → 明暗 → 细节 → 收边）
        self.li, self.si = 0, 0
        self._enter_layer()
        QTimer.singleShot(300, self._tick)

    def _enter_layer(self):
        if self.li >= len(self.layers):
            return
        L, node = self.layers[self.li]
        self.doc.setActiveNode(node)
        self._last_col = self._last_w = None
        preset = _find_preset(L.get("brush") or L["kind"])
        if preset is not None:
            try:
                self.view.setCurrentBrushPreset(preset)
            except Exception:
                pass
        self._say("AI 逐笔作画 · %s（%d 笔）" % (L["name"], len(L["strokes"])))
        self._progress(L["name"])

    def _stroke(self, L, node, s):
        col = s["c"]
        key = (int(col[0]), int(col[1]), int(col[2]))
        if key != getattr(self, "_last_col", None):     # 颜色 / 笔刷大小没变就不重复设置
            self.view.setForeGroundColor(ManagedColor.fromQColor(QColor(*key), self.view.canvas()))
            self._last_col = key
        if s["w"] != getattr(self, "_last_w", None):
            self.view.setBrushSize(float(s["w"]))
            self._last_w = s["w"]
        pts = s["pts"]
        if L["kind"] == "sketch":
            pr = s.get("p") or [1.0] * len(pts)
            for i in range(len(pts) - 1):
                node.paintLine(_ip(*pts[i]), _ip(*pts[i + 1]), float(pr[i]), float(pr[i + 1]), "ForegroundColor")
        elif len(pts) == 1:
            x, y = pts[0]
            node.paintLine(_ip(x, y), _ip(x + 1, y), 1.0, 1.0, "ForegroundColor")
        else:
            path = QPainterPath(QPointF(*pts[0]))
            for p in pts[1:]:
                path.lineTo(QPointF(*p))
            node.paintPath(path, "ForegroundColor", "None")

    def _tick(self):
        try:
            deadline = time.time() + SLICE_MS / 1000.0
            while self.li < len(self.layers) and time.time() < deadline:
                L, node = self.layers[self.li]
                if self.si >= len(L["strokes"]):
                    self.li += 1
                    self.si = 0
                    self._enter_layer()
                    continue
                self._stroke(L, node, L["strokes"][self.si])
                self.si += 1
                self.painted += 1
            now = time.time()
            if now - getattr(self, "_last_refresh", 0) >= REFRESH_MS / 1000.0:
                self.doc.refreshProjection()
                self._last_refresh = now
            if self.painted % 500 < 60:
                self._progress(self.layers[min(self.li, len(self.layers) - 1)][0]["name"])
            if self.li < len(self.layers):
                QTimer.singleShot(0, self._tick)
            else:
                self._wrap_up()
        except Exception:
            self._finish(False, traceback.format_exc()[-800:])
            self._say("AI 逐笔作画出错，详情见 .done 文件")

    def _wrap_up(self):
        for L, node in self.layers:
            if L["kind"] == "sketch":
                if L.get("hide_after"):
                    node.setVisible(False)           # 第十九轮：起稿线完成后隐藏，不压在成品上（画师的做法）
                else:
                    node.setOpacity(int(255 * 0.35))
        self.doc.refreshProjection()
        self.doc.setBatchmode(True)                  # 导出/保存不弹对话框
        try:
            self.doc.exportImage(self.out_png, InfoObject())
            self.doc.saveAs(self.out_kra)
        finally:
            self.doc.setBatchmode(False)
        self._progress("完成")
        self._finish(True)
        self._say("AI 逐笔作画完成：%d 笔，用时 %d 秒" % (self.painted, time.time() - self.t0))


class AtlasPainterExtension(Extension):
    def __init__(self, parent):
        super().__init__(parent)
        self._painter = None
        self._autorun_checked = False

    def setup(self):
        try:
            Krita.instance().notifier().windowCreated.connect(self._on_window)
        except Exception:
            pass

    def createActions(self, window):
        act = window.createAction("atlas_painter_run", "Atlas · AI 逐笔作画（选择作业文件）…", "tools/scripts")
        act.triggered.connect(self._pick_and_run)

    def _on_window(self):
        if self._autorun_checked:
            return
        self._autorun_checked = True
        QTimer.singleShot(1500, self._autorun)

    def _autorun(self):
        path = os.environ.get("ATLAS_PAINT_JOB", "")
        if path and os.path.isfile(path) and not os.path.exists(path + ".done"):
            self._run(path)

    def _pick_and_run(self):
        path, _ = QFileDialog.getOpenFileName(None, "选择逐笔作画作业", "", "作业 (*.json)")
        if path:
            self._run(path)

    def _run(self, path):
        if self._painter is not None and self._painter.li < len(getattr(self._painter, "layers", [])):
            QMessageBox.information(None, "Atlas", "已有一幅画正在进行中。")
            return
        try:
            self._painter = _Painter(path)
            self._painter.start()
        except Exception:
            err = traceback.format_exc()[-800:]
            try:
                with open(path + ".done", "w", encoding="utf-8") as f:
                    json.dump({"ok": False, "error": err}, f, ensure_ascii=False)
            except Exception:
                pass
            QMessageBox.warning(None, "Atlas · AI 逐笔作画", "启动失败：\n" + err)
