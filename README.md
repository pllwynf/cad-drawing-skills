# CAD 建筑设计出图技能集

一套面向**建筑设计出图**的 AI 技能包（Skill Pack），覆盖从「拿到一张纸/一张照片」到「输出可编辑 DWG/DXF」的完整链路：DWG 批量解析、扫描图矢量化、图片重绘、天正建筑参数化出图、图像批量无损放大、AI 效果图生成。

所有技能均按 `SKILL.md`（带 YAML frontmatter）组织，可被支持 Skill 机制的 AI 助手直接加载。

---

## 技能清单

| 技能 | 目录 | 解决什么问题 |
|---|---|---|
| **DWG 自动化处理** | `skills/dwg-autocad-auto` | 用 `accoreconsole.exe` 免开 GUI 批量处理 DWG：提取文字/属性/图层/统计，把 DWG 渲染成 PNG 让多模态模型「真的看见」图纸，批量导出 DXF/PDF，运行 AutoLISP 脚本 |
| **图片重绘为 CAD** | `skills/autocad-image-redraw` | 把截图、扫描件、照片、手绘图重建成**可编辑**的 DWG/DXF。核心是「证据分级」：每个尺寸都标注 `known / scaled / inferred / unreadable`，绝不靠像素相似度冒充尺寸准确 |
| **天正建筑出图** | `skills/tarch-plan-drafting` | 驱动 T20 天正建筑（V9.0 + AutoCAD 2022）纯原生命令出图：轴网→柱→墙→门窗→楼梯→三道尺寸→符号图框，含立剖面生成与 MCP 自动投递 |
| **扫描图矢量化** | `skills/scan-to-dwg` | 纸质扫描图纸（PDF/图片）自动分层重绘为 DXF/DWG：图像预处理 → 连通分量分析 → 按轴线/墙体/门窗/标注/文字分离图层 → 可选 OCR |
| **批量无损放大** | `skills/batch-image-upscale` | 效果图批量放大到指定长边。Lanczos 高质量插值（快）或 ONNX 超分模型 Real-ESRGAN/EDSR（AI 增强），自动保留 Alpha 通道、大图分块推理 |
| **AI 效果图生成** | `skills/nano-banana-pro` | 调用 Nano Banana Pro（Gemini 3 Pro Image）做文生图与图生图，支持 1K/2K/4K，用于方案效果图与改图 |

---

## 安装

把需要的技能目录整体复制到助手的技能目录即可，一行一个：

```bash
# 全量安装
cp -r skills/* ~/.workbuddy/skills/

# 或只装某个
cp -r skills/tarch-plan-drafting ~/.workbuddy/skills/
```

> 若使用其他支持 Skill 机制的工具，把它们放进对应的 skills 目录同样可用，结构是通用的 `SKILL.md + references/ + scripts/`。

安装后重启会话，技能即被识别。

---

## 环境依赖

### 外部程序

| 依赖 | 用途 | 说明 |
|---|---|---|
| AutoCAD 2022 + `accoreconsole.exe` | `dwg-autocad-auto` | 核心控制台引擎，无需启动 GUI 即可跑批 |
| T20 天正建筑 V9.0（模块目录 `sys24x64`） | `tarch-plan-drafting` | 常驻在 AutoCAD 2022 内 |
| easy-autocad MCP 服务 | `tarch-plan-drafting` | 提供 `execute_command` / `execute_pick` / `count_entity_types` / `capture_window` |
| ODA File Converter | `scan-to-dwg` | 可选，DXF → DWG 转换 |

> 各技能 `SKILL.md` 的 frontmatter 里写了本机实际路径，换机器时改 `metadata.requires.bins` 即可。

### Python 包

```bash
pip install pillow opencv-python numpy ezdxf pymupdf requests
```

`batch-image-upscale` 走超分模型时另需 `onnxruntime`，脚本内附模型下载器。

---

## 典型用法

**1. 业主只给了一份纸质扫描图，要做改造设计**

```
scan-to-dwg      扫描件 PDF → 分层 DXF（轴线/墙体/门窗/文字各自成层）
      ↓
autocad-image-redraw   补全尺寸、纠正偏差，输出可编辑 DWG
```

**2. 已有 DWG，要交给 AI 做施工图审查**

```
dwg-autocad-auto  批量提取文字/图层/统计 → 渲染成 PNG → 多模态模型读图
```

**3. 从零出一套平面图**

```
tarch-plan-drafting   轴网 → 柱 → 墙 → 门窗 → 楼梯 → 三道尺寸 → 图框
```

**4. 方案汇报用的效果图**

```
nano-banana-pro       生成/改图 → batch-image-upscale 放大到 2560px 长边
```

---

## 目录结构

```
cad-drawing-skills/
├── README.md
└── skills/
    ├── dwg-autocad-auto/
    │   └── SKILL.md                  # 命令参考 + AutoLISP 脚本模板
    ├── autocad-image-redraw/
    │   ├── SKILL.md
    │   ├── references/               # 规格说明、校验规则、最小示例
    │   └── scripts/                  # 预检 / 校验 / 绘制 / 渲染 / 比对
    ├── tarch-plan-drafting/
    │   ├── SKILL.md
    │   └── references/               # 01 命令总表 … 10 标高与对话框
    ├── scan-to-dwg/
    │   ├── SKILL.md
    │   ├── scripts/run.py            # 管线入口
    │   └── scan2dwg/                 # 预处理/分类/矢量化/写 DXF/OCR
    ├── batch-image-upscale/
    │   ├── SKILL.md
    │   └── scripts/
    └── nano-banana-pro/
        ├── SKILL.md
        └── scripts/
```

---

## 设计取舍

- **尺寸可信度优先于像不像。** `autocad-image-redraw` 强制对每个关键尺寸标注来源等级，宁可承认「不可读」，也不让缩放得到的数值伪装成实测值。
- **能不开 GUI 就不开。** DWG 批处理全部走 `accoreconsole`，一张图一条命令，适合成百上千个文件的批量场景。
- **图纸是证据，不是真相。** 扫描件重绘以可核验为准：先分层、再对位、最后补尺寸，而不是一次性黑箱输出。

---

## 许可

本仓库内容供学习与内部使用。涉及具体项目图纸、业主资料的示例文件均未包含在内（已剔除）。
