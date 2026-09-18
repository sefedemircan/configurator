"""Katalog ürün render'ından yakın kumaş örnek panosu üretimi."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _crop_box(image: Image.Image, rel: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = rel
    box = (
        int(width * left),
        int(height * top),
        int(width * right),
        int(height * bottom),
    )
    return image.crop(box)


# Catalog seat renders are centered on black. Prefer outer bolster panels for YAN.
_YAN_CROPS = (
    (0.18, 0.20, 0.36, 0.46),  # left backrest bolster
    (0.64, 0.20, 0.82, 0.46),  # right backrest bolster
    (0.14, 0.52, 0.34, 0.76),  # left cushion bolster
    (0.66, 0.52, 0.86, 0.76),  # right cushion bolster
)

_ORTA_CROPS = (
    (0.40, 0.26, 0.60, 0.48),  # center backrest
    (0.38, 0.54, 0.62, 0.72),  # center cushion
    (0.42, 0.32, 0.58, 0.44),  # upper center insert
    (0.42, 0.58, 0.58, 0.68),  # lower center insert
)

_IPLIK_CROPS = (
    (0.30, 0.35, 0.45, 0.42),
    (0.55, 0.35, 0.70, 0.42),
)


def allows_perforation(material_type: str | None) -> bool:
    if not material_type:
        return False
    text = material_type.upper()
    return any(token in text for token in ("DOT", "DELİK", "DELIK", "PERFOR"))


def suppress_perforation_look(image: Image.Image) -> Image.Image:
    """Remove small dark pinpricks so the model is not taught perforated leather."""
    rgb = image.convert("RGB")
    cleaned = rgb.filter(ImageFilter.MedianFilter(size=5))
    cleaned = cleaned.filter(ImageFilter.SMOOTH_MORE)
    return cleaned.convert("RGBA")


def _load_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _core_fabric_patch(fabric_photo: Image.Image) -> Image.Image:
    """Trim pinked / stitched edges so the board is mostly continuous fabric."""
    image = fabric_photo.convert("RGBA")
    width, height = image.size
    margin_x = max(4, int(width * 0.05))
    margin_y = max(4, int(height * 0.05))
    return image.crop((margin_x, margin_y, width - margin_x, height - margin_y))


def _square_cover(image: Image.Image, size: int) -> Image.Image:
    image = image.convert("RGBA")
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    crop = image.crop((left, top, left + side, top + side))
    return crop.resize((size, size), Image.Resampling.LANCZOS)


def _seat_distance_tile(core: Image.Image, tile_size: int, repeats: int = 4) -> Image.Image:
    """Same fabric at furniture scale: many small repeats instead of one giant macro."""
    cell = max(48, tile_size // repeats)
    small = _square_cover(core, cell)
    seat = Image.new("RGBA", (tile_size, tile_size), (20, 20, 20, 255))
    for row in range(repeats):
        for col in range(repeats):
            seat.paste(small, (col * cell, row * cell))
    return seat


def build_direct_fabric_board(
    fabric_photo: Image.Image,
    *,
    tile_size: int = 768,
    label: str = "",
) -> Image.Image:
    """Macro + seat-distance scale ladder (no 2x2 mosaic of the zoomed crop)."""
    core = _core_fabric_patch(fabric_photo)
    macro = _square_cover(core, tile_size)
    seat = _seat_distance_tile(core, tile_size)

    pad = 16
    caption_h = 40
    header = 64 if label else 0
    board = Image.new(
        "RGBA",
        (pad * 3 + tile_size * 2, header + tile_size + caption_h + pad),
        (20, 20, 20, 255),
    )
    draw = ImageDraw.Draw(board)
    title_font = _load_font(24)
    caption_font = _load_font(16)

    if label:
        draw.rectangle((0, 0, board.width, header), fill=(12, 12, 12, 255))
        draw.text((pad, 18), label[:90], fill=(255, 255, 255, 255), font=title_font)

    y0 = header
    board.paste(macro, (pad, y0))
    board.paste(seat, (pad * 2 + tile_size, y0))

    draw.text(
        (pad, y0 + tile_size + 8),
        "MACRO: grain identity — do NOT stamp at this size",
        fill=(230, 230, 230, 255),
        font=caption_font,
    )
    draw.text(
        (pad * 2 + tile_size, y0 + tile_size + 8),
        "SEAT DISTANCE: correct grain density on the cover",
        fill=(230, 230, 230, 255),
        font=caption_font,
    )
    return board


def build_fabric_swatch_board(
    product_render: Image.Image,
    layer_key: str,
    *,
    tile_size: int = 512,
    label: str = "",
    material_type: str | None = None,
) -> Image.Image:
    """Crop fabric regions from a seat product render and tile into a close-up board."""
    image = product_render.convert("RGBA")
    crops_map = {
        "yan": _YAN_CROPS,
        "orta": _ORTA_CROPS,
        "iplik": _IPLIK_CROPS,
    }
    rels = crops_map.get(layer_key, _YAN_CROPS)
    patches: list[Image.Image] = []
    for rel in rels:
        patch = _crop_box(image, rel).resize((tile_size, tile_size), Image.Resampling.LANCZOS)
        if layer_key in {"yan", "orta"} and not allows_perforation(material_type):
            patch = suppress_perforation_look(patch)
        patches.append(patch)

    cols = 2
    rows = (len(patches) + cols - 1) // cols
    header = 72 if label else 0
    board = Image.new("RGBA", (cols * tile_size, rows * tile_size + header), (20, 20, 20, 255))

    if label:
        draw = ImageDraw.Draw(board)
        draw.rectangle((0, 0, board.width, header), fill=(12, 12, 12, 255))
        draw.text((16, 20), label[:80], fill=(255, 255, 255, 255), font=_load_font(28))

    for index, patch in enumerate(patches):
        x = (index % cols) * tile_size
        y = header + (index // cols) * tile_size
        board.paste(patch, (x, y))

    return board
