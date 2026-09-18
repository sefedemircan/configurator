import asyncio
import logging
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image

from app.schemas.tryon import ProductLayers
from app.services.fabric_swatches import build_direct_fabric_board, build_fabric_swatch_board

logger = logging.getLogger(__name__)

LAYER_ORDER = ["base", "yan", "orta", "iplik", "overlay"]

_LAYER_MAX_SIDE = {"yan": 2048, "orta": 1536, "iplik": 768}
_SWATCH_LABELS = {
    "yan": "YAN GOVDE SCALE BOARD — left MACRO / right SEAT DISTANCE",
    "orta": "ORTA KISIM SCALE BOARD — left MACRO / right SEAT DISTANCE",
    "iplik": "IPLIK THREAD CLOSE-UP — stitch color only",
}
_CATALOG_SWATCH_LABELS = {
    "yan": "YAN GOVDE FABRIC CLOSE-UP — copy this surface 1:1",
    "orta": "ORTA KISIM FABRIC CLOSE-UP — copy this surface 1:1",
    "iplik": "IPLIK THREAD CLOSE-UP — stitch color only",
}


def _local_path_from_value(value: str) -> Path | None:
    raw = value.strip()
    if raw.startswith("file:"):
        parsed = urlparse(raw)
        path_str = unquote(parsed.path or "")
        # Windows: file:///C:/path -> /C:/path
        if path_str.startswith("/") and len(path_str) > 2 and path_str[2] == ":":
            path_str = path_str[1:]
        path = Path(path_str)
        return path if path.exists() else None

    path = Path(raw)
    if path.exists() and path.is_file():
        return path
    return None


async def _load_layer_image(url: str | None) -> Image.Image | None:
    if not url or not url.strip():
        return None

    value = url.strip()
    if value.startswith("data:image"):
        from app.utils.images import decode_image_data

        return decode_image_data(value)

    local = _local_path_from_value(value)
    if local is not None:
        try:
            return Image.open(local).convert("RGBA")
        except Exception as exc:
            logger.warning("Failed to load local layer image %s: %s", local, exc)
            return None

    if value.startswith("/"):
        return None

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(value)
            response.raise_for_status()
            return Image.open(BytesIO(response.content)).convert("RGBA")
    except Exception as exc:
        logger.warning("Failed to load layer image %s: %s", value[:80], exc)
        return None


def _alpha_composite(base: Image.Image, overlay: Image.Image) -> Image.Image:
    if base.size != overlay.size:
        overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
    return Image.alpha_composite(base, overlay)


def _prepare_fabric_reference(image: Image.Image, max_side: int = 1280) -> Image.Image:
    """Keep fabric grain; avoid JPEG smear on YAN GÖVDE / ORTA KISIM swatches."""
    image = image.convert("RGBA")
    width, height = image.size
    longest = max(width, height)
    if longest > max_side:
        scale = max_side / longest
        image = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.Resampling.LANCZOS,
        )
    return image


async def load_layer_data_urls(layers: ProductLayers) -> dict[str, str]:
    """Download yan / orta / iplik product renders as lossless data URLs."""
    from app.utils.images import encode_image_data

    keys = ("yan", "orta", "iplik")
    images = await asyncio.gather(
        *[_load_layer_image(getattr(layers, key, None)) for key in keys]
    )
    result: dict[str, str] = {}
    for key, image in zip(keys, images):
        if image is not None:
            max_side = _LAYER_MAX_SIDE.get(key, 1280)
            result[key] = encode_image_data(
                _prepare_fabric_reference(image, max_side=max_side),
                fmt="PNG",
            )
    return result


async def load_layer_reference_pack(
    layers: ProductLayers,
    layer_material_types: dict[str, str] | None = None,
    layer_is_direct_swatch: dict[str, bool] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return product-render data URLs and close-up fabric swatch boards."""
    from app.utils.images import encode_image_data

    keys = ("yan", "orta", "iplik")
    material_types = layer_material_types or {}
    direct_flags = layer_is_direct_swatch or {}
    images = await asyncio.gather(
        *[_load_layer_image(getattr(layers, key, None)) for key in keys]
    )

    product_urls: dict[str, str] = {}
    swatch_urls: dict[str, str] = {}

    for key, image in zip(keys, images):
        if image is None:
            continue
        max_side = _LAYER_MAX_SIDE.get(key, 1280)
        prepared = _prepare_fabric_reference(image, max_side=max_side)
        product_urls[key] = encode_image_data(prepared, fmt="PNG")
        if direct_flags.get(key):
            swatch = build_direct_fabric_board(
                prepared,
                tile_size=768,
                label=_SWATCH_LABELS.get(key, key.upper()),
            )
        else:
            swatch = build_fabric_swatch_board(
                prepared,
                key,
                tile_size=640 if key == "yan" else 512,
                label=_CATALOG_SWATCH_LABELS.get(key, key.upper()),
                material_type=material_types.get(key),
            )
        swatch_urls[key] = encode_image_data(swatch, fmt="PNG")

    return product_urls, swatch_urls


async def compose_product_image(layers: ProductLayers) -> Image.Image:
    canvas: Image.Image | None = None

    for key in LAYER_ORDER:
        src = getattr(layers, key, None)
        layer = await _load_layer_image(src)
        if layer is None:
            continue

        if canvas is None:
            canvas = layer.copy()
            continue

        canvas = _alpha_composite(canvas, layer)

    if canvas is None:
        canvas = Image.new("RGBA", (1024, 768), (40, 40, 40, 255))

    return canvas
