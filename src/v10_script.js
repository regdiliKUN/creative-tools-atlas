
"use strict";
// 轮9修正：只在【跨源】iframe 嵌套时跳出。同源嵌入（如本地预览面板）必须放行，
// 否则 frame-busting 会导致页面反复重载，脚本无法执行（点击即启动功能失效）。
try{
  if(window.top!==window.self){
    // 能读到 top.location.href 说明同源——放行；跨域读取会抛异常——跳出
    var _topHref=window.top.location.href;
    if(_topHref && new URL(_topHref).origin!==location.origin)
      window.top.location=window.self.location;
  }
}catch(e){
  try{ window.top.location=window.self.location; }catch(e2){}
}
/* ---------------------------------------------------------------- 工作流支线定义 */
/* 创作工坊 · 工作流支线定义 (v2.0.0)
   每条工作流 = 一个独立目标，含专属工具(上下游顺序)、步骤、操作提示、输入项。
   设计原则：选需求 → 进支线 → 只看相关工具 → 按序开工。
   全部工具名严格复用 studio.html GROUPS 里的 n 字段。 */


const WORKFLOWS = [
  {
    id: "character",
    icon: "✦",
    label: "角色立绘与设定图",
    tagline: "从一句话设定到可交付的角色美术稿",
    color: "var(--paint)",
    goalIds: ["character"],
    intro: "把角色设定变成干净、可复用的立绘与设定稿。核心是「先定基底、锁一致性、再出变体」——Krita 里起稿，AI 插件按选区/线稿生成，锁定 Seed 保证同一个角色不跑偏。",
    // 上下游顺序：起稿 → 生成 → 一致性 → 精修 → 交付
    stages: [
      {
        title: "起稿与设定基底",
        hint: "在 Krita 里画出角色草图与配色，保留分层源文件；这一步决定后面 AI 生成的骨架。",
        tools: ["Krita"]
      },
      {
        title: "AI 辅助生成与局部重绘",
        hint: "装 Krita AI Diffusion 插件，用选区生成/Live Painting 反复迭代；首次启动 Krita 加载笔刷资源可能要 1–3 分钟，属正常。",
        tools: ["Krita AI Diffusion", "ComfyUI"]
      },
      {
        title: "锁定角色一致性",
        hint: "满意基底后锁 Seed，只调 CFG/Denoise 出变体；系列角色可叠加 IP-Adapter 或自训 LoRA。",
        tools: ["ControlNet"]
      },
      {
        title: "精修与交付",
        hint: "抠图去底、FaceDetailer 修脸，输出干净 PNG；商用前核对模型权重与许可证。",
        tools: ["抠图 / 净化", "Krita"]
      }
    ],
    tips: [
      "首选 Krita + AI 插件起步，别一上来搭 ComfyUI 节点图。",
      "6GB 显存能跑；512² 小图先验证，再上 1024²。",
      "保留分层 .kra 源文件，是质量也是商用合规证据。"
    ],
    promptKind: "character"
  },
  {
    id: "triview",
    icon: "◫",
    label: "三视图与基准图",
    tagline: "产出尺寸一致、视角固定的正/侧/后三视图",
    color: "var(--ai)",
    goalIds: ["triview"],
    intro: "三视图是「美术设定图」和「重建输入图」的分水岭。诀窍是：不换提示词，只换控制图（骨架/深度/Canny）来切视角，强制三个视角共用同一套人体比例。",
    stages: [
      {
        title: "备好正面基底",
        hint: "先出一张确认过的正面高清设定图，作为三视图的基准。",
        tools: ["Krita", "Krita AI Diffusion"]
      },
      {
        title: "控制图锁定视角",
        hint: "预置标准三视图骨架图/深度图作条件输入；换视角只替换控制图，不换提示词。",
        tools: ["ControlNet", "openpose"]
      },
      {
        title: "批量出三视图",
        hint: "在 ComfyUI 里跑三视图工作流，锁 Seed、固定尺寸与顺序（正/侧/后）。",
        tools: ["ComfyUI", "zero123plus"]
      },
      {
        title: "一致性校验",
        hint: "检查比例、服装细节在三个视角是否一致；不一致就回到控制图微调。",
        tools: ["三视图控制图", "锁 Seed 做变体"]
      }
    ],
    tips: [
      "正/侧/后三张尺寸必须一致、顺序固定，否则下游重建会错位。",
      "白底、平光、单对象；极端角度会漂，优先 3/4 视角。",
      "IP-Adapter 权重 0.6–0.8：>0.8 僵硬，<0.5 锁不住。"
    ],
    promptKind: "triview"
  },
  {
    id: "rebuild",
    icon: "◇",
    label: "基建重建基准图",
    tagline: "把三视图净化成能喂给图生 3D 模型的干净输入",
    color: "var(--model)",
    goalIds: ["to3d","triview"],
    intro: "这是最容易被跳过、却最要命的一环：AI 直接吐出的图带水印、脏背景、多光源，喂进重建模型等于埋雷。这一步专门把图「洗干净」，产出符合 8 条硬规则的重建基准图。",
    stages: [
      {
        title: "准备干净输入",
        hint: "白底/透明底、平光、单对象、1024² 以上；复杂角色补正/侧/后三视图。",
        tools: ["Krita"]
      },
      {
        title: "抠图与净化",
        hint: "Rembg 抠图、去水印、ColorMatch、FaceDetailer——脏数据进重建等于埋雷，这步不能省。",
        tools: ["抠图 / 净化", "ComfyUI"]
      },
      {
        title: "按 8 条硬规则校验",
        hint: "逐条核对重建基准图规格：单对象、平光、视角、尺寸一致、顺序固定。",
        tools: ["三视图控制图"]
      },
      {
        title: "进入重建（下一支线）",
        hint: "净化后的干净 PNG 即可交给「图生 3D 模型」工作流；这里只负责把输入端做到位。",
        tools: ["Blender"]
      }
    ],
    tips: [
      "输出必须是干净 PNG，不要 JPG（压缩伪影伤害重建）。",
      "单对象、不遮挡、无文字水印——这三样是重建质量的命门。",
      "想直接看重建效果？完成本支线后切换到「图生 3D 模型」支线。"
    ],
    promptKind: "rebuild"   // 轮4：不再复用 triview
  },
  {
    id: "to3d",
    icon: "◈",
    label: "图生 3D 模型",
    tagline: "从干净图到带纹理的 3D 网格（效果优先）",
    color: "var(--ai)",
    goalIds: ["to3d"],
    intro: "效果优先：TRELLIS.2 产出质量最高（资产级、MIT），Hunyuan3D 系列 PBR 材质强，TripoSR 只作轻量验证。RTX 4090 24GB 跑 TRELLIS.2 没问题；权重需单独下载。",
    stages: [
      {
        title: "选择生成模型",
        hint: "按效果排序：TRELLIS.2（最好）→ Hunyuan3D-2.1（PBR）→ Hunyuan3D 2.0 → TripoSR（轻量验证）。",
        tools: ["TRELLIS / TRELLIS.2", "Hunyuan3D-2.1", "TripoSR"]
      },
      {
        title: "生成与导出",
        hint: "把净化后的干净 PNG 送进模型，导出 GLB / OBJ；首次需下载模型权重（数 GB–十几 GB）。",
        tools: ["ComfyUI"]
      },
      {
        title: "拓扑与修模",
        hint: "AI 网格多是三角面：instant-meshes 重四边面，MeshLab 清理，Blender 修漏面/非流形。",
        tools: ["instant-meshes", "MeshLab", "Blender"]
      },
      {
        title: "质量校验",
        hint: "trimesh 脚本化检查网格完整性，确认可进入打印或 VRM 流程。",
        tools: ["trimesh", "Assimp"]
      }
    ],
    tips: [
      "权重默认不随包下载——见「安装AI引擎说明.md」按体积自行获取。",
      "显存被占用会 OOM：生成前确认 24GB 已释放。",
      "商用优先 MIT 模型（TRELLIS/TripoSR）；Hunyuan3D 社区许可有地域条款。"
    ],
    promptKind: "to3d"
  },
  {
    id: "print",
    icon: "▲",
    label: "手办与 3D 打印",
    tagline: "从网格到可打印、可上色的实体手办",
    color: "var(--figure)",
    goalIds: ["print"],
    intro: "最后一公里：AI 网格通常不能直接打印（漏面、非流形、薄壁、空腔）。先修模，再切片，先打小样验证比例与壁厚，别一上来就打大模型。",
    stages: [
      {
        title: "网格修复",
        hint: "Blender 查漏面/非流形/薄壁/内部空腔，MeshLab 简化，trimesh 脚本化校验。",
        tools: ["Blender", "MeshLab", "trimesh"]
      },
      {
        title: "重拓扑与加厚",
        hint: "instant-meshes 把三角面转规整四边面；薄壁处加厚，避免打印时断裂。",
        tools: ["instant-meshes-2026"]
      },
      {
        title: "切片设置",
        hint: "FDM 用 OrcaSlicer（树状支撑），光固化用 UVtools；先打 30% 小样验证。",
        tools: ["OrcaSlicer", "UVtools", "PrusaSlicer", "Cura"]
      },
      {
        title: "上色与交付",
        hint: "ArmorPaint 在模型表面绘 PBR 贴图；整理源文件与切片参数。",
        tools: ["ArmorPaint"]
      }
    ],
    tips: [
      "别省修模：脏网格打出来就是废件，浪费几小时机时。",
      "OrcaSlicer/UVtools 是 AGPL，做商品售卖前留意许可。",
      "先打小样验证比例，再放大到成品尺寸。"
    ],
    promptKind: "print"
  },
  {
    id: "vrm",
    icon: "☺",
    label: "VRM 与虚拟形象",
    tagline: "把角色做成可驱动、可上架的 VRM 形象",
    color: "var(--figure)",
    goalIds: ["vrm"],
    intro: "从角色网格到能说话、能动、能上架的虚拟形象。核心是 VRM 1.0 规范导出 + 骨骼/表情标准化，再做面捕驱动与网页展示。",
    stages: [
      {
        title: "人体底模",
        hint: "MakeHuman 滑杆生成带骨骼的基础人体，或沿用前面支线的角色网格。",
        tools: ["MakeHuman", "Blender"]
      },
      {
        title: "VRM 导出",
        hint: "Blender + VRM Add-on 导出 VRM 0.x/1.0，规范 Humanoid 骨骼与表情。",
        tools: ["VRM Add-on for Blender", "VRM 规范"]
      },
      {
        title: "换装与转换",
        hint: "CharacterStudio 浏览器内换装调色；MMD 资源用 VRMify 转 VRM。",
        tools: ["CharacterStudio", "VRMify"]
      },
      {
        title: "驱动与展示",
        hint: "VSeeFace 面捕驱动；three-vrm / model-viewer 在网页展示形象。",
        tools: ["VSeeFace", "three-vrm", "model-viewer"]
      }
    ],
    tips: [
      "导出前确认 VRM 1.0 规范，避免各平台兼容问题。",
      "表情（BlendShape）命名要标准，否则面捕识别不到。",
      "VRM 规范本身是公开标准，商用前留意模型来源授权。"
    ],
    promptKind: "vrm"   // 轮4：不再复用 character
  },
  {
    id: "pixel",
    icon: "▦",
    label: "像素与 2D 动画",
    tagline: "像素画、逐帧动画与序列帧输出",
    color: "var(--paint)",
    goalIds: ["pixel"],
    intro: "像素与动画是独立于 3D 的一条支线。Aseprite 管像素逐帧，OpenToonz 管完整 2D 动画（扫描、上色、摄影表、特效）。",
    stages: [
      {
        title: "像素绘制",
        hint: "Aseprite 图层/帧分离、洋葱皮、像素完美笔刷；注意官方二进制需购买。",
        tools: ["Aseprite"]
      },
      {
        title: "2D 动画",
        hint: "OpenToonz 做扫描线稿、自动上色、摄影表、骨骼变形与特效渲染。",
        tools: ["OpenToonz"]
      },
      {
        title: "导出交付",
        hint: "导出精灵表 / 序列帧，供游戏引擎或视频剪辑使用。",
        tools: ["Aseprite", "OpenToonz"]
      }
    ],
    tips: [
      "Aseprite 是 EULA：源码可读但官方二进制需购买，商用务必合规。",
      "像素画先定调色板（16/32 色），再动笔。",
      "序列帧导出注意帧率与命名顺序。"
    ],
    promptKind: "pixel"
  },
  {
    id: "cad",
    icon: "⬡",
    label: "参数化 CAD 零件",
    tagline: "用参数/代码造可打印的硬表面零件",
    color: "var(--model)",
    goalIds: ["cad"],
    intro: "硬表面、需要精确尺寸的零件走这条支线：FreeCAD（可视化参数化）、OpenSCAD（代码 CSG）、CadQuery（Python 工作流）三选一，改一个参数整件重算。",
    stages: [
      {
        title: "参数化建模",
        hint: "FreeCAD 约束草图+特征历史；或 OpenSCAD/CadQuery 用代码描述实体。",
        tools: ["FreeCAD", "OpenSCAD", "CadQuery"]
      },
      {
        title: "AI 辅助 CAD（可选）",
        hint: "text-to-cad 给编码 Agent 用的 CAD 技能包，可快速起稿。",
        tools: ["text-to-cad"]
      },
      {
        title: "合体与导出",
        hint: "导出的 STL 可与角色网格合体，再进打印支线。",
        tools: ["Assimp", "glTF-Blender-IO"]
      }
    ],
    tips: [
      "三者按语言偏好二选一：FreeCAD 可视化、OpenSCAD 声明式、CadQuery 现代 Python。",
      "参数化零件改尺寸不用重画，这是它相对手工建模的核心优势。",
      "导出 STL 前检查壁厚与公差，避免打印装不上。"
    ],
    promptKind: "cad"
  },
  {
    id: "texture",
    icon: "◐",
    label: "PBR 贴图与材质",
    tagline: "在 3D 模型表面绘制与烘焙 PBR 材质",
    color: "var(--model)",
    goalIds: ["texture"],
    intro: "贴图是「绘画」与「建模」之间的门。ArmorPaint 直接在模型表面绘 PBR，Blender 负责 UV 与烘焙，是这条支线的主力。",
    stages: [
      {
        title: "表面绘制",
        hint: "ArmorPaint 直接在 3D 模型表面绘制 PBR 贴图，实时预览。",
        tools: ["ArmorPaint"]
      },
      {
        title: "UV 与烘焙",
        hint: "Blender 里检查 UV、烘焙法线/AO 贴图，确保引擎里正确显示。",
        tools: ["Blender", "Krita AI Diffusion"]
      },
      {
        title: "引擎接入",
        hint: "glTF-Blender-IO 导出 GLB，three-vrm/model-viewer 做网页预览。",
        tools: ["glTF-Blender-IO", "model-viewer"]
      }
    ],
    tips: [
      "PBR 三件套：BaseColor / Roughness / Normal，缺一影响质感。",
      "贴图分辨率与 UV 布局先行，避免后面返工。",
      "商用留意贴图素材来源与模型许可证。"
    ],
    promptKind: "texture"
  }
];



/* ---------------------------------------------------------------- 数据底座
   全部工具来自包内两份报告。tier: top 首选 / alt 备选 / legacy 上一代
   / research 研究教学 / proto 原型(已被吸收) / spec 规范 / tech 技法
   roles: 适用目标; vram: 最低显存 GB(0=不需要)                            */
const GROUPS = [
  {id:"canvas", name:"画布 / 数字绘画", color:"var(--paint)", tools:[
    {n:"Krita", u:"https://github.com/KDE/krita", s:"10.8k ★", lic:"GPL-3.0", tier:"top", vram:0, roles:[], note:"免费里最接近正经画画的那个，笔刷/图层/漫画分格齐全，也是 AI 插件的宿主。链条第一环最稳的起点。"},
    {n:"Krita AI Diffusion", u:"https://github.com/Acly/krita-ai-diffusion", s:"10.9k ★", lic:"GPL-3.0", tier:"top", vram:6, roles:["character","triview","texture"], note:"在 Krita 内把选区/线稿/姿态翻译成生成条件；官方硬指标 NVIDIA ≥6GB。四把刷子都在它里面。"},
    {n:"Aseprite", u:"https://github.com/aseprite/aseprite", s:"~40.8k ★", lic:"EULA", tier:"alt", vram:0, roles:["pixel"], note:"像素画与逐帧动画首选；源码可读但官方二进制需购买，商用务必先读 EULA。"},
    {n:"OpenToonz", u:"https://github.com/opentoonz/opentoonz", s:"7.8k ★", lic:"BSD-3", tier:"alt", vram:0, roles:["pixel"], note:"完整 2D 动画制作：扫描线稿、自动上色、摄影表、骨骼变形。做动画而非单张插画时选它。"},
    {n:"excalidraw", u:"https://github.com/excalidraw/excalidraw", s:"—", lic:"MIT", tier:"alt", vram:0, roles:[], note:"手绘风白板，画流程草图与创作构思；不是正式绘画工具，仅用于前期构思。"},
    {n:"ArmorPaint", u:"https://github.com/armory3d/armorpaint", s:"~5.5k ★", lic:"—", tier:"alt", vram:0, roles:["texture","to3d"], note:"直接在 3D 模型表面绘制 PBR 贴图，是「绘画」与「建模」之间的那道门。"},
    {n:"openpose", u:"https://github.com/CMU-Perceptual-Computing-Lab/openpose", s:"~33.6k ★", lic:"—", tier:"legacy", vram:0, roles:["triview"], note:"姿态关键点提取做参考，已停更多年；实际部署用 ComfyUI 内置的 OpenPose 预处理器即可。"}
  ]},
  {id:"engine", name:"AI 生成引擎 / 一致性", color:"var(--ai)", tools:[
    {n:"ComfyUI", u:"https://github.com/Comfy-Org/ComfyUI", s:"147.1k ★", lic:"GPL-3.0", tier:"top", vram:6, roles:[], note:"节点式生成工作流引擎，整个开源创作生态的中枢神经。若只深入一个 AI 项目，选它。"},
    {n:"IP-Adapter / FaceID", u:"https://github.com/Comfy-Org/ComfyUI", s:"技法", lic:"—", tier:"tech", vram:0, roles:["character","triview"], note:"零训练锁身份，权重 0.6–0.8；>0.8 僵硬发糊，<0.5 锁不住脸。在 ComfyUI 内以节点实现。"},
    {n:"InstantID / PuLID", u:"https://github.com/Comfy-Org/ComfyUI", s:"技法", lic:"—", tier:"tech", vram:0, roles:["character","triview"], note:"零训练、脸部保真更强，常与 IP-Adapter 叠用（一个管脸、一个管风格体态）。"},
    {n:"自训角色 LoRA", u:"https://github.com/Comfy-Org/ComfyUI", s:"技法", lic:"—", tier:"tech", vram:12, roles:["character","triview"], note:"20–30 张多角度图微调约半小时，系列化/量产/长期角色的正解；训练集必须含多角度。"},
    {n:"ControlNet", u:"https://github.com/lllyasviel/ControlNet", s:"34.1k ★", lic:"Apache-2.0", tier:"proto", vram:0, roles:["triview","to3d"], note:"条件控制的论文与原型，早已被 ComfyUI 与 Krita 插件内置吸收；不需单独安装，也不需打开。"},
    {n:"AUTOMATIC1111 WebUI", u:"https://github.com/AUTOMATIC1111/stable-diffusion-webui", s:"上一代", lic:"AGPL-3.0", tier:"legacy", vram:6, roles:[], note:"上一代 AI 绘画界面的王者，如今节奏明显放缓；新项目更建议从 ComfyUI 起步。"},
    {n:"Fooocus", u:"https://github.com/lllyasviel/Fooocus", s:"上一代", lic:"GPL-3.0", tier:"legacy", vram:6, roles:[], note:"开箱即用的简洁界面，同样明显放缓；与 A1111 属重复功能，优中选优让位 ComfyUI。"}
  ]},
  {id:"model", name:"3D 建模 / 修模 / 格式", color:"var(--model)", tools:[
    {n:"Blender", u:"https://github.com/blender/blender", s:"~21.7k ★", lic:"GPL-3.0", tier:"top", vram:0, roles:[], note:"全流程 3D 套件；AI 吐出的网格漏面/非流形/薄壁/空腔，全靠它收尾，这一步别省。"},
    {n:"trimesh", u:"https://github.com/mikedh/trimesh", s:"3.7k ★", lic:"MIT", tier:"top", vram:0, roles:["print","to3d"], note:"纯 Python 三角网格库，STL/OBJ/PLY/GLB/3MF 通吃；脚本化批量检查与修复网格的首选。"},
    {n:"MCP for Blender", u:"https://github.com/ahujasid/mcp-for-blender", s:"34.5k ★", lic:"MIT", tier:"alt", vram:0, roles:[], note:"让 LLM 直接读写 Blender 场景：建物体、改材质、跑渲染。2026-09 由 blender-mcp 更名，认新地址。"},
    {n:"MeshLab", u:"https://github.com/cnr-isti-vclab/meshlab", s:"5.7k ★", lic:"GPL-3.0", tier:"alt", vram:0, roles:["print","to3d"], note:"网格清理、修补、简化、贴图烘焙的图形界面老将，3D 打印前处理常用。"},
    {n:"instant-meshes", u:"https://github.com/wjakob/instant-meshes", s:"6.1k ★", lic:"BSD", tier:"alt", vram:0, roles:["to3d"], note:"自动四边面重拓扑；AI 生成的一团三角面想变成可编辑规整网格就靠它。"},
    {n:"instant-meshes-2026", u:"https://github.com/MondRubberduck/instant-meshes-2026", s:"社区分支", lic:"—", tier:"alt", vram:0, roles:["to3d"], note:"上者的社区现代化分支，老仓库停更时优先试这个。"},
    {n:"FreeCAD", u:"https://github.com/FreeCAD/FreeCAD", s:"35.4k ★", lic:"LGPL-2.0", tier:"alt", vram:0, roles:["cad"], note:"参数化 3D CAD：约束草图、特征历史、工程图、Python API；做可打印的硬表面零件选它。"},
    {n:"OpenSCAD", u:"https://github.com/openscad/openscad", s:"10.6k ★", lic:"GPL-2.0", tier:"alt", vram:0, roles:["cad"], note:"用代码描述实体（CSG + 轮廓拉伸），改一个变量整件模型随之重算。"},
    {n:"CadQuery", u:"https://github.com/CadQuery/cadquery", s:"6.1k ★", lic:"Apache-2.0", tier:"alt", vram:0, roles:["cad"], note:"Python 版参数化 CAD，比 OpenSCAD 更贴近现代 Python 工作流；与 FreeCAD 属重复功能，按语言偏好二选一。"},
    {n:"text-to-cad", u:"https://github.com/earthtojake/text-to-cad", s:"~26k ★", lic:"—", tier:"alt", vram:0, roles:["cad"], note:"2026 新项目，给编码 Agent 用的 CAD 技能包，代表「Agent 直接造模型」的方向。"},
    {n:"Assimp", u:"https://github.com/assimp/assimp", s:"13.3k ★", lic:"BSD-3", tier:"alt", vram:0, roles:["to3d"], note:"把 40+ 种 3D 格式互转的导入库，格式不通时用它做中转。"},
    {n:"glTF-Blender-IO", u:"https://github.com/KhronosGroup/glTF-Blender-IO", s:"~1.7k ★", lic:"Apache-2.0", tier:"alt", vram:0, roles:["vrm","print"], note:"GLB 进出 Blender 的官方通道，网页展示与引擎导入的标准格式。"}
  ]},
  {id:"to3d", name:"图生 3D / 重建", color:"var(--ai)", tools:[
    {n:"TripoSR", u:"https://github.com/VAST-AI-Research/TripoSR", s:"6.9k ★", lic:"MIT", tier:"top", vram:6, roles:["to3d","print"], note:"前馈式单图重建，约 6GB / 亚秒级 / 干净 MIT。轻量验证与商用最稳的第一站。"},
    {n:"TRELLIS / TRELLIS.2", u:"https://github.com/microsoft/TRELLIS", s:"14.3k ★", lic:"MIT", tier:"top", vram:24, roles:["to3d","print"], note:"结构化潜变量 SLAT，一份结果可解码成 Mesh / 3D Gaussian；资产级质量 + 干净 MIT，显存 24GB 起。"},
    {n:"Hunyuan3D 2.0", u:"https://github.com/Tencent-Hunyuan/Hunyuan3D-2", s:"15.4k ★", lic:"社区许可", tier:"alt", vram:16, roles:["to3d","print"], note:"两阶段生成（几何→纹理），中文生态与手办适配最厚；社区许可含地域排除与大用户条款，商用前必读。"},
    {n:"Hunyuan3D-2.1", u:"https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1", s:"~4.4k ★", lic:"社区许可", tier:"alt", vram:16, roles:["to3d","texture"], note:"2.0 的画质升级支线，主打生产级 PBR 材质；许可限制同上。"},
    {n:"Unique3D", u:"https://github.com/AiuniAI/Unique3D", s:"3.6k ★", lic:"—", tier:"alt", vram:12, roles:["to3d"], note:"单图约 30 秒产出带纹理网格：多视图扩散 → 多级上采样提纹理。"},
    {n:"InstantMesh", u:"https://github.com/TencentARC/InstantMesh", s:"~4.6k ★", lic:"—", tier:"legacy", vram:12, roles:["to3d"], note:"多视图扩散 + FlexiCubes，主要更新停在 2024；高星不等于还活着，读原理可以，部署找仍在维护的。"},
    {n:"shap-e", u:"https://github.com/openai/shap-e", s:"~12k ★", lic:"MIT", tier:"research", vram:0, roles:["to3d"], note:"3D 生成的基础范式教学仓，细节偏弱；适合读原理而非出成品。"},
    {n:"zero123plus", u:"https://github.com/SUDO-AI-3D/zero123plus", s:"—", lic:"—", tier:"proto", vram:0, roles:["triview","to3d"], note:"单图生成一致多视图，是很多图生 3D 链路的上游模块；做角色三视图时特别有用。"},
    {n:"threestudio", u:"https://github.com/threestudio-project/threestudio", s:"—", lic:"—", tier:"research", vram:0, roles:["to3d"], note:"偏研究与 3D 重建的框架，适合想深入算法的人。"},
    {n:"gaussian-splatting", u:"https://github.com/graphdeco-inria/gaussian-splatting", s:"—", lic:"—", tier:"research", vram:0, roles:["to3d"], note:"3D Gaussian Splatting 原始实现，研究向；TRELLIS 已能直接解码出 3DGS。"}
  ]},
  {id:"role", name:"角色 / VRM 生态", color:"var(--figure)", tools:[
    {n:"VRM Add-on for Blender", u:"https://github.com/saturday06/VRM-Addon-for-Blender", s:"1.7k ★", lic:"—", tier:"top", vram:0, roles:["vrm"], note:"在 Blender 中导入/导出 VRM 0.x 与 1.0，Humanoid 骨骼与表情标准化；做 VRM 的第一站。"},
    {n:"MakeHuman", u:"https://github.com/makehumancommunity/makehuman", s:"~1.6k ★", lic:"AGPL-3.0", tier:"alt", vram:0, roles:["vrm","print"], note:"滑杆生成参数化 3D 人体，输出带骨骼的基础网格；适合快速起人体底模。"},
    {n:"CharacterStudio", u:"https://github.com/M3-org/CharacterStudio", s:"375 ★", lic:"—", tier:"alt", vram:0, roles:["vrm"], note:"浏览器里的 VRM/glTF 角色工作室：点选换装、拖入本地模型与贴图、调色。"},
    {n:"three-vrm", u:"https://github.com/pixiv/three-vrm", s:"2.3k ★", lic:"MIT", tier:"alt", vram:0, roles:["vrm"], note:"Three.js 的 VRM 加载与渲染库，网页里展示角色用它。"},
    {n:"model-viewer", u:"https://github.com/google/model-viewer", s:"—", lic:"Apache-2.0", tier:"alt", vram:0, roles:["vrm","print"], note:"一个标签即可在网页展示 GLB/GLTF，作品集展示最省事。"},
    {n:"VRMify", u:"https://github.com/JiGuang283/VRMify", s:"—", lic:"—", tier:"alt", vram:0, roles:["vrm"], note:"把 MMD 的 PMX 模型转成 VRM，是 MMD 角色资源宝库的钥匙。"},
    {n:"VSeeFace", u:"https://github.com/emilianavt/VSeeFace", s:"—", lic:"—", tier:"alt", vram:0, roles:["vrm"], note:"面捕驱动 VRM 角色，让做好的形象动起来。"},
    {n:"VRM 规范", u:"https://github.com/vrm-c/vrm-specification", s:"规范", lic:"—", tier:"spec", vram:0, roles:["vrm"], note:"VRM 格式规范本身；遇到兼容性问题回来查这份。"},
    {n:"smplx", u:"https://github.com/vchoutas/smplx", s:"—", lic:"—", tier:"research", vram:0, roles:["vrm"], note:"学术向参数化人体模型，研究用而非出成品。"}
  ]},
  {id:"print", name:"切片 / 打印收尾", color:"var(--figure)", tools:[
    {n:"OrcaSlicer", u:"https://github.com/OrcaSlicer/OrcaSlicer", s:"~16.2k ★", lic:"AGPL-3.0", tier:"top", vram:0, roles:["print"], note:"FDM 切片首选：内置校准测试、逐特征参数、树状/有机支撑、多机型配置。已从 SoftFever 迁到组织账号。"},
    {n:"UVtools", u:"https://github.com/sn4k3/UVtools", s:"~1.6k ★", lic:"AGPL-3.0", tier:"top", vram:0, roles:["print"], note:"直接打开并编辑已切片的光固化文件（.ctb/.goo/.photon…），光固化路线的收尾利器。"},
    {n:"PrusaSlicer", u:"https://github.com/prusa3d/PrusaSlicer", s:"~9.4k ★", lic:"AGPL-3.0", tier:"alt", vram:0, roles:["print"], note:"稳定保守的 FDM 切片；求稳、不追新功能时选它。"},
    {n:"Cura", u:"https://github.com/Ultimaker/Cura", s:"~7.1k ★", lic:"LGPL-3.0", tier:"alt", vram:0, roles:["print"], note:"机型兼容最广；老机器或非主流机型找不到配置时用它。"}
  ]},
  {id:"craft", name:"技法 / 中间产物", color:"var(--muted)", tools:[
    {n:"三视图控制图", u:"https://github.com/Comfy-Org/ComfyUI", s:"技法", lic:"—", tier:"tech", vram:0, roles:["triview","to3d"], note:"预置标准三视图骨架/深度图作条件，强制统一人体比例；换视角只换控制图、不换提示词。"},
    {n:"抠图 / 净化", u:"https://github.com/Comfy-Org/ComfyUI", s:"技法", lic:"—", tier:"tech", vram:0, roles:["to3d","print"], note:"Rembg / LaMa 抠图、去水印、ColorMatch、FaceDetailer；脏数据进重建流程等于埋雷，别省。"},
    {n:"锁 Seed 做变体", u:"https://github.com/Comfy-Org/ComfyUI", s:"技法", lic:"—", tier:"tech", vram:0, roles:["character","triview"], note:"找到满意基底后锁 Seed，只调 CFG / Denoise 出变体，保证角色一致性。"}
  ]}
];

const GOALS = [
  {id:"character", label:"角色立绘 / 设定图"},
  {id:"triview",   label:"三视图 / 重建基准图"},
  {id:"to3d",      label:"图生 3D 模型"},
  {id:"print",     label:"手办 / 3D 打印"},
  {id:"vrm",       label:"VRM / 虚拟形象"},
  {id:"pixel",     label:"像素 / 2D 动画"},
  {id:"cad",       label:"参数化 CAD 零件"},
  {id:"texture",   label:"PBR 贴图 / 材质"}
];
const TIER_LABEL = {top:"首选",alt:"备选",legacy:"上一代",research:"研究",proto:"原型",spec:"规范",tech:"技法"};
const TIER_RANK  = {top:0,alt:1,tech:2,proto:3,legacy:4,research:5,spec:6};
/* 效果优先：quality 为产出质量分(10 最高)，排序时权重最大；性能/显存仅作参考信息。
   用户明确要求「效果为优先，性能暂不考虑」。 */
const QUALITY = {
  "TRELLIS / TRELLIS.2":10,"Hunyuan3D 2.0":9,"Hunyuan3D-2.1":9.5,"Unique3D":8,
  "InstantMesh":7,"TripoSR":6.5,"ComfyUI":10,"Krita AI Diffusion":9,"ControlNet":8,
  "Krita":9,"Blender":10,"Aseprite":8,"OpenToonz":7.5,"FreeCAD":8.5,"OpenSCAD":7,
  "CadQuery":8,"OrcaSlicer":9,"UVtools":8.5,"PrusaSlicer":8,"Cura":7.5,"MeshLab":7,
  "instant-meshes":8,"instant-meshes-2026":8.5,"ArmorPaint":8,"MCP for Blender":7,
  "MakeHuman":7,"VRM Add-on for Blender":9,"CharacterStudio":7.5,"VSeeFace":8,
  "shap-e":4,"zero123plus":6,"threestudio":5,"gaussian-splatting":5,"smplx":5,
  "three-vrm":7,"model-viewer":7,"VRMify":7,"openpose":5,"excalidraw":4,
  "AUTOMATIC1111 WebUI":6,"Fooocus":6,"text-to-cad":6,"Assimp":6,"trimesh":7,
  "glTF-Blender-IO":7,"VRM 规范":5,
  // 轮2：技法/中间产物此前漏配，被静默兜底成"效果分 6/10"（编造数据）。
  // 这里的分数表示"工艺成熟度/对成品质感的贡献"，非独立软件质量，仅用于同类排序。
  "IP-Adapter / FaceID":8,"InstantID / PuLID":8.5,"自训角色 LoRA":9,
  "三视图控制图":8,"抠图 / 净化":8,"锁 Seed 做变体":7.5
};
// 轮1：键必须与工具条目的 lic 字面值完全一致，否则 RISK[t.lic] 永不命中。
// 原键 "community" 与实际值 "社区许可" 不匹配，导致商用模式漏报风险最高的 Hunyuan3D 系列。
const RISK = {
  "社区许可":"社区许可：明确排除欧盟/英国/韩国且有大用户条款，商用前逐条读",
  "EULA":"EULA：源码可读但官方二进制需购买",
  "AGPL-3.0":"AGPL-3.0：有网络服务传染性（SaaS/网络服务亦受约束）",
  "GPL-3.0":"GPL-3.0：代码嵌入分发产品需履行 copyleft",
  "GPL-2.0":"GPL-2.0：代码嵌入分发产品需履行 copyleft",
  "LGPL-2.0":"LGPL-2.0：动态链接一般可闭源，静态链接或修改库需开源",
  "LGPL-3.0":"LGPL-3.0：动态链接一般可闭源，修改库需开源并允许反向工程"
};

/* ---------------------------------------------------------------- 自动化引擎：作业单编译
   把「给人看的步骤描述」翻译成「机器可执行的作业步骤」。
   映射原则：AI 生成/净化/重建类交给引擎，手绘/审美/驱动类标记人工并暂停交接。 */
const AUTO_STAGE = [
  // 匹配步骤标题关键词 → 执行类型（按顺序首个命中）。
  // 注意顺序：更具体的 image_to_3d 必须在宽泛的 text_to_image 之前，否则"图生 3D"会被"生图"抢走。
  {re:/图生 3D|图生3D|3D 模型|重建基准|进入重建/, kind:"image_to_3d"},
  {re:/净化|抠图|准备干净输入/, kind:"clean_image"},
  {re:/生图|辅助生成|AI 辅助|批量出|生成与导出|选择生成模型/, kind:"text_to_image"},
  {re:/切片|导出打印|切片设置/, kind:"slice"},
];
const HUMAN_STAGE = [
  {re:/起稿|手绘|画.*草图|设定基底|人体底模/, kind:"hand_draw", why:"手绘起稿需要人的创意，AI 无法替代"},
  {re:/精修|上色|面部|修脸|材质审美/, kind:"aesthetic_refine", why:"精修与审美判断需要人工"},
  {re:/驱动|面捕|展示/, kind:"facecap", why:"面捕驱动需要真人表演与设备"},
];
function stepKind(title){
  for(const m of AUTO_STAGE) if(m.re.test(title)) return m.kind;
  for(const m of HUMAN_STAGE) if(m.re.test(title)) return m.kind;
  return "human";   // 未识别的一律人工，保守
}
// 轮7：引擎里仍是占位、尚未真正接入执行器的类型——不能计入"可自动"，
// 否则页面承诺"可自动 N 步"，实际跑到那里却只是 pending，属于虚假承诺。
const NOT_READY_KINDS=new Set(["image_to_3d","clean_image"]);
// 由 profile 生成机器可读作业单（与任务包文本同源）
function buildJobSpec(p){
  const pk=promptPack(p);
  const steps=[];
  for(const wfId of (p.workflows||[])){
    const w=WORKFLOWS.find(x=>x.id===wfId); if(!w) continue;
    for(const sg of w.stages){
      const kind=stepKind(sg.title);
      steps.push({kind, label:`[${w.label}] ${sg.title}`, hint:sg.hint});
    }
  }
  return {
    name:p.proj||p.subject||"创作任务包",
    prompt_pos:pk.pos, prompt_neg:pk.neg,
    steps:steps,
    steps_total:steps.length,
    auto_count:steps.filter(s=>!HUMAN_STAGE.some(m=>m.kind===s.kind)
                  &&s.kind!=="human"&&!NOT_READY_KINDS.has(s.kind)).length,
  };
}

/* ---------------------------------------------------------------- 本地工具桥通信 */
const BRIDGE='http://127.0.0.1:7843';
// 轮12：兼容旧浏览器（无 AbortSignal.timeout）——用 AbortController + setTimeout 兜底
function timeoutFetch(url, opts, ms){
  const o = Object.assign({}, opts||{});
  if (typeof AbortSignal!=='undefined' && typeof AbortSignal.timeout==='function'){
    o.signal = AbortSignal.timeout(ms);
    return fetch(url, o);
  }
  const ctrl = (typeof AbortController!=='undefined') ? new AbortController() : null;
  if (ctrl){ o.signal = ctrl.signal; const t=setTimeout(()=>ctrl.abort(), ms);
    return fetch(url,o).finally(()=>clearTimeout(t)); }
  return fetch(url, o);   // 最坏情况：无超时，但至少能工作
}
let bridgeOn=false, toolStatus={};
const pendingTools=new Set();  // 轮5：正在启动/安装的工具 id
let detecting=false, detectGen=0;
let bridgeToken=null;  // 轮1：challenge token  // 轮9：桥探测互斥 + 代际（防旧结果覆盖新）
// 工具名 -> bridge id 映射（桥里注册的 19 个）
const T2B={
  'Krita':'krita','Blender':'blender','FreeCAD':'freecad','OpenSCAD':'openscad',
  'MeshLab':'meshlab','OpenToonz':'opentoonz','Cura':'cura','PrusaSlicer':'prusaslicer',
  'OrcaSlicer':'orcaslicer','UVtools':'uvtools','Aseprite':'aseprite','ComfyUI':'comfyui',
  'trimesh':'trimesh','CadQuery':'cadquery','Assimp':'assimp','smplx':'smplx',
  'excalidraw':'excalidraw','CharacterStudio':'charstudio','threestudio':'threestudio'
};
async function detectBridge(){
  // 轮9：并发互斥 + 代际淘汰——旧请求返回时若已有新请求就不覆盖
  if(detecting) return;
  detecting=true;
  const myGen=++detectGen;
  let on=false;
  try{
    const r=await timeoutFetch(BRIDGE+'/api/ping',{},1500);
    const d=await r.json();
    // 轮2：校验身份标识，挡住任意占用端口的假服务
    on = !!d.ok && d.service==='atlas-tool-bridge' && !!d.version;
    if(on){
      // 轮1：向桥申请 token（桥端校验 Referer 来自 studio.html）
      try{
        const cr=await timeoutFetch(BRIDGE+'/api/challenge',{},1500);
        const cd=await cr.json();
        bridgeToken = cd.ok ? cd.token : null;
      }catch(e){ bridgeToken=null; }
    } else bridgeToken=null;
  }catch(e){on=false; bridgeToken=null;}
  finally{ detecting=false; }
  if(myGen!==detectGen) return;   // 已有更新的探测在跑，本次结果作废
  bridgeOn=on;
  const bar=$('bridgeBar');
  bar.classList.toggle('on',bridgeOn);
  $('bridgeDot').style.background=bridgeOn?'var(--ok)':'var(--warn)';
  const authed = bridgeOn && !!bridgeToken;
  $('bridgeText').textContent = bridgeOn && !authed
    ? '检测到工具桥，但未通过安全校验（可能浏览器未发送来源信息）· 请改用内置浏览器打开本页'
    : authed
      ? '本地工具桥已连接 · 可点击启动 / 一键安装本机工具'
      : '本地工具桥未运行 · 工具仍可点开仓库页（想点击即启动，请启动工具桥）';
  $('bridgeStart').style.display=bridgeOn?'none':'inline-block';
  // 同步执行台引导条——用户真正要看"能不能执行"的地方就在这里
  const hint=$('execHint');
  if(hint){
    if(authed){
      hint.className='exec-hint ready';
      hint.innerHTML='✅ <span>工具桥已就绪：下方每个工具都可点「启动」打开本机软件，或「一键安装」尚未安装的。提示词已备好，复制即可用。</span>';
    } else if(bridgeOn && !authed){
      hint.className='exec-hint';
      hint.innerHTML='⚠️ <span>检测到工具桥，但未通过安全校验。请用内置浏览器或双击 <code>studio.html</code> 打开本页，再点顶部「刷新状态」。</span>';
    } else {
      hint.className='exec-hint';
      hint.innerHTML='⚠️ <span>「启动 / 安装」按钮需要本地工具桥。请双击 <code>快捷方式工具/start-tool-bridge.ps1</code>（选「用 PowerShell 运行」），然后点顶部「刷新状态」，下方按钮就会亮起。工具仍可点名字打开仓库页。</span>';
    }
  }
  if(bridgeOn) await loadToolStatus();
  else toolStatus={};
  refreshToolViews();
}
// 轮15：桥端状态检测最坏要 spawn 4 个子进程，3s 超时会静默失败（catch 吞掉），
// 导致所有已装工具被误显示成"一键安装"。超时提到 10s；安装后用 fresh=1 强制重算。
async function loadToolStatus(fresh){
  try{
    const r=await timeoutFetch(BRIDGE+'/api/status'+(fresh?'?fresh=1':''),{},10000);
    const d=await r.json();
    toolStatus={};
    (d.tools||[]).forEach(t=>toolStatus[t.id]=t);
  }catch(e){
    // 不再静默：状态拉取失败时明确告知，避免用户把"未装"误当成事实
    setStatus($('outStatus'),'工具状态获取失败，按钮可能显示为未安装；请点「刷新状态」重试。',true);
  }
}
async function callBridge(action,id,btn){
  if(!bridgeOn){setStatus($('outStatus'),'工具桥未运行，请先点上方「启动工具桥」。',true);return;}
  if(!bridgeToken){setStatus($('outStatus'),'工具桥未通过安全校验，请点「刷新状态」或改用内置浏览器打开本页。',true);return;}
  // 轮5：用 pending 数据模型而非 DOM 引用——重绘后状态仍然正确
  if(pendingTools.has(id)){setStatus($('outStatus'),'该工具正在处理中，请稍候。',true);return;}
  pendingTools.add(id);
  refreshToolViews();
  try{
    const r=await timeoutFetch(BRIDGE+'/api/'+action+'?id='+encodeURIComponent(id),
      {method:'POST',headers:{'Content-Type':'application/json','X-Bridge-Token':bridgeToken}},60000);
    const d=await r.json();
    setStatus($('outStatus'),d.message||'完成',!d.ok);
    if(action==='install') await loadToolStatus(true);   // 轮15：安装后强制重算状态
  }catch(e){
    setStatus($('outStatus'),'调用失败：'+(e&&e.message||String(e))+'。请点工具按钮重试。',true);
  }
  finally{
    pendingTools.delete(id);
    refreshToolViews();   // 统一重绘，按钮状态由 pending 集决定
  }
}
function refreshToolViews(){
  // 轮18：保存焦点——全量 innerHTML 重建会丢弃焦点，重建后按稳定 key 恢复
  const ae=document.activeElement;
  const key=ae && ae.dataset ? ae.dataset.focuskey : null;
  renderTools($('q').value);
  renderBranches();
  if(last && last.p) renderExec(last.p);
  if(key){
    try{
      const el=document.querySelector('[data-focuskey="'+CSS.escape(key)+'"]');
      if(el) el.focus();
    }catch(e){}
  }
}
function toolBtn(name){
  const id=T2B[name];
  if(!id) return `<span class="tbtn" title="技法/配方，依附 ComfyUI 或 Krita 使用，无需单独启动">依附使用</span>`;
  // 轮5：pending 优先——重绘后仍能正确显示"处理中"且禁用
  if(pendingTools.has(id)) return `<button class="tbtn" disabled>处理中…</button>`;
  const st=toolStatus[id];
  // 先算出"桥连通时本该是什么按钮"，与 bridgeOn 解耦。
  // 旧代码在桥未连接时直接 return ''，导致执行台所有按钮凭空消失，
  // 用户只看到一串工具名，误以为"没有地方执行"。
  let label, cls, action;
  if(st&&st.installed && st.kind==='cli') return `<span class="tbtn" title="命令行库，在脚本里 import 使用">命令行</span>`;
  else if(st&&st.installed && st.kind==='suite') return `<span class="tbtn" title="需先装框架与模型权重">需配置</span>`;
  else if(st&&st.installed){ label='启动'; cls='tbtn'; action='launch'; }
  else if(st&&st.kind==='web'){ label='打开'; cls='tbtn'; action='launch'; }
  else { label='一键安装'; cls='tbtn need'; action='install'; }
  if(!bridgeOn){
    // 桥未连：保留按钮形态但禁用，title 说明如何启用。用户能看见入口，不会再对着空气找执行按钮。
    return `<button class="${cls}" disabled title="需先启动本地工具桥：双击 快捷方式工具/start-tool-bridge.ps1，然后回来点「刷新状态」">${label}</button>`;
  }
  return `<button class="${cls}" data-${action}="${id}" data-focuskey="${action}:${id}">${label}</button>`;
}
function bindToolBtns(root){
  (root||document).querySelectorAll('[data-launch]').forEach(b=>b.onclick=()=>callBridge('launch',b.dataset.launch,b));
  (root||document).querySelectorAll('[data-install]').forEach(b=>b.onclick=()=>callBridge('install',b.dataset.install,b));
}

/* ---------------------------------------------------------------- 工作流状态 */
let selectedWf = new Set();               // 当前选中的工作流 id
const collapsedBranches=new Set();        // 轮8：用户手动收起的支线
const openFolds=new Set();                 // 轮8：用户手动展开的详情
function toolByName(n){ return GROUPS.flatMap(g=>g.tools).find(x=>x.n===n); }

/* ---------------------------------------------------------------- 工具函数 */
const $ = id => document.getElementById(id);
// 轮9：空值归一——否则缺字段的历史记录会在页面上渲染出字面量 "undefined"/"null"
function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function safeName(s){
  let r=String(s||"").replace(/[\\/:*?"<>|]/g,"_")     // 非法标点
    .replace(/[\x00-\x1f\x7f]/g,"_")                  // 轮13：控制字符
    .replace(/[.\s]+$/g,"")                            // 轮13：尾随点/空格
    .trim();
  if(/^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)/i.test(r)) r="_"+r;  // 轮13：Windows 保留名
  r=Array.from(r).slice(0,50).join("");                  // 轮13：按 Unicode 码点截断（不切代理对）
  return r||"创作任务包";
}
// 轮7：Markdown 专用转义——用户输入进入 .md 前压平换行、转义结构标记，避免破坏表格/代码块
function mdInline(v){
  return String(v==null?"":v)
    .replace(/\r\n?/g," ").replace(/\n/g," ")       // 多行压成一行
    .replace(/`/g,"\\`")                             // 反引号避免闭合代码围栏
    .replace(/\|/g,"\\|")                           // 竖线避免破坏表格
    .replace(/^([\s]*)([#>\-+])([\s])/gm,"$1\\$2$3")  // 行首结构符转义
    .trim();
}
// 轮6：提示词正文专用清洗。与 mdInline 的区别——提示词里逗号、竖线、括号都是合法
// 语义标点，不能转义；只需压平换行/控制字符、转义反引号以免闭合 Markdown 代码围栏。
function promptSafe(v){
  return String(v==null?"":v)
    .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/g," ")
    .replace(/\r\n?/g," ").replace(/\n/g," ")
    .replace(/`/g,"\\`")
    .trim();
}
function stamp(){const d=new Date(),p=n=>String(n).padStart(2,"0");return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;}
function setStatus(el,msg,err){el.textContent=msg;el.classList.toggle("err",!!err);}

/* ---------------------------------------------------------------- 表单 */
function buildGoals(){
  // 兼容：原 GOALS 仍用于任务包分类标签；界面改用 WORKFLOWS 选择器
  $("wfGrid").innerHTML = WORKFLOWS.map((w,i)=>
    `<div class="wf-card" data-wf="${w.id}" style="--wfc:${w.color}" role="button" tabindex="0"
       aria-pressed="false">
       <span class="wf-n">${i+1}</span>
       <div class="wf-ic">${w.icon}</div>
       <div class="wf-lb">${esc(w.label)}</div>
       <div class="wf-tg">${esc(w.tagline)}</div>
     </div>`).join("");
  $("wfGrid").querySelectorAll(".wf-card").forEach(c=>{
    const pick=()=>{ const id=c.dataset.wf;
      if(selectedWf.has(id)) selectedWf.delete(id); else selectedWf.add(id);
      renderWfSelect(); renderBranches(); checkDirty();
    };
    c.addEventListener("click",pick);
    c.addEventListener("keydown",e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick();}});
  });
}
function renderWfSelect(){
  $("wfGrid").querySelectorAll(".wf-card").forEach(c=>{
    const on=selectedWf.has(c.dataset.wf);
    c.classList.toggle("on",on);
    c.setAttribute("aria-pressed",on?"true":"false");
    c.querySelector(".wf-n").textContent=on?"✓":(WORKFLOWS.findIndex(w=>w.id===c.dataset.wf)+1);
  });
}
function renderBranches(){
  const box=$("wfBranches");
  if(!selectedWf.size){
    box.innerHTML=`<div class="wf-empty"><span class="big">◎</span>上面选一条工作流，这里会出现它的专属支线：按顺序列出工具、操作提示和避坑要点。</div>`;
    return;
  }
  box.innerHTML=WORKFLOWS.filter(w=>selectedWf.has(w.id)).map(w=>`
    <div class="branch" style="--bfc:${w.color}" data-branch="${w.id}">
      <div class="branch-hd"><div class="bi">${w.icon}</div>
        <div><h3>${esc(w.label)}</h3><div class="bt">${esc(w.tagline)}</div></div>
        <button class="bswitch" data-hide="${w.id}" aria-expanded="${!collapsedBranches.has(w.id)}">${collapsedBranches.has(w.id)?'展开支线':'收起支线'}</button>
      </div>
      <div class="branch-body" ${collapsedBranches.has(w.id)?'style="display:none"':''}>
        <p class="intro">${esc(w.intro)}</p>
        ${w.stages.map((sg,i)=>`
          <div class="flow-step">
            <div class="sn">${i+1}</div>
            <div><div class="sh">${esc(sg.title)}</div>
              <div class="si">${esc(sg.hint)}</div>
              <div class="stools">${sg.tools.map(n=>{
                const t=toolByName(n);
                return `<span class="tag" title="${t?esc(t.note):''}">${esc(n)}</span>${toolBtn(n)}`;
              }).join('')}</div>
            </div>
          </div>`).join('')}
        <div class="branch-tips"><b>💡 这条支线的提示</b>
          <ul>${w.tips.map(t=>`<li>${esc(t)}</li>`).join('')}</ul>
        </div>
        <details class="fold" data-fold="${w.id}" ${openFolds.has(w.id)?'open':''}>
          <summary>本支线未用到、但相关的其他工具（按需探索）</summary>
          <div class="fold-body">${relatedOthers(w)}</div>
        </details>
        <div class="branch-cta">
          <span class="ctatx">要一份可复制、可导出的完整任务包？填几项参数即可生成。</span>
          <button class="quick" data-make="${w.id}">用这条工作流生成任务包 →</button>
        </div>
      </div>
    </div>`).join('');
  box.querySelectorAll("[data-hide]").forEach(b=>b.onclick=()=>{
    const el=box.querySelector(`[data-branch="${b.dataset.hide}"]`);
    const body=el.querySelector(".branch-body");
    const id=b.dataset.hide;
    if(collapsedBranches.has(id)){ collapsedBranches.delete(id); body.style.display='';
      b.textContent='收起支线'; b.setAttribute('aria-expanded','true'); }
    else { collapsedBranches.add(id); body.style.display='none';
      b.textContent='展开支线'; b.setAttribute('aria-expanded','false'); }
  });
  box.querySelectorAll("details[data-fold]").forEach(d=>{
    d.ontoggle=()=>{ if(d.open) openFolds.add(d.dataset.fold); else openFolds.delete(d.dataset.fold); };
  });
  bindToolBtns(box);
  box.querySelectorAll("[data-make]").forEach(b=>b.onclick=()=>{
    $("paramsFold").open=true;                 // 展开参数区
    if(!$("proj").value && !$("subject").value){ // 用工作流标签预填，省去从零输入
      $("proj").value=WORKFLOWS.find(x=>x.id===b.dataset.make).label+" · 任务";
    }
    $("paramsFold").scrollIntoView({behavior:'smooth',block:'start'});
    setStatus($("status"),"已展开参数区，填好主体后点「生成创作任务包」。");
  });
}
function relatedOthers(w){
  const used=new Set(w.stages.flatMap(s=>s.tools));
  const all=GROUPS.flatMap(g=>g.tools);
  const rel=all.filter(t=>!used.has(t.n) && t.roles.some(r=>(w.goalIds||[]).includes(r)));
  const list=(rel.length?rel:all.filter(t=>!used.has(t.n)).slice(0,8));
  return `<div class="tools">`+list.map(t=>`<div class="tool">
    <div class="tn"><a href="${t.u}" target="_blank" rel="noopener noreferrer">${esc(t.n)}</a>
    <span class="badge ${t.tier}">${TIER_LABEL[t.tier]}</span>${toolBtn(t.n)}</div>
    <div class="note">${esc(t.note)}</div></div>`).join('')+`</div>`;
}
function profile(){
  // 从选中的工作流映射出 goals（兼容任务包与执行台的原有逻辑）
  const goals=[...new Set([...selectedWf].flatMap(id=>{
    const w=WORKFLOWS.find(x=>x.id===id); return w?w.goalIds:[];
  }))];
  // 轮1：收集选中工作流 stages 里显式点名的工具，作为强制适用集合
  const stageTools=[...new Set([...selectedWf].flatMap(id=>{
    const w=WORKFLOWS.find(x=>x.id===id); return w?w.stages.flatMap(sg=>sg.tools):[];
  }))];
  return {
    proj:$("proj").value.trim(), subject:$("subject").value.trim(),
    goals, workflows:[...selectedWf], stageTools,
    style:$("style").value, vram:parseInt($("vram").value,10),
    usage:$("usage").value, comm:$("comm").value,
    extra:$("extra").value.trim()
  };
}

/* ---------------------------------------------------------------- 轮4：脏状态检测 */
function profileSig(p){ return JSON.stringify({
  workflows:(p.workflows||[]).slice().sort(), goals:(p.goals||[]).slice().sort(),
  proj:p.proj, subject:p.subject, style:p.style, vram:p.vram,
  usage:p.usage, comm:p.comm, extra:p.extra
}); }
let lastSig=null;
function checkDirty(){
  if(!last || !lastSig){return;}
  const now=profileSig(profile());
  const dirty = now!==lastSig;
  $("dirtyNote").style.display = dirty?'block':'none';
  // 轮19：读屏播报靠文本变化（display 切换不触发 aria-live）
  $("dirtyLive").textContent = dirty ? '需求已变更，当前任务包已过期，请重新生成。' : '';
  ["save","download","print"].forEach(id=>$(id).disabled=dirty);
}
// 轮8：允许显式指定签名——载入历史时用它保存时的 sig，而不是拿"当前表单"重算。
function markClean(sig){ lastSig = sig!==undefined ? sig : (last?profileSig(profile()):null);
  $("dirtyNote").style.display='none';
  if($("dirtyLive"))$("dirtyLive").textContent=''; }

/* ---------------------------------------------------------------- 优中选优 */
function applicable(t,p){
  if(!t.roles||t.roles.length===0) return true;          // 通用工具恒可用
  if((p.stageTools||[]).includes(t.n)) return true;      // 轮1：支线显式点名的工具强制适用
  return p.goals.length===0 || t.roles.some(r=>p.goals.includes(r));
}
function rankTools(group,p){
  return group.tools.map(t=>{
    // 轮2：兜底值只参与排序，不再对外谎称"效果分 6/10"。
    // 数据缺失时显示"未评分（数据待补）"，让缺口可见而不是被伪造的分数掩盖。
    const scored = Object.prototype.hasOwnProperty.call(QUALITY,t.n);
    const q = scored ? QUALITY[t.n] : 6;
    // 效果优先：质量分主导(乘 10)，tier 仅作次要修正；显存不再是排序主因。
    let rank = (10 - q) * 10 + (TIER_RANK[t.tier] ?? 6);
    let why  = scored ? "效果分 " + q + "/10" : "未评分（数据待补）";
    // 轮9：专用工具优先于通用工具——精准命中当前目标的加权提前，
    // 完全通用的工具(roles 为空)轻微后置，确保工具链首选与支线 stages 一致。
    const gs=p.goals||[];
    const hit = (t.roles||[]).some(r=>gs.includes(r));
    if(hit){ rank -= 30; why += "；专为本目标挑选"; }
    else if(gs.length && (!t.roles||!t.roles.length)){ rank += 5; why += "；通用工具"; }
    // 显存不足：仍会标注，但只小幅影响排序（用户说性能暂不考虑）
    if(t.vram>p.vram){
      rank += 2;
      why += p.vram===0 ? "；需显卡，无卡可云端体验"
                        : `；需≥${t.vram}GB(当前${p.vram}GB)`;
    }
    // 商用场景：高风险许可附警示
    if(p.comm==="yes" && RISK[t.lic]){
      rank += 3;
      why += "；" + RISK[t.lic];
    }
    return {...t, rank, q, why};
  }).sort((a,b)=>a.rank-b.rank);
}

/* ---------------------------------------------------------------- 提示词包 */
function promptPack(p){
  // 轮6：主体/补充是自由文本，进提示词前压平换行并转义反引号；
  // 提示词里竖线、逗号是合法语义标点，故用 promptSafe 而非 mdInline。
  const subj = promptSafe(p.subject) || "原创角色";
  const feat = p.extra ? "，" + promptSafe(p.extra) : "";
  // 依据选中工作流的 promptKind 生成专属提示词（多选时取第一条主工作流）
  const wf = (p.workflows||[]).map(id=>WORKFLOWS.find(w=>w.id===id)).filter(Boolean)[0];
  const kind = wf ? wf.promptKind : "character";
  const POS = {
    character: `${subj}，${p.style}，角色设定图，完整全身，居中构图，单人，干净白底，平光均匀照明，\n高细节，清晰线稿，锐利焦点，8k，masterpiece, best quality, character sheet,\n正面视角，比例准确，无遮挡${feat}`,
    triview:   `${subj}，${p.style}，角色三视图设定，正面/侧面/背面并列，同一角色，尺寸一致，顺序固定，\n白色背景，平光，均匀照明，比例统一，清晰线稿，8k，character turnaround sheet，\n无遮挡，无透视变形${feat}`,
    to3d:      `${subj}，single object，isolated on pure white background，flat even lighting，\ncentered，front or 3/4 view，high detail texture，clean topology reference，\nno shadow，no props，no text，8k，photorealistic${feat}`,
    print:     `${subj}，3D printable model reference，solid watertight form，uniform gray clay material，\nneutral studio lighting，front view，no thin walls，no floating parts，\nclean silhouette，technical design render${feat}`,
    pixel:     `${subj}，pixel art，16-bit style，limited palette，crisp pixels，no anti-aliasing，\nsprite sheet ready，front-facing， clean outline${feat}`,
    cad:       `${subj}，parametric CAD part，orthographic view，technical drawing，precise dimensions，\nblueprint style，clean edges，engineering sketch，isolated on white${feat}`,
    texture:   `${subj}，PBR material sphere reference，albedo/roughness/normal maps，\nneutral lighting，tileable texture，material study，8k detail${feat}`,
    // 轮4：VRM 需要 T-pose/中性表情/可绑定人体，与"角色设定图"模板语义不同，不再复用 character
    vrm:       `${subj}，${p.style}，VRM 1.0 avatar reference，full body，front view，T-pose / A-pose，\nneutral expression，symmetric，clean white background，flat even lighting，\nvisible joints for rigging，separate hair and clothing，clear silhouette，8k${feat}`,
    // 轮4：重建基准图强调"净化后的单对象输入"，与三视图并列排版模板不同
    rebuild:   `${subj}，${p.style}，single clean object，pure white / transparent background，\nflat even lighting，no cast shadow，no props，no watermark，no text，centered，\nfront or 3/4 view，1024px+，high detail texture，clean topology reference${feat}`
  };
  const NEG = {
    character: `lowres, blurry, jpeg artifacts, watermark, text, signature, logo, extra limbs,\nbad anatomy, deformed hands, mutated fingers, missing fingers, extra fingers,\nmultiple people, cropped, out of frame, cluttered background, heavy shadow,\nnsfw, glowing weapon, distorted face`,
    triview:   `different characters, inconsistent proportions, mismatched outfits, perspective distortion,\nrotated views, cluttered background, multiple angles in one view, text, watermark,\ncropped, blurry, uneven lighting`,
    to3d:      `multiple objects, busy background, strong shadows, text, watermark, transparent effects,\nhair strands, fine filaments, reflections, overlapping parts, low resolution`,
    print:     `thin fragile parts, hollow shell without walls, overhangs without support, floating pieces,\ncomplex interlocking parts, textures, colors, background, text`,
    pixel:     `anti-aliasing, smooth gradients, photorealism, 3D render, blurry, jpeg artifacts,\ntoo many colors, dithering artifacts, watermark, text`,
    cad:       `organic shape, freeform sculpture, realistic texture, hand-drawn, perspective distortion,\ncolors, shading, background, text, watermark`,
    texture:   `baked lighting, shadows in albedo, non-tileable seams, low resolution, blurry,\nwatermark, text, background objects`,
    vrm:       `dynamic pose, action shot, perspective distortion, strong expression, cropped,\nmultiple characters, busy background, complex accessories, text, watermark, blurry`,
    rebuild:   `multiple objects, busy background, strong shadows, ground plane, reflections,\ntext, watermark, jpeg artifacts, hair strands, fine filaments, low resolution`
  };
  const pos = POS[kind] || POS.character;
  const neg = NEG[kind] || NEG.character;
  const tri =
`【三视图 / 重建基准图规格（8 条硬规则）】
1 白底或透明底，平光，单对象，正面或 3/4 视角
2 分辨率 1024² 以上，正/侧/后三视图尺寸一致、顺序固定
3 不换提示词，只换控制图（OpenPose / Depth / Canny）来切视角
4 一致性权重：IP-Adapter / FaceID 从 0.6 起，>0.8 僵硬、<0.5 锁不住
5 系列化/量产改用 20–30 张多角度图自训 LoRA
6 锁 Seed，只调 CFG / Denoise 出变体
7 生成后必须净化：Rembg 抠图 / LaMa / 去水印 / ColorMatch / FaceDetailer
8 输出干净 PNG 再进重建；脏数据进图生 3D 等于埋雷`;
  const params = p.vram===0
    ? "本地无卡：整条 AI 链路改用云端（Hugging Face Space / 在线 ComfyUI），本地只做绘画与修模。"
    : `显存 ${p.vram}GB 起步参数：先跑一张 512² 小图验证链路，再上 1024²；`+
      `CFG 7 左右、Denoise 0.5–0.65 起试；不要第一步就勾 Flux / Z-Image 等大模型。`;
  return {pos,neg,tri,params};
}

/* ---------------------------------------------------------------- 执行清单 */
function steps(p){
  // 优先从选中工作流 stages 生成执行清单（与任务包第3节、执行台同源）
  if(p.workflows&&p.workflows.length){
    const wss=p.workflows.map(id=>WORKFLOWS.find(w=>w.id===id)).filter(Boolean);
    const S=[];
    wss.forEach(w=>{
      S.push(`【${w.label}】`);
      w.stages.forEach((sg,i)=>S.push(`  ${i+1}. ${sg.title}：${sg.hint}（工具：${sg.tools.join(" → ")}）`));
    });
    return S;
  }
  // 兼容旧任务包：按 goals 条件追加，不再无条件塞"装机/起稿"
  const g=new Set(p.goals||[]);
  const S=[];
  if(g.has("character")||g.has("triview")||g.has("to3d"))
    S.push("阶段 0 · 装机：确认 Krita ≥5.2.0 + Krita AI Diffusion 插件 + ComfyUI 能连通；先跑 512² 小图验证链路。");
  if(g.has("character"))
    S.push("阶段 1 · 起稿：在 Krita 画出角色基底，用选区生成 / Live Painting / 控制层反复迭代，保留分层源文件。");
  if(g.has("triview"))
    S.push("阶段 2 · 三视图：预置骨架/深度控制图，固定提示词切三视角，锁 Seed 出变体，输出尺寸一致的正/侧/后三视图。");
  if(g.has("to3d"))
    S.push("阶段 3 · 图生 3D：把净化后的干净 PNG 送进重建模型，导出 GLB / OBJ。");
  if(g.has("texture")) S.push("阶段 3b · 贴图：在 ArmorPaint / Blender 中绘制或烘焙 PBR 贴图，检查 UV 与法线。");
  if(g.has("cad")) S.push("阶段 3c · 参数化零件：用 FreeCAD / OpenSCAD / CadQuery 建模，导出 STL 后与角色网格合体。");
  if(g.has("print")) S.push("阶段 4 · 修模与切片：Blender 查漏面，trimesh 校验，OrcaSlicer/UVtools 切片，先打小样。");
  if(g.has("vrm")) S.push("阶段 4b · VRM：Blender + VRM Add-on 导出 VRM 1.0，three-vrm 网页验证，VSeeFace 面捕试跑。");
  if(g.has("pixel")) S.push("阶段 2b · 动画：Aseprite（像素逐帧）或 OpenToonz（2D 动画）导出精灵表 / 序列帧。");
  S.push("阶段 6 · 交付：整理分层源文件、提示词、Seed、模型与截图；保留人工修改痕迹作为合规与质量证据。");
  return S;
}

/* ---------------------------------------------------------------- 任务包生成 */
function buildPackage(p){
  const L=[];
  const goalNames=p.goals.length?p.goals.map(id=>(GOALS.find(g=>g.id===id)||{}).label).filter(Boolean).join(" / "):"通用创作";
  L.push(`# 创作任务包：${mdInline(p.proj)||"未命名项目"}`,"");
  L.push(`> 生成时间：${stamp()}　|　由「创作工具星图 · 创作工坊」本地生成，输入未上传`);
  L.push(`> 数据口径：工具星数/许可为 2026-11-16 前后公开快照，会浮动；参数为社区经验值，属起点参考。`, "");
  L.push("## 1. 任务概要","");
  L.push(`- 项目：${mdInline(p.proj)||"未命名项目"}`);
  L.push(`- 主体：${mdInline(p.subject)||"原创角色"}`);
  L.push(`- 目标：${goalNames}`);
  L.push(`- 风格：${p.style}`);
  L.push(`- 用途：${p.usage}${p.comm==="yes"?"（商用：需核对许可）":"（非商用）"}`);
  L.push(`- 硬件：${p.vram===0?"无本地卡 / 走云端":p.vram+" GB 显存"}`);
  if(p.workflows&&p.workflows.length){
    const wfNames=p.workflows.map(id=>{const w=WORKFLOWS.find(x=>x.id===id);return w?w.label:id;});
    L.push(`- 工作流：${wfNames.join(" / ")}`);
  }
  if(p.extra) L.push(`- 补充：${mdInline(p.extra)}`);
  L.push("","## 2. 提示词包（可直接粘贴）","");
  const pk=promptPack(p);
  L.push("### 正面提示词","", "```text", pk.pos, "```","");
  L.push("### 负面提示词","", "```text", pk.neg, "```","");
  L.push("### 三视图 / 重建基准图规格","", "```text", pk.tri, "```","");
  L.push("### 参数建议","", pk.params,"");
  // 新增：按工作流的分阶段执行路径（任务包自带，无需跳回页面）
  if(p.workflows&&p.workflows.length){
    L.push("## 3. 工作流执行路径（按序开工）","");
    (p.workflows.map(id=>WORKFLOWS.find(w=>w.id===id)).filter(Boolean)).forEach(w=>{
      L.push(`### ${w.icon} ${w.label}`,"",w.intro,"");
      w.stages.forEach((sg,i)=>{
        const names=sg.tools.join(" → ");
        L.push(`${i+1}. **${sg.title}**：${sg.hint}`);
        L.push(`   - 工具：${names}`);
      });
      L.push("","   提示：","");
      w.tips.forEach(t=>L.push(`   - ${t}`));
      L.push("");
    });
  }
  L.push("## 4. 工具链 · 效果优先（性能仅作参考）","");
  L.push("> 排序以产出质量为主，显存/性能仅标注不主导。每个推荐位附「为什么」一句话。","");
  L.push("| 环节 | 首选（为什么） | 备选（为什么） |","|---|---|---|");
  const chosen=[], downgraded=[];
  for(const grp of GROUPS){
    const ranked=rankTools(grp,p);
    const pool=ranked.filter(t=>applicable(t,p));
    if(!pool.length) continue;
    const first=pool[0], alts=pool.slice(1,3);
    chosen.push(...pool);
    // 只收录"真正因显存/许可被降级"的工具；"效果分 X/10"是常态说明，不算降级。
    // 同时排除本环节的首选/备选，避免"推荐它"与"别开工"自相矛盾。
    const featured=new Set([first.n,...alts.map(t=>t.n)]);
    for(const t of ranked){
      const realDown = /；需≥|；需本地显卡|；社区许可|；EULA|；AGPL|；GPL-3\.0/.test(t.why||"");
      if(realDown && applicable(t,p) && !featured.has(t.n)) downgraded.push({n:t.n,why:t.why});
    }
    const why1 = (first.note||"").split("。")[0] + "。";
    const whyAlt = alts.map(t=>`${t.n}：${(t.note||"").split("。")[0]}。`).join(" ");
    L.push(`| ${grp.name} | **[${first.n}](${first.u})** — ${why1}`+
           ` | ${alts.map(t=>`[${t.n}](${t.u})`).join(" / ")||"—"}`+
           `${whyAlt?"<br>"+whyAlt:""} |`);
  }
  if(downgraded.length){
    L.push("","**适配提示（下列工具有显存/许可限制，开工前先确认）**","");
    const seen=new Set();
    for(const d of downgraded){
      if(seen.has(d.n))continue;seen.add(d.n);
      L.push(`- ${d.n}：${d.why}`);
    }
  }
  L.push("","## 5. 执行清单","");
  steps(p).forEach(s=>L.push(`- [ ] ${s}`));
  L.push("","## 6. 许可证与避坑","");
  if(p.comm==="yes"){
    L.push("**商用模式：以下高风险项必须逐条确认**","");
    const seen=new Set();
    for(const t of chosen){
      if(RISK[t.lic] && !seen.has(t.lic)){seen.add(t.lic);L.push(`- ${t.n}（${t.lic}）：${RISK[t.lic]}`);}
    }
    L.push("- 模型权重条款各不相同：商用前逐个查模型卡与训练数据版权。");
    L.push("- 纯 AI 生成图像的著作权认定各地不一，建议保留人工修改痕迹与分层源文件。");
    L.push("- 优先 MIT 的下游 3D 模型（TripoSR / TRELLIS）；做周边售卖前逐项确认。");
  } else {
    L.push("- 自己画画、公司内部使用、不分发：通常无 copyleft 义务，但仍建议留分层源文件。");
    L.push("- 若日后转商用，重跑本工坊并选「需要商用」，会列出全部高风险许可项。");
  }
  L.push("- 高星 ≠ 还活着：ControlNet（34.1k ★）停在 2024-02，InstantMesh / Fooocus / A1111 也明显放缓；看 star 前先看 pushed_at。");
  L.push("- 仓库会搬家：ComfyUI 已迁 Comfy-Org，blender-mcp 更名 mcp-for-blender，OrcaSlicer 迁组织账号；Blender / Krita 在 GitHub 只是镜像。");
  L.push("- 最后一公里：AI 网格通常不能直接打印，漏面/非流形/薄壁/空腔必须靠 Blender + trimesh + UVtools 收尾。");
  L.push("","## 7. 全部工具索引（星图收录，按需取用）","");
  for(const grp of GROUPS){
    L.push(`**${grp.name}**：` + grp.tools.map(t=>`[${t.n}](${t.u})`).join(" · "),"");
  }
  L.push("---","本任务包由本地静态页面生成，不含自动执行脚本；所有命令与菜单路径均为人工操作说明。");
  return {text:L.join("\n"), prompt:`【正面】\n${pk.pos}\n\n【负面】\n${pk.neg}\n\n${pk.tri}\n\n${pk.params}`};
}

/* ---------------------------------------------------------------- 工具全览 */
function renderTools(term){
  term=(term||"").trim().toLowerCase();
  let count=0;
  $("toolList").innerHTML = GROUPS.map(grp=>{
    const list=grp.tools.filter(t=>!term||(t.n+" "+t.note+" "+(t.roles||[]).join(" ")+" "+grp.name).toLowerCase().includes(term));
    if(!list.length) return "";
    count+=list.length;
    return `<div class="group"><h3><span class="dot" style="background:${grp.color}"></span>${esc(grp.name)}`+
      `<span class="cnt">${list.length} 个</span></h3><div class="tools">`+
      list.map(t=>{
        const bid=T2B[t.n], st=bid?toolStatus[bid]:null;
        const localBadge = st ? (st.installed
          ? '<span class="badge local">本机已装</span>'
          : '<span class="badge miss">本机未装</span>') : '';
        return `<div class="tool">
        <div class="tn"><a href="${t.u}" target="_blank" rel="noopener noreferrer">${esc(t.n)}</a>
        <span class="badge ${t.tier}">${TIER_LABEL[t.tier]}</span>${localBadge}${toolBtn(t.n)}</div>
        <div class="meta">${esc(t.s)}　·　${esc(t.lic)}${t.vram?"　·　≥"+t.vram+"GB":""}</div>
        <div class="note">${esc(t.note)}</div></div>`;
      }).join("")+
      `</div></div>`;
  }).join("") || `<p>没有匹配的工具，换个关键词试试。</p>`;
  $("filter-status").textContent = `匹配 ${count} 个工具`;
  bindToolBtns($("toolList"));
}

/* ---------------------------------------------------------------- 本地留存 */
// 轮4：命名空间 + 版本隔离，避免与同源其他应用/旧版互相覆盖
const HKEY="atlas:studio:v1.9:history";
const HKEY_LEGACY="atlas-studio-history";
// 一次性迁移旧键数据（仅当新键不存在时）
try{
  if(!localStorage.getItem(HKEY) && localStorage.getItem(HKEY_LEGACY)){
    localStorage.setItem(HKEY,localStorage.getItem(HKEY_LEGACY));
  }
}catch(e){}
function getHist(){
  try{
    const a=JSON.parse(localStorage.getItem(HKEY)||"[]");
    // 轮3：过滤非对象元素；轮9：再校验必要字段类型，缺 text/name 的损坏记录不进入列表，
    // 避免载入后把 undefined 塞进任务包输出区（篡改存储 / 旧版遗留数据）。
    return Array.isArray(a)?a.filter(h=>h&&typeof h==='object'&&!Array.isArray(h)
      && typeof h.text==='string' && typeof h.name==='string'
      && (h.prompt===undefined || typeof h.prompt==='string')):[];
  }catch(e){return [];}
}
function setHist(a){try{localStorage.setItem(HKEY,JSON.stringify(a.slice(0,20)));return true;}catch(e){return false;}}
// 轮8：载入历史时把表单恢复到生成时的参数，让"输出 / 执行台 / 脏检测 / 保存去重"四者同源。
// 只重置输出文本而不管表单，会让 lastSig 指向另一份内容，save 的 sig 与 text 错配。
function restoreProfile(p){
  if(!p||typeof p!=='object') return false;
  const fields={proj:"",subject:"",style:"干净赛璐璐平涂",vram:"12",usage:"个人练习",comm:"no",extra:""};
  for(const id in fields){
    const el=$(id); if(!el) continue;
    const v=(p[id]===undefined||p[id]===null)?fields[id]:String(p[id]);
    el.value=v;
    if(el.tagName==='SELECT' && el.value!==v) el.value=fields[id]; // 值已被移除的选项回退默认
  }
  const valid=new Set(WORKFLOWS.map(w=>w.id));
  selectedWf=new Set((Array.isArray(p.workflows)?p.workflows:[]).filter(id=>valid.has(id)));
  try{ renderWfSelect(); renderBranches(); }catch(e){}
  return true;
}
function renderHist(){
  const a=getHist();
  $("hist").innerHTML = a.length ? `<ul>${a.map((h,i)=>
    `<li><span class="t">${esc(h.time)}</span><span>${esc(h.name)}</span>
     <button data-i="${i}" class="load">载入</button><button data-i="${i}" class="del">删除</button></li>`).join("")}</ul>`
    : `<ul><li>暂无留存记录。</li></ul>`;
  $("hist").querySelectorAll(".load").forEach(b=>b.addEventListener("click",()=>{
    const h=getHist()[+b.dataset.i]; if(!h)return;
    $("output").textContent=h.text;
    // 轮19：恢复作业单——否则载入历史后一键执行按钮还在，last.jobSpec 却是空的，点了报错
    last={text:h.text,prompt:h.prompt,name:h.name,p:h.p||null,goals:h.goals||[],
          jobSpec:h.jobSpec||null};
    if($("autoPanel")){
      $("autoPanel").style.display=h.jobSpec?'block':'none';
      if(h.jobSpec){
        $("autoRun").disabled=false;
        $("autoMeta").textContent=`${h.jobSpec.steps_total||0} 步 · 可自动 ${h.jobSpec.auto_count||0} 步（历史记录）`;
      }
    }
    // 有 p 就按工作流渲染执行台；旧记录退化为 goals 驱动（保持历史包可用）
    const ep = h.p || (h.goals ? {goals:h.goals,workflows:[],style:h.style||"干净赛璐璐平涂",
                vram:12,comm:"no",subject:"",extra:""} : null);
    try{ renderExec(ep); }
    catch(e){ renderExec(null); setStatus($("outStatus"),"历史记录格式异常，已跳过执行台渲染。",true); }
    // 轮8：载入即把表单恢复到生成时参数，并用该历史记录的原始 sig 建立脏检测基准。
    // 否则 lastSig 仍指向"上次生成"或另一份表单，改一字段就误报过期、save 的 sig 与 text 错配。
    restoreProfile(h.p);
    // 有原始 sig 就沿用（与 text 完全同源）；旧格式没有，则用恢复后的表单重建基准。
    if(typeof h.sig==='string' && h.sig) markClean(h.sig);
    else markClean();
    ["copy","copyPrompt","download","save","print"].forEach(id=>$(id).disabled=false);
    setStatus($("outStatus"),`已载入：${h.name}${h.p?"（执行台已恢复）":"（旧格式，执行台按目标恢复）"}`);
  }));
  $("hist").querySelectorAll(".del").forEach(b=>b.addEventListener("click",()=>{
    const a2=getHist(); a2.splice(+b.dataset.i,1); setHist(a2); renderHist();
    setStatus($("outStatus"),"已删除该留存记录。");
  }));
}


/* ---------------------------------------------------------------- 执行台：任务包直接流入 */
function renderExec(p){
  if(!p || typeof p!=='object'){$("execEmpty").style.display='block';$("execStages").innerHTML='';return;}
  // 轮2：畸形 localStorage 数据兜底——workflows/goals 必须是数组
  if(!Array.isArray(p.workflows)) p.workflows=[];
  if(!Array.isArray(p.goals)) p.goals=[];
  if(typeof p.subject!=='string') p.subject='';
  if(typeof p.extra!=='string') p.extra='';
  $("execEmpty").style.display='none';
  const g=new Set(p.goals||[]);
  const pk=promptPack(p);
  // 若选了工作流：执行台直接用工作流 stages（与支线一致），不再混用旧逻辑
  if(p.workflows&&p.workflows.length){
    const wss=p.workflows.map(id=>WORKFLOWS.find(w=>w.id===id)).filter(Boolean);
    $("execStages").innerHTML=wss.map(w=>`
      <div class="stage" style="border-left:3px solid ${w.color}">
        <h4 aria-level="3">${w.icon} ${esc(w.label)}</h4>
        ${w.stages.map((sg,i)=>`
          <div style="margin:8px 0 12px 4px">
            <div style="font-size:12.5px;font-weight:600;color:var(--text)">${i+1}. ${esc(sg.title)}</div>
            <div style="font-size:11.5px;color:var(--muted);margin:3px 0 6px">${esc(sg.hint)}</div>
            <div class="tools">${sg.tools.map(n=>`<span class="tag">${esc(n)}</span>${toolBtn(n)}`).join('')}</div>
          </div>`).join('')}
        <div class="pt">💡 ${w.tips.map(esc).join(' · ')}</div>
      </div>`).join('');
    bindToolBtns($("execStages"));
    return;
  }
  // 兼容旧任务包（无 workflows 字段）：沿用原目标驱动逻辑
  const stages=[];
  stages.push({title:'阶段 0 · 起稿与设定', tools:['Krita','Krita AI Diffusion'], pt:pk.pos});
  if(g.has('triview')||g.has('to3d')||g.has('print'))
    stages.push({title:'阶段 1 · 三视图 / 重建基准图', tools:['ComfyUI','ControlNet'], pt:pk.tri});
  if(g.has('to3d'))
    stages.push({title:'阶段 2 · 图生 3D（效果优先）', tools:['TRELLIS / TRELLIS.2','Hunyuan3D 2.0','TripoSR'], pt:pk.params});
  if(g.has('texture'))
    stages.push({title:'阶段 2b · PBR 贴图', tools:['ArmorPaint','Blender'], pt:'在模型表面绘制 PBR，检查 UV 与法线。'});
  if(g.has('cad'))
    stages.push({title:'阶段 2c · 参数化零件', tools:['FreeCAD','OpenSCAD','CadQuery'], pt:'参数化建模后导出 STL 与角色网格合体。'});
  if(g.has('print'))
    stages.push({title:'阶段 3 · 修模与切片', tools:['Blender','MeshLab','trimesh','OrcaSlicer','UVtools'], pt:pk.params});
  if(g.has('vrm'))
    stages.push({title:'阶段 3b · VRM 导出与驱动', tools:['VRM Add-on for Blender','VSeeFace'], pt:'Blender 导出 VRM 1.0，网页验证后面捕驱动。'});
  if(g.has('pixel'))
    stages.push({title:'阶段 1b · 像素 / 动画', tools:['Aseprite','OpenToonz'], pt:pk.pos});
  $("execStages").innerHTML=stages.map(sg=>`
    <div class="stage"><h4 aria-level="3">${esc(sg.title)}</h4>
      <div class="tools">${sg.tools.map(n=>{
        const t=GROUPS.flatMap(g=>g.tools).find(x=>x.n===n);
        return `<span class="tag">${esc(n)}</span>${toolBtn(n)}`+(t?`<span style="flex-basis:100%;font-size:11px;color:var(--dim)">↳ ${esc((t.note||'').split('。')[0])}</span>`:'');
      }).join('')}</div>
      <div class="pt">${esc(sg.pt)}</div>
    </div>`).join('');
  bindToolBtns($("execStages"));
}

/* ---------------------------------------------------------------- 交互 */
let last=null;
function clip(text,okMsg){
  const done=()=>setStatus($("outStatus"),okMsg);
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(done).catch(()=>fallback(text,done));
  } else fallback(text,done);
}
function fallback(text,done){
  const ta=document.createElement("textarea");ta.value=text;ta.readOnly=true;  // 轮15：iOS 需 readOnly
  ta.style.position="fixed";ta.style.top="0";ta.style.left="0";
  ta.style.opacity="0";                       // 保持不可见但可focus（不用 display:none）
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  if(ta.setSelectionRange){try{ta.setSelectionRange(0,text.length);}catch(e){}}
  let ok=false;
  try{ ok=document.execCommand("copy"); }catch(e){ ok=false; }
  document.body.removeChild(ta);
  if(ok) done();
  else setStatus($("outStatus"),"复制失败，请手动选中上面的文本复制。",true);
}
function download(){
  if(!last)return;
  // 轮14：BOM 让旧版 Windows 记事本正确识别 UTF-8（新版也能正常显示 BOM）
  const blob=new Blob(["\uFEFF",last.text],{type:"text/markdown;charset=utf-8"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);
  a.download=safeName(last.name)+".md";document.body.appendChild(a);a.click();
  setTimeout(()=>{URL.revokeObjectURL(a.href);a.remove();},500);
  setStatus($("outStatus"),`已导出 ${a.download}`);
}

$("gen").addEventListener("click",()=>{
  const p=profile();
  if(!selectedWf.size){setStatus($("status"),"请先在上方选一条工作流（可多选）。",true);return;}
  if(!p.proj&&!p.subject){setStatus($("status"),"请在「项目参数」里至少填写项目名称或角色主体。",true);
    $("paramsFold").open=true;return;}
  const pkg=buildPackage(p);
  const jobSpec=buildJobSpec(p);   // 自动化引擎：编译机器可读作业单
  last={text:pkg.text,prompt:pkg.prompt,name:p.proj||p.subject||"创作任务包",p:p,jobSpec:jobSpec};
  $("output").textContent=pkg.text;
  renderExec(p);
  // 自动化引擎：展示一键执行面板
  $("autoPanel").style.display='block';
  $("autoRun").disabled=false;
  $("autoMeta").textContent=`${jobSpec.steps_total} 步 · 可自动 ${jobSpec.auto_count} 步 · 需人工 ${jobSpec.steps_total-jobSpec.auto_count} 步`;
  // 轮7：print 初始 disabled，历史载入路径启用了 5 个按钮，这里也必须一致，否则新生成的包无法打印
  ["copy","copyPrompt","download","save","print"].forEach(id=>$(id).disabled=false);
  markClean();
  setStatus($("status"),`已生成：${p.workflows.length} 条工作流、${p.goals.length} 个目标、${GROUPS.reduce((n,g)=>n+g.tools.length,0)} 个工具纳入索引。`);
  // 生成后明确指路执行台——用户反馈"生成后找不到地方执行"
  setStatus($("outStatus"),"任务包已就绪：可复制 / 导出 / 保存；想直接开工请往下滚到「③ 执行台」，那里已按阶段列好工具与提示词。");
});
function resetOutput(){
  last=null;
  $("output").textContent="尚未生成。选一条工作流，填好参数后点「生成创作任务包」，这里会出现一份可复制、可导出的 Markdown 任务包。";
  ["copy","copyPrompt","download","save","print"].forEach(id=>$(id).disabled=true);
  renderExec(null);
  if($("dirtyNote"))$("dirtyNote").style.display='none';
  if($("autoPanel"))$("autoPanel").style.display='none';   // 自动化引擎
  if(_autoTimer){clearInterval(_autoTimer);_autoTimer=null;}
}
$("clear").addEventListener("click",()=>{
  ["proj","subject","extra"].forEach(id=>$(id).value="");
  $("style").selectedIndex=0;$("vram").value="12";$("usage").selectedIndex=0;$("comm").selectedIndex=0;
  selectedWf.clear(); renderWfSelect(); renderBranches(); resetOutput();
  setStatus($("status"),"表单、工作流与产出已清空。");
  setStatus($("outStatus"),"");
});
$("copy").addEventListener("click",()=>last&&clip(last.text,"任务包已复制到剪贴板。"));
$("copyPrompt").addEventListener("click",()=>last&&clip(last.prompt,"提示词包已复制到剪贴板。"));
$("download").addEventListener("click",download);
$("save").addEventListener("click",()=>{
  if(!last)return;
  const a=getHist();
  const sig=profileSig(profile());
  // 轮12：同源去重——内容签名相同则只更新时间，不新增记录
  const dupIdx=a.findIndex(h=>h.sig===sig);
  if(dupIdx>=0){
    a[dupIdx].time=stamp();
    const [dup]=a.splice(dupIdx,1); a.unshift(dup);
    if(!setHist(a)){setStatus($("outStatus"),"本地存储不可用，请改用「导出 .md」。",true);return;}
    renderHist();setStatus($("outStatus"),"内容与最近一条相同，已更新时间。");return;
  }
  const before=a.length;
  a.unshift({time:stamp(),name:last.name,text:last.text,prompt:last.prompt,sig,
    p:last.p||null,goals:last.p?last.p.goals:[],style:last.p?last.p.style:"",
    jobSpec:last.jobSpec||null});   // 轮19：保存作业单，载入后一键执行不失效
  const dropped=Math.max(0,before+1-20);
  if(!setHist(a)){setStatus($("outStatus"),"本地存储不可用（隐私模式？），请改用「导出 .md」。",true);return;}
  renderHist();setStatus($("outStatus"),"已保存到本地留存。"+(dropped?"（最旧 "+dropped+" 条已被覆盖）":""));
});
$("print").addEventListener("click",()=>window.print());
// 轮7：debounce，避免中文输入法逐字触发全量 DOM 重建
let _searchTimer=null;
$("q").addEventListener("input",e=>{
  const v=e.target.value;
  clearTimeout(_searchTimer);
  _searchTimer=setTimeout(()=>renderTools(v),150);
});

// 轮3/20：初始化逐项隔离 + async 兜底，任一处异常不拖垮全局
[buildGoals,renderWfSelect,renderBranches,renderHist].forEach(fn=>{
  try{fn();}catch(e){console.error('[atlas init]',fn.name,e);}
});
detectBridge().catch(e=>console.error('[atlas bridge init]',e));
// 轮4：任何需求字段变化都触发脏检测
["proj","subject","style","vram","usage","comm","extra"].forEach(id=>{
  $(id).addEventListener("input",checkDirty); $(id).addEventListener("change",checkDirty);
});
$("bridgeRefresh").onclick=detectBridge;
$("bridgeStart").onclick=()=>{
  setStatus($("outStatus"),'请在文件夹里双击「快捷方式工具/start-tool-bridge.ps1」选择用 PowerShell 运行，然后回来点刷新。');
};

/* ---------------------------------------------------------------- 自动化引擎：一键执行 + 进度轮询 */
let _autoJobId=null, _autoTimer=null;
function autoRender(job){
  const pct=job.progress||0;
  $("autoBar").style.width=pct+'%';
  $("autoCurrent").textContent=(job.current||'') + (job.status==='paused'?' ⏸ 需人工接手':'');
  const st={pending:'○',running:'◐',done:'●',error:'✕',needs_human:'⏸'};
  $("autoSteps").innerHTML=(job.steps||[]).map(s=>
    `<div style="margin:2px 0">${st[s.status]||'○'} ${esc(s.label)}`+
    (s.detail?` <span style="color:var(--dim)">— ${esc(s.detail)}</span>`:'')+`</div>`).join('');
  const running=['queued','running'].includes(job.status);
  $("autoRun").style.display=running?'none':'inline-block';
  $("autoStop").style.display=running?'inline-block':'none';
  if(['done','failed','paused','stopped'].includes(job.status)){
    if(_autoTimer){clearInterval(_autoTimer);_autoTimer=null;}
    setStatus($("outStatus"),
      job.status==='done'?'✅ 自动化执行完成，产物已保存到 outputs/ 目录。':
      job.status==='paused'?'⏸ 引擎已在人工环节暂停，前置产物已备好，请接手继续。':
      job.status==='failed'?'❌ 执行失败：'+esc(job.current||'')+'（详见步骤详情）':
      '已停止。');
  }
}
async function autoPoll(){
  if(!_autoJobId) return;
  try{
    const r=await timeoutFetch(BRIDGE+'/api/job/'+encodeURIComponent(_autoJobId),{},5000);
    const d=await r.json();
    if(d.ok && d.job) autoRender(d.job);
  }catch(e){ /* 轮询容错：下次再试 */ }
}
$("autoRun").onclick=async()=>{
  if(!bridgeOn||!bridgeToken){setStatus($("outStatus"),'请先启动工具桥并刷新状态，再执行自动化。',true);return;}
  if(!last||!last.jobSpec){setStatus($("outStatus"),'请先生成任务包。',true);return;}
  setStatus($("outStatus"),'正在提交自动化作业…');
  try{
    const r=await timeoutFetch(BRIDGE+'/api/job/create',{
      method:'POST',headers:{'Content-Type':'application/json','X-Bridge-Token':bridgeToken},
      body:JSON.stringify(last.jobSpec)
    },10000);
    const d=await r.json();
    if(!d.ok||!d.job_id){setStatus($("outStatus"),'提交失败：'+esc(d.error||'未知错误'),true);return;}
    _autoJobId=d.job_id;
    $("autoProgress").style.display='block';
    $("autoRun").style.display='none';$("autoStop").style.display='inline-block';
    setStatus($("outStatus"),'自动化作业已提交，正在执行…');
    if(_autoTimer)clearInterval(_autoTimer);
    _autoTimer=setInterval(autoPoll,1200);
    autoPoll();
  }catch(e){setStatus($("outStatus"),'提交失败：'+(e&&e.message||String(e)),true);}
};
$("autoStop").onclick=async()=>{
  if(!bridgeToken)return;
  try{
    await timeoutFetch(BRIDGE+'/api/job/stop',{
      method:'POST',headers:{'Content-Type':'application/json','X-Bridge-Token':bridgeToken},body:'{}'
    },5000);
    setStatus($("outStatus"),'已请求停止。');
  }catch(e){setStatus($("outStatus"),'停止请求失败：'+(e&&e.message||String(e)),true);}
};
