#!/usr/bin/env python3
"""
批量无损放大图片脚本
支持两种模式:
  1. Lanczos 高质量插值放大 (无需额外模型, 快速)
  2. ONNX 超分辨率模型放大 (Real-ESRGAN, 效果更佳, 需要下载模型)

用法:
  python batch_upscale.py --input <输入目录> --output <输出目录> [选项]

示例:
  python batch_upscale.py --input D:/photos --output D:/photos_4x --scale 4
  python batch_upscale.py --input D:/photos --output D:/photos_sr --mode onnx --model-path model.onnx
"""

import argparse
import sys
import os
import time
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print("[错误] 缺少依赖: pip install Pillow numpy")
    sys.exit(1)

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


# ─────────────────────────────────────────────
# 模式 1: Pillow Lanczos 高质量插值放大
# ─────────────────────────────────────────────
def upscale_lanczos(img: Image.Image, scale: int) -> Image.Image:
    new_w = img.width * scale
    new_h = img.height * scale
    return img.resize((new_w, new_h), Image.LANCZOS)


# ─────────────────────────────────────────────
# 模式 2: ONNX 超分辨率模型放大
# ─────────────────────────────────────────────
def load_onnx_session(model_path: str):
    try:
        import onnxruntime as ort
    except ImportError:
        print("[错误] 缺少 onnxruntime: pip install onnxruntime")
        sys.exit(1)

    providers = ort.get_available_providers()
    # 优先使用 GPU
    if "CUDAExecutionProvider" in providers:
        ep = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        print("[信息] 使用 GPU (CUDA) 加速推理")
    elif "DmlExecutionProvider" in providers:
        ep = ["DmlExecutionProvider", "CPUExecutionProvider"]
        print("[信息] 使用 DirectML GPU 加速推理")
    else:
        ep = ["CPUExecutionProvider"]
        print("[信息] 使用 CPU 推理 (GPU 不可用)")

    session = ort.InferenceSession(model_path, providers=ep)
    return session


def preprocess(img: Image.Image) -> np.ndarray:
    """PIL Image -> NCHW float32 [0,1]"""
    arr = np.array(img.convert("RGB")).astype(np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)[np.newaxis, ...]  # HWC -> NCHW
    return arr


def postprocess(output: np.ndarray) -> Image.Image:
    """NCHW float32 [0,1] -> PIL Image"""
    arr = output[0].transpose(1, 2, 0)          # NCHW -> HWC
    arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def upscale_onnx(img: Image.Image, session) -> Image.Image:
    inp_name = session.get_inputs()[0].name
    inp = preprocess(img)
    outputs = session.run(None, {inp_name: inp})
    return postprocess(outputs[0])


# ─────────────────────────────────────────────
# 分块处理 (避免大图 OOM)
# ─────────────────────────────────────────────
def upscale_onnx_tiled(img: Image.Image, session, tile_size: int = 512, overlap: int = 32) -> Image.Image:
    """
    将大图分块推理, 每块之间有 overlap 像素重叠以避免拼接缝隙。
    最终按比例拼合成完整超分图。
    """
    # 先获取模型放大倍率 (通过一个小 patch 推算)
    probe = img.crop((0, 0, min(64, img.width), min(64, img.height)))
    probe_out = upscale_onnx(probe, session)
    scale_x = probe_out.width / probe.width
    scale_y = probe_out.height / probe.height

    out_w = round(img.width * scale_x)
    out_h = round(img.height * scale_y)
    result = Image.new("RGB", (out_w, out_h))

    x_positions = list(range(0, img.width, tile_size - overlap))
    y_positions = list(range(0, img.height, tile_size - overlap))

    total = len(x_positions) * len(y_positions)
    done = 0

    for y in y_positions:
        for x in x_positions:
            x2 = min(x + tile_size, img.width)
            y2 = min(y + tile_size, img.height)
            tile = img.crop((x, y, x2, y2))
            tile_out = upscale_onnx(tile, session)

            # 目标粘贴位置
            paste_x = round(x * scale_x)
            paste_y = round(y * scale_y)
            result.paste(tile_out, (paste_x, paste_y))

            done += 1
            print(f"  分块进度: {done}/{total}", end="\r", flush=True)

    print()
    return result


# ─────────────────────────────────────────────
# 单文件处理
# ─────────────────────────────────────────────
def process_file(
    src: Path,
    dst: Path,
    mode: str,
    scale: int,
    session=None,
    tile: int = 512,
    quality: int = 95,
    format_out: str = None,
):
    img = Image.open(src)
    original_mode = img.mode  # 保留透明通道信息

    # 如果有 alpha 通道, ONNX 模式下分离处理
    alpha = None
    if img.mode in ("RGBA", "LA") and mode == "onnx":
        channels = img.split()
        alpha = channels[-1]
        img = img.convert("RGB")

    if mode == "lanczos":
        out_img = upscale_lanczos(img, scale)
    elif mode == "onnx":
        if img.width * img.height > tile * tile:
            out_img = upscale_onnx_tiled(img, session, tile_size=tile)
        else:
            out_img = upscale_onnx(img, session)
    else:
        raise ValueError(f"未知模式: {mode}")

    # 恢复 alpha 通道
    if alpha is not None:
        # alpha 也需要放大
        scale_factor = out_img.width / img.width
        new_a_size = (round(alpha.width * scale_factor), round(alpha.height * scale_factor))
        alpha_up = alpha.resize(new_a_size, Image.LANCZOS)
        out_img = out_img.convert("RGBA")
        out_img.putalpha(alpha_up)

    # 确定输出格式
    ext = dst.suffix.lower()
    if format_out:
        ext = "." + format_out.lower()
        dst = dst.with_suffix(ext)

    # 保存
    save_kwargs = {}
    if ext in (".jpg", ".jpeg"):
        save_kwargs["quality"] = quality
        save_kwargs["subsampling"] = 0
        if out_img.mode in ("RGBA", "P"):
            out_img = out_img.convert("RGB")
    elif ext == ".png":
        save_kwargs["compress_level"] = 1  # 快速压缩, 无损

    out_img.save(dst, **save_kwargs)
    return dst


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="批量无损放大图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", "-i", required=True, help="输入目录或单个图片文件")
    parser.add_argument("--output", "-o", required=True, help="输出目录")
    parser.add_argument("--mode", choices=["lanczos", "onnx"], default="lanczos",
                        help="放大模式: lanczos(默认,快速) / onnx(超分辨率,需要模型)")
    parser.add_argument("--scale", type=int, default=2, choices=[2, 3, 4],
                        help="放大倍率 (lanczos模式有效, 默认2x)")
    parser.add_argument("--model-path", help="ONNX 模型路径 (onnx模式必填)")
    parser.add_argument("--tile", type=int, default=512, help="分块大小 (onnx模式, 默认512)")
    parser.add_argument("--quality", type=int, default=95, help="JPEG 输出质量 (1-100, 默认95)")
    parser.add_argument("--format", dest="format_out", help="强制输出格式: png/jpg/webp")
    parser.add_argument("--recursive", action="store_true", help="递归处理子目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出文件")

    args = parser.parse_args()

    # 验证输入
    in_path = Path(args.input)
    out_dir = Path(args.output)

    if not in_path.exists():
        print(f"[错误] 输入路径不存在: {in_path}")
        sys.exit(1)

    if args.mode == "onnx" and not args.model_path:
        print("[错误] onnx 模式需要指定 --model-path")
        print("[提示] 可从 https://github.com/xinntao/Real-ESRGAN 下载 ONNX 模型")
        sys.exit(1)

    # 加载 ONNX 模型
    session = None
    if args.mode == "onnx":
        print(f"[信息] 加载 ONNX 模型: {args.model_path}")
        session = load_onnx_session(args.model_path)
        print("[信息] 模型加载完成")

    # 收集文件列表
    if in_path.is_file():
        files = [in_path]
        base_dir = in_path.parent
    else:
        base_dir = in_path
        pattern = "**/*" if args.recursive else "*"
        files = [f for f in in_path.glob(pattern) if f.is_file() and f.suffix.lower() in SUPPORTED_EXT]

    if not files:
        print(f"[警告] 未找到支持的图片文件 ({', '.join(SUPPORTED_EXT)})")
        sys.exit(0)

    print(f"\n[信息] 共找到 {len(files)} 张图片")
    print(f"[信息] 模式: {args.mode.upper()} | 倍率: {'模型决定' if args.mode=='onnx' else str(args.scale)+'x'}")
    print(f"[信息] 输出目录: {out_dir}\n")

    out_dir.mkdir(parents=True, exist_ok=True)

    # 批量处理
    success, skip, fail = 0, 0, 0
    t0 = time.time()

    for idx, src in enumerate(files, 1):
        # 保持子目录结构
        rel = src.relative_to(base_dir)
        dst = out_dir / rel

        if not args.overwrite and dst.exists():
            print(f"[{idx}/{len(files)}] 跳过 (已存在): {src.name}")
            skip += 1
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        try:
            t1 = time.time()
            out_file = process_file(
                src, dst,
                mode=args.mode,
                scale=args.scale,
                session=session,
                tile=args.tile,
                quality=args.quality,
                format_out=args.format_out,
            )
            elapsed = time.time() - t1
            src_size = os.path.getsize(src) / 1024
            dst_size = os.path.getsize(out_file) / 1024
            print(f"[{idx}/{len(files)}] ✓ {src.name} ({src_size:.0f}KB → {dst_size:.0f}KB, {elapsed:.1f}s)")
            success += 1
        except Exception as e:
            print(f"[{idx}/{len(files)}] ✗ {src.name}: {e}")
            fail += 1

    total_elapsed = time.time() - t0
    print(f"\n{'─'*50}")
    print(f"完成! 成功: {success} | 跳过: {skip} | 失败: {fail} | 总耗时: {total_elapsed:.1f}s")
    print(f"输出目录: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
