---
name: dwg-autocad-auto
description: "AutoCAD DWG auto-processing via accoreconsole. Extract text/attributes/layers/stats from DWG; render DWG to PNG so a multimodal AI can actually SEE the drawing; batch export to DXF/PDF; run AutoLISP scripts. For 施工图审查 (construction drawing review) DWG file analysis."
description_zh: "AutoCAD DWG 自动处理：通过 accoreconsole 提取文字/属性/图层/统计，将 DWG 渲染为 PNG 供多模态 AI「看图」，批量导出 DXF/PDF，运行 AutoLISP 脚本"
version: 1.1.0
homepage: ""
allowed-tools: Read,Write,Bash,Glob
metadata:
  agent_created: true
  emoji: "📐"
  requires:
    bins:
      - "D:\\工作安装软件\\cad\\AutoCAD 2022\\accoreconsole.exe"
    features:
      - 备选：浩辰CAD看图王（GUI-only，自动化不可用）
---

# AutoCAD DWG 自动处理

通过 AutoCAD 2022 的 **accoreconsole.exe**（核心控制台引擎，无需GUI）对 DWG 文件进行自动化处理。

## 环境信息

| 项目 | 值 |
|------|-----|
| accoreconsole 路径 | `D:\工作安装软件\cad\AutoCAD 2022\accoreconsole.exe` |
| 版本 | S.51.0.0 (AutoCAD 2022) |
| 用途 | 施工图AI自动审查 - DWG图元提取与分析 |

## 基本调用格式

```powershell
$cc = "D:\工作安装软件\cad\AutoCAD 2022\accoreconsole.exe"
$dwg = "path/to/drawing.dwg"
$scr = "path/to/script.scr"
$result = & $cc /i $dwg /s $scr /l "en-US" 2>&1
```

参数说明：
- `/i <dwg>` — 输入DWG文件
- `/s <script>` — AutoLISP脚本文件 (.scr)
- `/l <lang>` — 语言 (en-US 或 zh-CN)
- `/product <prod>` — 产品 (默认 AutoCAD)
- `/isolate <userid> <folder>` — 隔离模式（需要两个子参数）
- `/readonly` — 只读模式

## AutoLISP 脚本模板

### 1. 提取全部文字标注 (TEXT/MTEXT)

```lisp
(setvar "FILEDIA" 0)
(setvar "CMDECHO" 0)
;; 选择所有文字
(setq ss (ssget "_X" '((0 . "TEXT,MTEXT"))))
(setq i 0)
(princ (strcat "TEXT_COUNT:" (itoa (sslength ss))))
(while (< i (sslength ss))
  (setq ent (ssname ss i))
  (setq ed (entget ent))
  (setq txt (cdr (assoc 1 ed)))
  (setq lay (cdr (assoc 8 ed)))
  (setq pt (cdr (assoc 10 ed)))
  (princ (strcat "LAYER:" lay "|TEXT:" txt "|POS:" (vl-princ-to-string pt)))
  (setq i (1+ i))
)
(princ "===DONE===")
```

### 2. 导出图层列表

```lisp
(setvar "CMDECHO" 0)
(princ "===LAYERS===")
(setq lay (tblnext "LAYER" T))
(while lay
  (princ (strcat (cdr (assoc 2 lay)) "|COLOR:" (itoa (cdr (assoc 62 lay))) "|LTYPE:" (cdr (assoc 6 lay))))
  (setq lay (tblnext "LAYER"))
)
(princ "===DONE===")
```

### 3. 图元分类统计

```lisp
(setvar "CMDECHO" 0)
(princ "===ENTITY_STATS===")
(foreach etype '("LINE" "LWPOLYLINE" "CIRCLE" "ARC" "TEXT" "MTEXT" "INSERT" "DIMENSION" "HATCH" "LEADER" "MLEADER" "ATTDEF" "ATTRIB")
  (setq ss (ssget "_X" (list (cons 0 etype))))
  (if ss
    (princ (strcat etype ":" (itoa (sslength ss)) "|"))
    (princ (strcat etype ":0|"))
  )
)
(princ "===DONE===")
```

### 4. 导出为DXF（用于Python ezdxf进一步分析）

```lisp
(setvar "FILEDIA" 0)
(setvar "CMDECHO" 0)
(command "._DXFOUT" "C:\\Users\\<用户名>\\WorkBuddy\\2026-05-19-task-5\\_export.dxf" "_V" "2018" "")
(princ "===DXF_EXPORTED===")
```

### 5. 提取块(BLOCK)及其属性

```lisp
(setvar "CMDECHO" 0)
(princ "===BLOCKS===")
(setq bl (tblnext "BLOCK" T))
(while bl
  (setq bname (cdr (assoc 2 bl)))
  (if (= (logand (cdr (assoc 70 bl)) 4) 0) ;; 非外部参照
    (progn
      ;; 统计该块的插入次数
      (setq ss (ssget "_X" (list (cons 0 "INSERT") (cons 2 bname))))
      (if ss
        (princ (strcat bname ":" (itoa (sslength ss)) "|"))
      )
    )
  )
  (setq bl (tblnext "BLOCK"))
)
(princ "===DONE===")
```

## 辅助 Python 脚本 (DXF分析)

```python
import ezdxf
doc = ezdxf.readfile("_export.dxf")
msp = doc.modelspace()

# 提取所有文字
for entity in msp.query('TEXT MTEXT'):
    text = entity.dxf.text if entity.dxftype() == 'TEXT' else entity.text
    layer = entity.dxf.layer
    print(f"LAYER:{layer}|TEXT:{text}")

# 提取所有尺寸标注
for dim in msp.query('DIMENSION'):
    print(f"TYPE:{dim.dxftype()}|MEAS:{dim.dxf.dimmeasurement}|LAYER:{dim.dxf.layer}")
```

## 让 AI「看懂图纸」的核心流程（v1.1 新增，已实测）

> ⚠️ **关键认知**：LLM 无法直接读 DWG。所谓「让电脑看懂图纸」= 两条腿走路：
> **矢量层（精确）** + **视觉层（直观）**。两者必须配合，缺一不可。

### 路线 A — 矢量层：精确读取图元数据（用于算量/审查/统计）

accoreconsole + AutoLISP，见上文模板。输出文字、图层、图元计数、块属性。
**这是最可靠的"读懂"，因为它读的是设计意图本身，不是像素。**

### 路线 B — 视觉层：渲染成图片，让多模态 AI 直接「看」

这是"翻图"和"看出问题"的关键。**实测可用流程**：

```bash
# 1) DWG -> DXF（accoreconsole，稳定可靠）
cat > dxf.scr <<'EOF'
(setvar "FILEDIA" 0)
(setvar "CMDECHO" 0)
(command "._DXFOUT" "C:/out/plan.dxf" "_V" "2018" "16")
(princ "===DXF_DONE===")
EOF
"D:/工作安装软件/cad/AutoCAD 2022/accoreconsole.exe" /i "图.dwg" /s dxf.scr /l en-US

# 2) DXF -> PNG（Python venv，见下）
"<venv>/python.exe" render_dxf.py plan.dxf plan_preview.png 2600

# 3) 用 Read 工具直接打开 PNG —— AI 即可「看到」图纸
```

依赖安装在托管 venv 中（已就绪）：
`C:\Users\<用户名>\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
已装 `ezdxf 1.4.4` + `matplotlib 3.11.1`。渲染脚本：`mcp-eval/probe/render_dxf.py`。

渲染器核心（ezdxf addons.drawing + matplotlib Agg 后端）：

```python
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt, ezdxf
from ezdxf.addons.drawing import RenderContext, Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

doc = ezdxf.readfile("plan.dxf"); msp = doc.modelspace()
fig = plt.figure(figsize=(2600/200, 2600/200), dpi=200)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor("white"); ax.set_axis_off()
Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(msp, finalize=True)
fig.savefig("plan_preview.png", dpi=200, facecolor="white", bbox_inches="tight")
```

**实测结果（2026-09-13）**
| 图纸 | 结果 |
|------|------|
| `kuang.dwg`（矿山地形图，桌面） | 1567 条文字、7103 条多段线、738 个填充、28 个图层；渲染后 AI 可辨识等高线 / 采矿权红线 / SZK 钻孔点 |
| `02平面图_t8_t3.dwg`（建筑平面图，桌面） | DXF 19.8MB，渲染后 AI 可辨识各层平面、柱网轴网、总平面 |

### ⛔ 实测踩坑记录

1. **`-PLOT` 命令在 accoreconsole 中会挂死**（提示序列不匹配，进程卡住直到超时）。
   **不要**用 `(command "_.-PLOT" ...)` 出 PDF。改用「DXFOUT + ezdxf 渲染」或 `-EXPORT`。
2. **`mcp` 包 2.x 破坏兼容**：`FastMCP` 已改名 `MCPServer`。任何基于 `mcp.server.fastmcp`
   的第三方代码必须钉 `mcp>=1.2.0,<2`，否则 `ModuleNotFoundError`。
3. pip 直连 pypi.org 在本机超时严重，务必加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`。
4. 大图纸渲染耗时：19.8MB DXF 约 1-2 分钟，建议后台执行。
5. `git clone` 大仓库在本机极慢（>7min 无响应），改用 GitHub Contents API + base64 取单文件更快。

## 已知限制

1. **中文乱码问题**：accoreconsole在控制台输出中文时会出现编码问题（文件名、图层名中的中文）。解决方案：
   - 将输出写入文件：`(setq f (open "output.txt" "w")) (princ data f) (close f)`
   - 或使用英文替代图层名
2. **执行时间**：加载DWG + 运行脚本约 10-60 秒（取决于图元数量）
3. **授权依赖**：需要AutoCAD 2022有效授权（当前用户的机器已验证可用）
4. **DWG版本**：支持R14 ~ 2022格式

## 备选方案

| 方案 | 状态 | 说明 |
|------|------|------|
| accoreconsole + LISP | ✅ 主方案 | 功能最强，图元级访问，无需打开 GUI |
| DXF + ezdxf 渲染 PNG | ✅ 看图方案 | 让多模态 AI 真正"看见"图纸，见上文路线 B |
| Easy-MCP-AutoCad（MCP） | ⚠️ 可选 | 需 GUI AutoCAD 常驻 + COM；仅适合「边看边改」，读取能力弱于主方案。见下方说明 |
| Python ezdxf | 备选 | 仅支持DXF，需先DWG→DXF转换 |
| 浩辰CAD看图王 | ❌ 不适用 | GUI-only，无命令行接口 |

### Easy-MCP-AutoCad 安装要点（2026-09-13 实测）

仓库 `zh19980811/Easy-MCP-AutoCad`（作者已声明**不再积极维护**）。已在本机装好：

| 项目 | 值 |
|------|-----|
| 服务目录 | `C:\Users\<用户名>\mcp-servers\Easy-MCP-AutoCad\` |
| venv | `.venv\Scripts\python.exe` |
| MCP 配置 | `C:\Users\<用户名>\.workbuddy\mcp.json`（server 名 `easy-autocad`） |
| 工具数 | 19 |

**必须做的两处源码修复**（原仓库开箱即崩）：
1. `server.py` 中 `draw_line` 有**两个 `@mcp.tool()` 装饰器**（中间夹空行），
   FastMCP 会报 `Tool already exists` 并丢弃第二个定义 —— 删掉多余那个。
2. 全文 36 处 `win32com.client.pythoncom` 是**错误引用**（该属性不存在），
   须改为模块级 `pythoncom` 并补 `import pythoncom`。
3. 依赖必须钉 `mcp>=1.2.0,<2`（mcp 2.x 已把 FastMCP 改名 MCPServer）。

**本质局限**：它全部走 `win32com.client.Dispatch("AutoCAD.Application")`，
**要求 AutoCAD 开着 GUI 并打开图纸**，不是 headless。且工具以「画图/改图」为主
（draw_line/circle/polyline/text、move/rotate/copy entity），读取侧只有
`scan_all_entities`（图元入 SQLite）+ `execute_query`（SQL 查询）。
**它不能让 AI 看懂图纸**，只能让 AI 往图纸里写东西。


## 实际测试验证

- 文件：司机之家建筑施工图20260507_t8_t3.dwg (1.68MB)
- 结果：成功加载17,650个图元，100+图层，执行AutoLISP脚本完全正常
- 日期：2026-05-21
