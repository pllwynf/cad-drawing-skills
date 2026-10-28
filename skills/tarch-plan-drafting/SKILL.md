---
name: tarch-plan-drafting
description: "Draft architectural drawings with T20 天正建筑 (V9.0 on AutoCAD 2022) using native 天正 commands only — axis grids, columns, walls, doors/windows, stairs, dimensions, symbols, plus elevation/section generation and title-block layout. Use when asked to 用天正画图/画平面图/按图纸重绘/生成施工图/加轴号/标三道尺寸, or to drive 天正 through the easy-autocad MCP bridge."
description_zh: "天正建筑(T20 V9.0)出图：轴网→柱→墙→门窗→楼梯→三道尺寸→符号图框，纯天正命令，含立剖面生成、图框布局与 MCP 自动投递/点选"
version: 1.0.0
metadata:
  agent_created: true
  emoji: "📐"
  requires:
    bins:
      - "D:\\工作安装软件\\cad\\AutoCAD 2022\\acad.exe"
    features:
      - "T20 天正建筑 V9.0 常驻在 AutoCAD 2022（模块目录 sys24x64）"
      - "MCP 服务 easy-autocad（execute_command / execute_pick / count_entity_types / capture_window）"
---

# 天正建筑出图（T20 V9.0）

用**天正自己的命令**画建筑图，不是用 AutoCAD 图元"拼"出建筑图。所有成果必须是天正智能对象
（`TDbWall` / `TDbColumn` / `TDbOpening` / `TDbRectStair` / `TDbDimension2` / `TDbAxisLabelSet`），
这样墙体转角自动清理、门窗自动开洞、尺寸与门窗联动、门窗表能统计。

## 四条底线

1. **不许用 LINE/PLINE/RECTANG 冒充墙**。墙必须用 `HZQT`（TGWall），柱用 `BZZ`（TGColumn），
   门窗用 `MC`（TOpening）。用原生图元画出来的东西，天正一律不认。
   标高同理：必须 `BGBZ` 生成 `TDbSymbElevation`，不许手画倒三角加 TEXT。
2. **顺序不能反**：轴网 → 柱 → 墙 → 门窗 → 楼梯 → 尺寸 → 符号。门窗外于墙、墙外于轴网，
   倒过来做会不断返工。
3. **交付前用 `count_entity_types` 对数**。画完不数，等于没画。
4. **不许把用户既有图纸的对象直接搬过来充当"重绘成果"**。
   跨文档 `CopyObjects` 在技术上是可行的（天正墙与门窗依附关系能保住），但那是**搬运，不是绘制**——
   任务目的是练习/验证出图能力，搬过来等于交白卷。只读导出来取尺寸、取门窗表、取标高，
   然后**用命令一步步重画**。
   唯一允许复制的情形：复制**本次自己刚画的**上一层去做标准层，且必须逐层核对 1/7 轴等外墙环完整性。

## 环境

| 项目 | 值 |
|---|---|
| CAD | AutoCAD 2022 `D:\工作安装软件\cad\AutoCAD 2022\acad.exe`（经 TGStart.exe 带天正启动） |
| 天正 | T20 天正建筑 V9.0，模块 `D:\工作安装软件\cad\sys24x64`（R24，**不是** sys22x64） |
| 帮助原文 | `D:\工作安装软件\cad\SYS\TArch.chm`（可用 `hh.exe -decompile` 解包） |
| 命令源 | `sys24x64\tch.mns`（工具栏宏名）、`SYS\KeyMap.txt`（数字快捷键，GBK 编码） |
| 图层定义 | `SYS\LAYERDEF.DAT`（GBK） |
| 自动化 | MCP `easy-autocad`：`execute_command` / `execute_pick` / `count_entity_types` / `capture_window` / `zoom` |

**命令双轨制**：菜单和键盘用拼音别名（`HZQT`、`ZWBZ`、`BZZ`、`MC`、`SPLT`、`ZDBZ`），
工具栏宏用英文内部名（`TGWall`、`TMultAxisDim`、`TGColumn`、`TOpening`、`TRStair`、`TDimMP`）。
两套等价，任选其一。完整对照见 `references/01-命令总表.md`。

## 出图流程（七道工序）

### 0. 图纸体检（动手前必做）

- 单位：`INSUNITS` 应为 4（毫米）；`MEASUREMENT=1`；`LUNITS=2`。
- 比例：`DQBL`（当前比例）要与出图比例一致（1:100 就设 100），它控制文字高度、号圈大小、线型比例。
- 图幅：`LIMMAX` 与出图图幅匹配，或先 `CRTK` 插入图框再往里画。
- 已有内容：`count_entity_types` 看有没有 `TDb*` 对象；有的话先确认是否同一套图层体系。
- 天正图层标准：`TCGL`（图层管理）确认是"天正"标准还是"GBT18112-2000"中文标准，
  后续按层筛选对象全靠它。

### 1. 轴网（定位）

- 正规做法：`HZZW`（绘制轴网）→ 直线轴网 → 键入开间/进深（支持 `4*6000`、`7500` 这类写法）→ 点插入点。
- 单根补线：`DZHZ`（单轴绘制，可设出头长度）。
- 已有墙想反推轴网：`QSZW`（墙生轴网）。
- 轴号与第一二道尺寸：`ZWBZ`（轴网标注）→ 点起始轴 → 点终止轴 → 回车跳过"不需要标注的轴线"
  → 再回车退出。**轴号是 `ZWBZ` 生成的，不是画轴线时自动带的**（见"坑 1"）。
- 出图前用 `ZGXX`（轴改线型）把连续线切成点划线。

### 2. 柱

- `BZZ`（标准柱）：设截面/材料 → 三种布置方式任选：
  **点选插入**（优先吸轴线交点）、**沿一根轴线布置**、**矩形区域轴线交点布置**（一次布一片，批量必用）。
- 异形柱：闭合 Pline + `BZZ` 的"选择 Pline 创建异形柱"，或对已有柱右键"布尔运算"。
- 角柱 `JZ` / 构造柱 `GZZ` 是另外两个命令，别混用。

### 3. 墙体

- `HZQT`（TGWall）直墙连续画；命令行里输 `R` 是**矩形画墙**（对角两点成整圈），画房间最快。
- 对话框里必须先定：`左宽/右宽`（基线左右）、`墙高`、`底高`、`材料`、`用途`（内墙/外墙/分户/虚墙/卫生隔断/矮墙）。
- **基线思维**：墙基线是定位线，转角、连接、开洞全按基线算，两条墙的基线必须准接。
  左右宽可为负（基线在墙外），墙厚 240 一般给 120/120。
- 由轴网批量成墙：`DXBQ`（单线变墙）勾"轴线生墙"，框选轴网，外墙/内墙分两次给厚度。
  注意这是**选择对象型**命令，自动投递见"通道三"。
- 收尾：`SBNW`（识别内外）→ `GQH`（改墙厚）/`GGD`（改高度）批量修正 → `XQJ`（修墙角）处理复制镜像后的接头。

### 4. 门窗

- `MC`（TOpening）插入，9 种定位方式：自由 / 顺序 / 轴线等分 / 墙段等分 / 垛宽定距 / 轴线定距 /
  按角度（弧墙）/ 智能 / 满墙。**内门用垛宽定距或轴线定距**，外墙窗用轴线等分，连续窗用顺序插入。
- 参数：编号、宽、高、窗台高/门槛高。编号规则建议 `M`+宽高、`C`+宽高（如 `M1522`、`C1518`）。
- **门/窗类型属于创建时决定，事后无法用程序改**（见"坑 3"）。要在插入前选对类型，或事后用
  `MC` 对话框的"替换"功能批量换。
- 统计：`MCB`（门窗表）、`MCJC`（门窗检查，查同编号尺寸是否一致）。
- 特殊：`DXC` 带形窗、`ZJC` 转角窗、`TC` 凸窗、`YXD` 异形洞、`ZHMC` 组合门窗。

### 5. 楼梯与场地构件

- `SPLT`（双跑楼梯）：梯间宽 / 梯段宽 / 井宽 / 楼梯高度 / 踏步总数 / 踏步宽 / 休息平台 / 平台宽 /
  层类型（首层下剖断、中间层双剖断、顶层无剖断）。
- 其它：`ZXTD` 直线梯段、`YHTD` 圆弧梯段、`DPLT` 多跑、`DT` 电梯、`ZDFT` 自动扶梯。
- 台阶 `TJ`、坡道 `PD`、散水 `SS`、阳台 `YT`。

### 6. 尺寸（三道尺寸线）

| 道次 | 内容 | 命令 |
|---|---|---|
| 第一道 | 总尺寸 | `ZWBZ` 自动生成（轴网标注） |
| 第二道 | 轴线间距 | `ZWBZ` 自动生成 |
| 第三道 | 门窗定位 | `MCBZ`（门窗标注，与门窗宽度联动） |
| 补充 | 内墙门窗定位 | `NMBZ`（内门标注） |
| 补充 | 墙厚 | `QHBZ` |
| 补充 | 任意连续点 | `ZDBZ`（逐点标注） |
| 修整 | 外包齐边 | `WBCC`；合并总尺寸 `HBBZ` |

`ZDBZ` 的应答顺序是**三点式**：起点 → 第二点 → 尺寸线位置 → 其余标注点… → 空回车。
顺序错会把坐标当尺寸线位置，出一堆错尺寸。

### 7. 符号、文字、图框

- 标高 `BGBZ`（**唯一正确画法**，详见 `references/10-标高标注与对话框命令.md`）：
  不勾「手工输入」时**自动取光标 Y 坐标**出标高（mm→m，精度 0.000）；
  所以把图放在 Y=0 基准上，点取即得正确数值。多个楼层用「多层标高」一次算出。
  配套：`BGDQ` 对齐、`BGGZ` 改值、`BGJC` 检查。
- 剖切符号 `PQFH`、索引 `SYTM`/`ZXSY`、引出标注 `YCBZ`、图名 `TMBZ`、指北针 `HZBZ`。
  `TMBZ` 图名必须用它，别用 TEXT 拼。
- 文字用 `DHWZ`（单行）/ 多行文字；不要用 AutoCAD 的 `TEXT`（字高按天正比例走才统一）。
- 图框 `CRTK`（插入图框）：图幅、横立式、比例、图纸空间、会签栏；标题栏从图框库选。
- 房间与面积：`SSFJ`（搜索房间）、`CXMJ`（查询面积）、`MJTJ`（面积统计）。
- 立面 `JZLM`、剖面 `JZPM` 依赖 `GCGL`（工程管理）里已建好的楼层表；`GJLM`/`GJPM` 可对单个构件出立面/剖面。

## 自动投递：选哪条通道

天正命令按"要输入什么"分三类，投递方式完全不同：

| 类型 | 例子 | 投递方式 |
|---|---|---|
| 取点型 | `HZQT` TGWall、`MC` TOpening、`TDimMP` ZDBZ、`TSingleAxis` | `execute_command` 的 `mode="com"`，一次把所有点/参数按顺序塞进去，最稳 |
| 面板逐点型 | `BZZ` TGColumn 点选插柱 | `mode="kbd"` 键盘慢速逐点（面板要初始化时间），间隔 ≥1.1s |
| 选择对象型 | `ZWBZ` 轴网标注、`DXBQ` 单线变墙、`MCBZ` 门窗标注、`SBNW` 识别内外、`QSZW` 墙生轴网 | `execute_pick`（先标定像素↔世界坐标，再按模型坐标点选） |
| 对话框+点取型 | `BGBZ` 标高标注、`TMBZ` 图名、`PQFH` 剖切符号、`HZBZ` 指北针 | 键盘起命令 → **回车**确认默认 → 等提示 → 鼠标点取（见 `references/10`） |

`execute_pick` 用法要点：

1. 先 `calibrate` 标定（用 `ID` 命令回读三个像素点的世界坐标，解 sx/sy/基准点，存 `pick_calib.json`）。
   标定残差 `err_px` 应为 0~2 px；视图一平移/缩放，指纹变了就得重标。
2. 起命令 → 等提示 → 点 → 回车收尾。**必须先等提示出现再点**：天正命令常常
   "起命令 → 内部先跑 `Grids` 等子命令 → 才出真提示"，抢着点会被丢掉。
3. 收尾回车按 `CMDACTIVE` 判断次数，不要连发：空命令行下回车会**重复上一条命令**。

## 坑（都是实打实踩出来的）

1. **轴号不是天生的**。轴线只是 `DOTE` 层上的 LINE/ARC，天正不把它当对象；轴号与第一二道尺寸要靠
   `ZWBZ` 生成。`ZWBZ` 内部会先找"轴网"，普通 LINE 组成的假轴网它可能直接取消（日志里表现为
   `TMULTAXISDIM → Grids → TMultAxisDim → 请选择起始轴线:*取消*`）。稳妥做法：用 `HZZW` 建真轴网再标注。
2. **天正参数面板是非模态 `#32770`，会无限阻塞 COM**。症状是 `AttributeError: <unknown>.ModelSpace`。
   发 **ESC** 收面板即恢复。反过来，面板在的时候**别乱发 ESC**——它会把你正在等的命令一起取消。
3. **门窗的"门/窗类型"只读**。`IsHigh`/`ProStyle`/`DoorLine` 赋值不报错但回读不变（假成功）；
   要窗型必须在插入时选对类型，或事后用"门窗替换"。别读 `TDbOpening.BayThick`，会 `RPC_E_SERVERFAULT`，
   多次调用能把 acad.exe 弄崩。
4. **键盘焦点**：`SendInput` 依赖 AutoCAD 持有前台。被别的程序（QQ 游戏之类）抢焦时按键全丢，
   桥会报出抢占者。点一下绘图区空白处可把键盘焦点请回绘图区，但**点完别急着发 ESC**（见坑 2）。
5. **`sizeof(INPUT)` 在 x64 必须是 40 字节**，按 KEYBDINPUT 自然对齐算成 32 会让 `SendInput`
   静默失败、按键全丢。
6. **`SAVEAS` 走 SendCommand 会挂住**（FILEDIA=0 也一样）；用 COM `doc.SaveAs(path)`。
   图纸一建好就落盘，别等最后——曾因为 acad.exe 意外退出丢了整张演示图。
7. **天正对象属性可精确改**：`TDbWall.TotalWidth`、`TDbColumn.Width/Deep`、
   `TDbOpening.Width/Height/WinSill/Label`、`TDbRectStair.StepNum1/2`。
   移动用 `Move(VARIANT(VT_ARRAY|VT_R8,[x,y,0]), ...)`，传 tuple 会 `E_INVALIDARG`。
8. **`ZDBZ`/`TDimMP` 是三点式应答**（见工序 6），投递参数顺序错了不会报错，只会画错。
9. **一条 MC 插多樘窗 = 归属全毁**：每开一个洞重建一次墙段，先前窗全部游离（组码 330 变 0）。
   必须**一次只插一樘**，插完 MOVE 复位再插下一樘；窗厚只能删了重插（147 组码读写皆不可碰）。
10. **非天正图元（房间名/引线/台阶线/雨篷虚线）用 COM 直绘**最稳：`AddText`（样式
   `_TCH_DIM` 支持中文）+ `AddLine`；命令行发 TEXT/含中文 LISP 十有八九被取消。
   详见 `references/09-自动化投递手册.md` 第四通道与"门窗插入铁律"。
11. **标准层可以复用本次已画好的图纸**：复制**自己刚生成**的那张 DWG，保留轴网/轴号/尺寸/柱/楼梯/外墙，
    COM 批删 `TDbOpening` 与内墙后重画内墙门窗，效率高一个数量级。
    但**不许拿用户的源图当底稿**（见底线 4）。
12. **对话框型命令（BGBZ/TMBZ/PQFH/HZBZ/JTYZ…）必须用回车确认，不能用 WM_COMMAND 关窗**：
    `SendMessage(BM_CLICK)` 或 `PostMessage(WM_COMMAND, IDOK)` 会让对话框关掉但命令立刻 `*取消*`。
    正确姿势：`type_line(命令)` → 等 `panels()` 出 `#32770` → `press_vk(VK_RETURN)` → 再点取。
13. **天正对象的"移动/改长"：VLA Move 不行，`_.move` 命令行**。`TDbColumn`/`TDbWall` 调 `e.Move(...)`
   报 `<unknown>.Move`，但用 LISP 投 `(command "_.move" (handent "句柄") "" '(0,0,0) '(0,900,0))`
   一次即成（48 根柱批量移过，9/9 命中）。改长度（竖墙根部 2700→3600）**删重画更快**，
   重画后统一刷 `LeftWidth/RightWidth/Height`，天正会在交点自动断开（墙数变多属正常）。
14. **`TDbWall` 没有 `StartPoint/EndPoint`**（COM 读会抛异常）→ 用 `dump_walls.lsp` 导出基线再解析；
   墙的基线是唯一可靠的定位依据。
15. **SPLT 双跑楼梯面板：`WM_SETTEXT` 改不动内部状态**（回读是新值，生成的仍是默认值）。
   面板非模态、开着也能直接点插入点；但面板开着 COM 全废。可写的只有 `SpaceWidth`(梯间宽)、
   `StepWidth/StepHeight/StairHeight/StepNum1/2/StepTotalNum`；`StairWidth` 只读、平台二宽度无属性。
   想精确建梯：先在面板里**真键击**输入（焦点必须逐个点准），或建后 COM 改尺寸 + `_.move` 就位。
16. **标定前必须 ZoomExtents**：`calibrate()` 的 `err_px=0` 只说明三个探针自洽，**不保证目标点在视口内**。
    视图没缩放时 `world_to_screen` 可能算出屏幕外像素（如 py=-9585），点击静默失效。
    每次标定后要逐点校验落点在视口 rect 内。

## 交付

- 主交付：`.dwg`（天正对象齐全，能被天正继续编辑）。用户默认**只要 DWG**。
- 自检：`count_entity_types` 输出 `TDbWall/TDbColumn/TDbOpening/TDbRectStair/TDbDimension2/TDbAxisLabelSet`
  计数，与图纸说明逐项对数；数字对不上就回去补，不要交。
- 需要过程留痕时才做分镜图（每工序一帧 + `capture_window`），本默认不产出。

## 参考

| 文件 | 内容 |
|---|---|
| `references/01-命令总表.md` | 全量命令：中文名 / 拼音 / 内部宏名 / 用途 |
| `references/02-轴网与轴号.md` | 轴网类型、绘制、标注、轴号规则、编辑 |
| `references/03-墙体与柱.md` | 墙体参数语义、编辑工具、柱的三种布置 |
| `references/04-门窗.md` | 九种插入方式、编号、联动、特殊门窗 |
| `references/05-尺寸标注.md` | 各标注命令交互、尺寸编辑 |
| `references/06-楼梯场地.md` | 楼梯参数、台阶坡道散水阳台、房间面积 |
| `references/07-立剖面与图框.md` | 建筑立面/剖面、构件立剖面、图框与工程管理 |
| `references/08-图层与对象模型.md` | 图层标准全表、对象类型与可读写属性 |
| `references/09-自动化投递手册.md` | 三通道细节、标定算法、排错流程、脚本骨架 |
| `references/10-标高标注与对话框命令.md` | BGBZ 手册原文+实测、对话框控件 ID 表、回车/点取通道、三个坑 |
