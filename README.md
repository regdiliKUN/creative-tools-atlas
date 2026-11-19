# 创作工具星图 · Creative Tools Atlas

> 一份离线可读的 GitHub 创作工具调研星图、一条实操航线，以及一个能真正调用本机软件的内容工坊。
> v2.1.0 起带**本地工具桥**：工坊里的工具不再是冷冰冰的 GitHub 链接，而是「已装→点击启动 / 未装→一键安装」。

<p align="left">
  <strong>内容本地可读 · 工具点击即调用 · 效果优先排序 · 任务包直接流入执行台</strong>
</p>

## v2.0.0 产品自洽性加固（安全与可访问性见 v1.9.0）（本地工具链 v1.6.1 / 工作流支线 v1.6.2 引入）

- **真装了 10 个桌面软件**（Krita / Blender / FreeCAD / OpenSCAD / MeshLab / OpenToonz / Cura / PrusaSlicer / OrcaSlicer / UVtools），winget 静默安装，100% 可被探测。
- **本地工具桥** `tools/tool-bridge.py`：只监听 `127.0.0.1:7843` 的零依赖 HTTP 服务。工坊页通过它启动/安装工具。用法：

  ```powershell
  # 源码仓库：cd tools；发布包解压后：cd 创作工具星图/快捷方式工具
    cd tools
  powershell -ExecutionPolicy Bypass -File start-tool-bridge.ps1
  ```

  看到 `BRIDGE_STARTED` 后，回到工坊点「刷新状态」，工具卡片即可点击。

- **效果优先**：排序以产出质量为主（TRELLIS.2 登顶），显存/性能仅标注不主导，符合"效果为优先，性能暂不考虑"。
- **执行台**：生成任务包后自动抓取其中的工具与提示词，按阶段列出可点击按钮，不用复制粘贴。
- **AI 引擎**：`tools/install-comfyui.ps1` 可一键装 ComfyUI 框架，**但默认不下载几十 GB 的模型权重**；体积与下载指引见 `tools/安装AI引擎说明.md`。你的显卡需为 NVIDIA（脚本按 CUDA 12.1 装 PyTorch）。
- **迭代记录**已收进 `docs/迭代记录/` 子文件夹，根目录不再臃肿。

---

## 页面一览

| 页面 | 内容 |
|---|---|
| [index.html](index.html) | 导航首页，串起下面两份报告与创作工坊 |
| [github-creative-tools-atlas.html](github-creative-tools-atlas.html) | 4 个星区 · 23 个主项目：绘画 / AI 辅助 / 3D 建模 / 手办角色，含许可证与显存横评 |
| [route-a-painter-workstation.html](route-a-painter-workstation.html) | 航线 A 深潜：画师的数字工位，安装、参数、工作流与交接清单 |
| [studio.html](studio.html) | **创作工坊**：填一次需求即产出创作任务包（提示词 + 优中选优工具链 + 执行清单 + 许可警示），52 个工具编入 7 个生产环节 |

数据口径：星数、版本、提交日期为 **2026-11-16 前后**的公开快照，会持续浮动，故多以「约 / k」量级呈现，用于横向比较而非精确审计。

## 三种用法

### 方式一：直接看内容（任意平台）

用浏览器打开仓库中的 `index.html` 即可，四页均为单文件内联 CSS/JS，无需服务器、无需构建、无需联网。

### 方式二：Windows 免安装应用

前往 **Releases** 下载 `creative-tools-atlas-v2.1.0-win64.zip`（约 8 MB），解压到任意目录，双击 `创作工具星图.exe`：

- 以 Edge / Chrome 的**应用模式窗口**打开（无地址栏、无标签栏，像独立软件而非浏览器页面）；
- 找不到 Edge / Chrome 时自动回退系统默认浏览器，也可手动双击 `index.html`；
- 支持中文与含空格的路径；不写注册表、不常驻后台、不占端口；
- 卸载 = 删掉文件夹与桌面快捷方式。

解压后若双击没反应，在 `快捷方式工具/` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File diagnose.ps1
```

诊断器会依次检查核心文件、浏览器、快捷方式指向、运行依赖与文件完整性，输出 `DIAG_OK` 或点名问题并给出修复建议。

### 方式三：用创作工坊产出内容（任意平台，无需安装）

打开 `studio.html`，**先选工作流**——9 条独立支线各自聚焦一个目标：

| 支线 | 解决什么 |
|---|---|
| 角色立绘与设定图 | 从一句话设定到可交付角色美术稿 |
| 三视图与基准图 | 尺寸一致、视角固定的正/侧/后三视图 |
| 基建重建基准图 | 把图净化成能喂给 3D 模型的干净输入 |
| 图生 3D 模型 | 干净图 → 带纹理网格（效果优先） |
| 手办与 3D 打印 | 修模 → 切片 → 可打印实体 |
| VRM 与虚拟形象 | 角色 → 可驱动的 VRM 形象 |
| 像素与 2D 动画 | 像素画、逐帧动画与序列帧 |
| 参数化 CAD 零件 | 用参数/代码造硬表面零件 |
| PBR 贴图与材质 | 模型表面绘制与烘焙 PBR |

选中后主界面切成该支线，只显示所需工具（上下游顺序）、操作提示和避坑要点，无关工具折叠收起。点工具上的「启动 / 一键安装」直接调用本机软件（需本地工具桥运行）。支线底部点「用这条工作流生成任务包」展开参数区，填好主体即可生成。任务包含：

- **提示词包**：结构化正面 / 负面提示词、三视图 8 条硬规则、显存档位参数建议，可单独复制粘贴进 ComfyUI；
- **工具链**：7 个生产环节，每个环节首选 + 备选 + 判断依据；同功能重复项一律优中选优，上一代 / 研究 / 原型项明确标注；
- **执行清单**：按目标分阶段的勾选项，从装机、起稿到修模、切片、交付；
- **许可证与避坑**：商用时自动列出高风险许可项；显存不足的工具自动降级并写进「适配提示」；
- **全部工具索引**：52 个工具按环节列出，均带仓库地址。

支持复制、导出 `.md`、浏览器本地留存（载入 / 删除）、打印存 PDF。所有输入只在本地处理，**不上传、不联网**。页面为纯静态单文件，零外部资源。

## 目录结构

```
creative-tools-atlas/
├── index.html                          导航首页
├── github-creative-tools-atlas.html    报告一：工具星图
├── route-a-painter-workstation.html    报告二：画师数字工位
├── studio.html                         创作工坊：生成创作任务包
├── src/                                构建期源码（Python）
│   ├── launcher.py                     Windows 启动器（应用窗口 + 回退链）
│   ├── build_manifest.py               生成 SHA-256 校验清单
│   └── selftest.py                     自动化质量自检套件（25 条断言）
├── tools/                              PowerShell 工具（纯 ASCII）
│   ├── shortcut.ps1                    快捷方式创建 / 回读
│   ├── resolve-desktop.ps1             解析真实桌面路径
│   ├── rebuild-shortcut.ps1            一键重建快捷方式
│   ├── verify-package.ps1              按清单校验文件完整性
│   ├── diagnose.ps1                    用户侧一键故障诊断
│   ├── tool-bridge.py                  本地工具桥（127.0.0.1:7843，零依赖 HTTP 服务）
│   ├── start-tool-bridge.ps1           一键启动工具桥
│   ├── install-comfyui.ps1             AI 引擎安装脚本（默认不下载权重）
│   └── 安装AI引擎说明.md               AI 模型体积与下载指引（UTF-8 中文）
├── docs/                               使用说明、变更日志、校验基线、八轮迭代记录
└── assets/                             应用图标
```

> 二进制（`创作工具星图.exe` 与 `_internal/` 运行依赖）**不入库**，随每个 Release 以 zip 附件分发，避免仓库被 18MB DLL 撑胖。

## 从源码重建（Windows）

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onedir --windowed \
  --name "创作工具星图" --icon assets/icon.ico \
  src/launcher.py
```

把生成的 `dist/创作工具星图/` 内容放到与三个 HTML 同级的目录即可。启动器按自身所在目录查找 `index.html`，不依赖固定路径。

## 质量工具

三个脚本原先写死了本机路径，现已改为**自动探测包目录**，优先级：

1. 命令行 `--base <dir>`（仅 selftest）
2. 环境变量 `ATLAS_PACKAGE`
3. 自动探测：脚本同目录 / 同级「创作工具星图」/ 父目录（要求同时具备完整包特征）

```bash
# 开发期：对完整软件包跑 25 条静态断言
python src/selftest.py --base "D:\path\to\创作工具星图"

# 或用环境变量
set ATLAS_PACKAGE=D:\path\to\创作工具星图
python src/selftest.py
python src/build_manifest.py
```

断言覆盖：HTML 结构与打印样式、外链 `noopener` 加固、无障碍 landmark 与标题层级、七处版本号一致、清单与启动器动态同步、`.ps1` 纯 ASCII、迭代档案轮次完整、诊断器自身完整性。任一失败退出码非 0。

`docs/MANIFEST.md` 是**Release 完整包**的 SHA-256 校验基线（对应解压后的目录结构），`tools/verify-package.ps1` 与 `tools/diagnose.ps1` 按它核对；源码仓库本身不需要它。

## 迭代档案

这个产出物经历了 **9 轮 × 20 轮 = 180 轮**迭代完善，每轮均记录优化目标、改动、理由与自检结果：

- [第一轮](docs/迭代记录/迭代记录.md) · [第二轮](docs/迭代记录/迭代记录-v2.md) · [第三轮](docs/迭代记录/迭代记录-v3.md)
- [第四轮](docs/迭代记录/迭代记录-v4.md) · [第五轮](docs/迭代记录/迭代记录-v5.md) · [第六轮](docs/迭代记录/迭代记录-v6.md) · [第七轮](docs/迭代记录/迭代记录-v7.md) · [第八轮](docs/迭代记录/迭代记录-v8.md) · [第九轮](docs/迭代记录/迭代记录-v9.md)
- [变更日志](docs/CHANGELOG.md) · [使用说明](docs/使用说明.txt)

演进主线：v1.0 裸 HTML → v1.1 软件包化 → v1.2 应用窗口与哈希校验 → v1.3 锁 bug 与外链安全 → v1.4 多用户锁隔离与语义化 → v1.5 校验器动态化 → v1.6 自动化质量保障体系 + 创作工坊 → v1.6.1 本地工具链（点击即调用）→ v1.6.2 工作流支线化（选需求进专属支线）→ v1.7.0 第七轮20轮质量迭代 → v1.8.0 第八轮20轮 → v1.9.0 第九轮20轮（安全深水区/协议层/编码边界/无障碍）→ v2.0.0 第十轮20轮（产品自洽性：数据契约/状态机/协议兑现）→ v2.1.0 第十一轮引擎健壮性 + 第十二轮图生3D 真实打通。

## 说明

- 报告内容基于 2026-11 的公开信息整理，项目状态与星数请以各仓库实时页面为准。
- 仓库未附带开源许可证；如需授权复用，请先与作者联系。
- 所有 HTML 均为静态文件，可直接用 GitHub Pages 或任意静态托管发布。
