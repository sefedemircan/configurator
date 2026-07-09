import logging
from io import BytesIO

import httpx
from PIL import Image

from app.schemas.tryon import ProductLayers

logger = logging.getLogger(__name__)

LAYER_ORDER = ["base", "yan", "orta", "iplik", "overlay"]


async def _load_layer_image(url: str | None) -> Image.Image | None:
    if not url or not url.strip():
        return None

    value = url.strip()
    if value.startswith("data:image"):
        from app.utils.images import decode_image_data

        return decode_image_data(value)

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
