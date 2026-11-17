# B 层 AI 引擎安装 · 说明（中文）

> 本文件是 `install-comfyui.ps1` 的中文说明。PowerShell 脚本必须保持纯 ASCII
> （PS 5.1 会按 ANSI 读取无 BOM 的 .ps1，混入中文会导致解析失败），
> 所以详细说明放在这份 UTF-8 文档里。

## 它能做什么

安装 ComfyUI + PyTorch CUDA 版，让工坊里的「AI 绘画 / 图生 3D」从云端链接
变成真正能在你本机调用的引擎。你的 RTX 4090（24GB）完全跑得动。

## 体积提醒（重要）

脚本**默认不下载模型权重**——那才是真正占空间的部分：

| 模型 | 体积 | 特点 |
|---|---|---|
| ComfyUI 框架 + PyTorch | 约 1–2 GB | 必装，脚本自动完成 |
| TripoSR | 约 2 GB | 轻量验证，亚秒级，MIT 许可 |
| TRELLIS.2 | 约 8–15 GB | 资产级质量，MIT 许可，**4090 推荐先装这个** |
| Hunyuan3D 2.1 | 约 10–20 GB | 中文生态，PBR 材质，社区许可（有地域限制条款） |

`-WithModels` 参数只是打印各模型的官方下载指引，不会擅自下载几十 GB。
请自己按提示下载权重并放进 ComfyUI 的 `models` 目录。

## 用法

在 PowerShell 里执行：

```powershell
cd "I:\workbuddy\创作工具星图\快捷方式工具"

# 只装框架（推荐先做这一步）
powershell -ExecutionPolicy Bypass -File install-comfyui.ps1

# 查看模型下载指引（不实际下载）
powershell -ExecutionPolicy Bypass -File install-comfyui.ps1 -WithModels

# 装到自定义目录
powershell -ExecutionPolicy Bypass -File install-comfyui.ps1 -InstallDir "D:\ComfyUI"
```

## 装完之后

1. 双击 `C:\ComfyUI\run_nvidia_gpu.bat` 启动，浏览器打开提示的本地地址；
2. 或者在工坊里点 ComfyUI 卡片的「启动」按钮（需本地工具桥在运行）；
3. 把工坊生成的提示词粘进 ComfyUI 的正/负提示词框即可开工。

## 前置要求

- Python 3.10+（已检测到 3.13，OK）
- Git（需在 PATH 中，用于克隆仓库）
- NVIDIA 驱动（已装，驱动版本 32.0.16.2114）
