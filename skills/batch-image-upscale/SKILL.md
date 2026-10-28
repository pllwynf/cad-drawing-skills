---
name: batch-image-upscale
description: >
  批量无损放大图片技能。支持两种模式：
  1. Lanczos 高质量插值放大（无需额外模型，快速）
  2. ONNX 超分辨率模型放大（Real-ESRGAN / EDSR，AI 增强效果，需下载模型）
  支持 JPG/PNG/BMP/TIFF/WebP 格式，自动保留 Alpha 通道，大图自动分块推理。
version: 1.0.0
agent_created: true
triggers:
  - 批量放大图片
  - 无损放大
  - 图片超分辨率
  - 图片放大
  - upscale
  - 图像超分
allowed-tools:
  - Bash
  - PowerShell
  - Read
  - Write
---

# 批量无损放大图片技能

## 功能概述

| 模式 | 原理 | 速度 | 效果 | 适用场景 |
|------|------|------|------|----------|
| `lanczos` | Pillow 高质量插值 | ⚡ 极快 | 良好 | 快速批量处理、文字图片、图表 |
| `onnx` | AI 超分辨率模型 | 🐢 较慢 | 🌟 优秀 | 照片、插画、需要最高质量 |

---

## 环境要求

```bash
# 必须安装 (通常已有)
pip install Pillow numpy

# ONNX 模式额外需要
pip install onnxruntime        # CPU 推理
pip install onnxruntime-gpu    # GPU 推理 (CUDA, 可选)
```

**检查当前环境：**
```powershell
pip list | Select-String "Pillow|numpy|onnx"
```

---

## 脚本位置

```
~/.workbuddy/skills/batch-image-upscale/scripts/
  ├── batch_upscale.py    # 主批量放大脚本
  └── download_model.py   # ONNX 模型下载助手
```

---

## 快速使用

### 模式1：Lanczos 快速放大（推荐首选）

```bash
# 2x 放大 (默认)
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/原始图片 \
  --output D:/放大后图片

# 4x 放大
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/原始图片 \
  --output D:/放大后图片_4x \
  --scale 4

# 递归处理含子文件夹的目录
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/项目图片 \
  --output D:/项目图片_2x \
  --recursive
```

### 模式2：ONNX AI 超分辨率放大

#### 步骤1: 下载 ONNX 模型

```bash
# 运行下载助手 (在模型保存目录下执行)
cd D:/models
python ~/.workbuddy/skills/batch-image-upscale/scripts/download_model.py
```

或手动下载：
- **EDSR x2 (通用, 轻量)**: https://github.com/onnx/models/raw/main/Computer_Vision/edsr_super_resolution_opset18/edsr_super_resolution.onnx
- **Real-ESRGAN x4 (高质量)**: 从 https://github.com/xinntao/Real-ESRGAN/releases 下载 ONNX 版本

#### 步骤2: 运行超分辨率放大

```bash
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/原始图片 \
  --output D:/放大后图片_AI \
  --mode onnx \
  --model-path D:/models/edsr_x2.onnx
```

---

## 完整参数说明

```
必填参数:
  --input, -i     输入目录或单个图片文件路径
  --output, -o    输出目录路径

可选参数:
  --mode          放大模式: lanczos (默认) 或 onnx
  --scale         放大倍率: 2 (默认), 3, 4  [仅 lanczos 模式有效]
  --model-path    ONNX 模型文件路径         [onnx 模式必填]
  --tile          分块大小 (默认512)         [onnx 模式, 防止大图 OOM]
  --quality       JPEG 输出质量 1-100 (默认95)
  --format        强制输出格式: png / jpg / webp
  --recursive     递归处理子目录
  --overwrite     覆盖已存在的输出文件
```

---

## 典型用例

### 施工图扫描图片放大 (2x, 输出PNG无损)
```bash
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/施工图扫描 \
  --output D:/施工图扫描_2x \
  --scale 2 \
  --format png \
  --overwrite
```

### 照片批量 AI 超清放大
```bash
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/老照片 \
  --output D:/老照片_AI超清 \
  --mode onnx \
  --model-path D:/models/RealESRGAN_x4.onnx \
  --tile 256 \
  --quality 98
```

### 单张图片放大测试
```bash
python ~/.workbuddy/skills/batch-image-upscale/scripts/batch_upscale.py \
  --input D:/test.jpg \
  --output D:/output \
  --scale 2
```

---

## 支持的图片格式

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| JPEG | .jpg, .jpeg | 有损格式，建议输出质量 ≥ 90 |
| PNG | .png | 无损格式，推荐用于文字/图纸 |
| BMP | .bmp | 无损无压缩 |
| TIFF | .tif, .tiff | 工程/专业图像 |
| WebP | .webp | 现代格式，支持无损/有损 |

---

## 性能参考

| 图片分辨率 | Lanczos 2x | ONNX CPU | ONNX GPU (RTX) |
|-----------|-----------|----------|----------------|
| 1920×1080 | ~0.1s | ~3-8s | ~0.5s |
| 3840×2160 | ~0.3s | ~15-30s (分块) | ~2s |
| 500×500 | <0.05s | ~0.5s | ~0.2s |

---

## 常见问题

**Q: ONNX 模型推理结果很差 / 有噪点？**
A: 检查模型是否与当前 onnxruntime 版本兼容，尝试换用 `--tile 256` 减小分块大小。

**Q: 处理大图时内存不足 (OOM)？**  
A: 减小 `--tile` 参数，如 `--tile 256` 或 `--tile 128`。

**Q: 输出文件比原始文件大很多？**  
A: 正常现象，放大后分辨率更高。若用 PNG 输出可用 `--format jpg --quality 90` 控制文件大小。

**Q: 想保持原始文件格式不变？**  
A: 不加 `--format` 参数，脚本会自动保持原格式。

**Q: 如何只放大特定类型的图片？**  
A: 目前脚本处理目录内所有支持格式。可先将目标文件复制到单独目录再运行。

---

## 模型推荐

| 模型 | 倍率 | 大小 | 适用场景 | 下载 |
|------|------|------|----------|------|
| EDSR x2 | 2x | ~23MB | 通用照片 | ONNX Model Zoo |
| Real-ESRGAN x4plus | 4x | ~67MB | 通用照片/文档 | GitHub Releases |
| Real-ESRGAN x4plus-anime | 4x | ~67MB | 动漫/插画 | GitHub Releases |

---

## 执行流程 (供 AI 参考)

1. 确认用户的输入目录、输出目录、放大倍率
2. 检查环境依赖：`pip list | grep Pillow`
3. 若缺少依赖，执行安装命令
4. 根据用户需求选择模式：
   - 快速/文字/图纸 → lanczos
   - 照片/高质量 → onnx (先确认有模型文件)
5. 构建命令并执行
6. 报告处理结果（成功/跳过/失败数量）
