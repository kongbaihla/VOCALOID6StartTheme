# -*- coding: utf-8 -*-
"""
V6PAC 图片处理
==============
* 解码任意常见格式
* 裁剪到 1200x714 (锁定比例, 只能平移缩放, 保证填满且不变形)
* 分级压缩: 无损优先, 够用就停; 超容量才降质
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageTk

# 封面目标尺寸 —— 与 splashwindow.baml 的布局匹配, 不可随意更改
TARGET_W, TARGET_H = 1200, 714
TARGET_RATIO = TARGET_W / TARGET_H

# 支持的输入格式
SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif",
                 ".tiff", ".ico", ".ppm", ".pgm", ".tga"}


class ImageError(Exception):
    """图片处理的可预期错误。"""


# ---------------------------------------------------------------- 解码

def load_image(path: str | os.PathLike) -> Image.Image:
    """读取任意格式图片, 统一为 RGBA。"""
    p = Path(path)
    if not p.is_file():
        raise ImageError(f"文件不存在: {p}")
    try:
        im = Image.open(p)
        im.load()
    except Exception as e:
        raise ImageError(f"无法读取图片: {e}")
    return im.convert("RGBA")


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} 字节"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


# ---------------------------------------------------------------- 裁剪

@dataclass
class CropView:
    """
    裁剪取景状态 (锁定比例)。
    zoom = 1.0 表示"刚好填满目标比例的最小缩放";
    cx, cy 是取景框中心在**原图归一化坐标**中的位置 (0..1)。
    """
    zoom: float = 1.0
    cx: float = 0.5
    cy: float = 0.5

    def clamp(self) -> None:
        self.zoom = max(1.0, min(20.0, self.zoom))
        self.cx = max(0.0, min(1.0, self.cx))
        self.cy = max(0.0, min(1.0, self.cy))


def base_scale(img_w: int, img_h: int) -> float:
    """填满目标比例所需的最小缩放 (使裁剪框完全落在图内)。"""
    return max(TARGET_W / img_w, TARGET_H / img_h)


def crop_box(img_w: int, img_h: int, view: CropView) -> tuple[int, int, int, int]:
    """
    计算在原图上的裁剪矩形 (left, top, right, bottom)。
    裁剪框始终是 TARGET_W:TARGET_H 比例, 且不超出原图。
    """
    view.clamp()
    scale = base_scale(img_w, img_h) * view.zoom
    # 裁剪框在原图坐标系下的尺寸
    bw = TARGET_W / scale
    bh = TARGET_H / scale
    bw = min(bw, img_w)
    bh = min(bh, img_h)

    # 中心位置
    left = view.cx * img_w - bw / 2.0
    top = view.cy * img_h - bh / 2.0
    left = max(0.0, min(img_w - bw, left))
    top = max(0.0, min(img_h - bh, top))

    return (int(round(left)), int(round(top)),
            int(round(left + bw)), int(round(top + bh)))


def render_crop(img: Image.Image, view: CropView) -> Image.Image:
    """按取景状态渲染出 1200x714 的封面图。"""
    box = crop_box(img.width, img.height, view)
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        raise ImageError("裁剪区域无效。")
    cropped = img.crop(box)
    return cropped.resize((TARGET_W, TARGET_H), Image.LANCZOS)


def auto_view(img: Image.Image) -> CropView:
    """默认取景: 居中、填满。"""
    return CropView(1.0, 0.5, 0.5)


# ---------------------------------------------------------------- 压缩

@dataclass
class CompressResult:
    data: bytes
    level: str            # 级别描述
    lossless: bool        # 是否无损
    colors: int | None    # 调色板色数 (无损为 None)


def _png_size(img: Image.Image, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", **kw)
    return buf.getvalue()


def compress_to_limit(img: Image.Image, limit: int) -> CompressResult:
    """
    把 1200x714 的图压缩到 <= limit 字节。

    顺序 (够用就停):
      1. 无损 + optimize
      2. 无损 + compress_level=9 + optimize
      3. 调色板 256 / 192 / 128 / 96 / 64 / 48 / 32 / 24 / 16 色
      4. 若仍超出, 返回 16 色结果 (由调用方决定是否接受)
    """
    rgba = img.convert("RGBA")

    # --- 级别 1/2: 无损 ---
    best = _png_size(rgba, optimize=True)
    if len(best) <= limit:
        return CompressResult(best, "无损 (optimize)", True, None)

    for lvl in (9,):
        d = _png_size(rgba, optimize=True, compress_level=lvl)
        if len(d) < len(best):
            best = d
        if len(d) <= limit:
            return CompressResult(d, f"无损 (压缩级别 {lvl})", True, None)

    # 若原图没有透明像素, 用 RGB 能显著减小体积
    has_alpha = rgba.getchannel("A").getextrema()[0] < 255
    base = rgba if has_alpha else rgba.convert("RGB")
    d = _png_size(base, optimize=True)
    if len(d) < len(best):
        best = d
    if len(d) <= limit:
        return CompressResult(d, "无损 (去除冗余 alpha)", True, None)

    # --- 级别 3: 调色板量化 ---
    palette_src = base.convert("RGB") if has_alpha else base
    last: CompressResult | None = None
    for colors in (256, 192, 128, 96, 64, 48, 32, 24, 16):
        try:
            q = palette_src.quantize(colors=colors, method=Image.MEDIANCUT,
                                     dither=Image.Dither.NONE)
        except Exception:
            continue
        d = _png_size(q, optimize=True)
        last = CompressResult(d, f"调色板 {colors} 色", False, colors)
        if len(d) <= limit:
            return last

    if last is None:
        raise ImageError("压缩失败: 无法生成任何可用结果。")
    return last


def fits_inplace(img: Image.Image, limit: int) -> bool:
    """该图能否无损塞进上限。"""
    return len(_png_size(img.convert("RGBA"), optimize=True)) <= limit


# ---------------------------------------------------------------- 预览

def make_preview(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """生成不超过 max_w x max_h 的预览缩略图。"""
    im = img.copy()
    im.thumbnail((max_w, max_h), Image.LANCZOS)
    return im


def render_crop_fast(img: Image.Image, view: CropView,
                     out_w: int = 0, out_h: int = 0) -> Image.Image:
    """
    快速渲染: 使用 BILINEAR 并把输出限制在小尺寸。
    用于拖动时的即时预览 (LANCZOS 太慢)。
    """
    box = crop_box(img.width, img.height, view)
    if box[2] - box[0] < 1 or box[3] - box[1] < 1:
        raise ImageError("裁剪区域无效。")
    if out_w <= 0 or out_h <= 0:
        out_w, out_h = TARGET_W, TARGET_H
    cropped = img.crop(box)
    return cropped.resize((out_w, out_h), Image.BILINEAR)


def render_crop_preview(img: Image.Image, base: Image.Image, view: CropView,
                        out_w: int, out_h: int) -> Image.Image:
    """
    基于**已缩小的底图**做裁剪预览 —— 远比从原图 LANCZOS 缩放快。
    base 与 img 尺寸比例一致 (由 make_preview 生成)。
    """
    scale = base.width / img.width
    box = crop_box(img.width, img.height, view)
    b = (int(box[0] * scale), int(box[1] * scale),
         int(box[2] * scale), int(box[3] * scale))
    b = (max(0, b[0]), max(0, b[1]),
         min(base.width, max(b[2], b[0] + 1)),
         min(base.height, max(b[3], b[1] + 1)))
    cropped = base.crop(b)
    return cropped.resize((out_w, out_h), Image.BILINEAR)


def to_tk(img: Image.Image) -> ImageTk.PhotoImage:
    return ImageTk.PhotoImage(img)
