#!/usr/bin/env python3
"""
辅助脚本: 下载 Real-ESRGAN ONNX 模型
支持的模型:
  - realesrgan-x4plus: 通用场景 4x 超分 (推荐)
  - realesrgan-x4plus-anime: 动漫/插画 4x 超分
  - realesrnet-x4plus: 去噪 + 4x 超分
"""

import sys
import urllib.request
import hashlib
from pathlib import Path

MODELS = {
    "realesrgan-x4plus": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
        "note": "通用场景 4x 超分辨率 (推荐)",
    },
    "realesrgan-x4plus-anime": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
        "note": "动漫/插画专用 4x 超分辨率",
    },
}

# 更轻量的 ONNX 模型源 (来自 onnx model zoo / community)
ONNX_MODELS = {
    "edsr-x2": {
        "url": "https://github.com/onnx/models/raw/main/Computer_Vision/edsr_super_resolution_opset18/edsr_super_resolution.onnx",
        "filename": "edsr_x2.onnx",
        "note": "EDSR 2x 超分 (ONNX官方, 通用场景)",
        "scale": 2,
    },
    "realesrgan-x4-ncnn": {
        "url": "https://github.com/Kazuhito00/Image-Processing-Node-Editor/raw/main/node/image_process/super_resolution/model/RealESRGANv3_x4.onnx",
        "filename": "RealESRGAN_x4.onnx",
        "note": "Real-ESRGAN 4x 超分 (ONNX格式)",
        "scale": 4,
    },
}


def download_with_progress(url: str, dest: Path):
    print(f"正在下载: {url}")
    print(f"保存至: {dest}")

    def reporthook(count, block_size, total_size):
        if total_size > 0:
            percent = min(count * block_size * 100 // total_size, 100)
            mb_done = count * block_size / 1024 / 1024
            mb_total = total_size / 1024 / 1024
            print(f"\r  [{percent:3d}%] {mb_done:.1f} / {mb_total:.1f} MB", end="", flush=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, dest, reporthook)
    print("\n下载完成!")


def main():
    print("=== Real-ESRGAN ONNX 模型下载工具 ===\n")
    print("可用模型:")
    for i, (key, info) in enumerate(ONNX_MODELS.items(), 1):
        print(f"  {i}. {key}: {info['note']} (倍率 {info['scale']}x)")

    print("\n选择模型 (输入序号, 默认1): ", end="")
    choice = input().strip() or "1"

    try:
        idx = int(choice) - 1
        model_key = list(ONNX_MODELS.keys())[idx]
        model_info = ONNX_MODELS[model_key]
    except (ValueError, IndexError):
        print("无效选择")
        sys.exit(1)

    save_dir = Path("models")
    dest = save_dir / model_info["filename"]

    if dest.exists():
        print(f"模型已存在: {dest}")
    else:
        try:
            download_with_progress(model_info["url"], dest)
        except Exception as e:
            print(f"\n下载失败: {e}")
            print("\n请手动下载模型:")
            print(f"  URL: {model_info['url']}")
            print(f"  保存到: {dest.resolve()}")
            sys.exit(1)

    print(f"\n✓ 模型准备就绪: {dest.resolve()}")
    print(f"\n使用命令:")
    print(f"  python batch_upscale.py --input <图片目录> --output <输出目录> --mode onnx --model-path {dest}")


if __name__ == "__main__":
    main()
