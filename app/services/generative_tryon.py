"""Generatif try-on — OpenRouter Gemini Image."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.schemas.tryon import ProductReference, VehicleInfo
from app.utils.images import encode_image_data

logger = logging.getLogger(__name__)

FALLBACK_IMAGE_MODELS = (
    "google/gemini-3.1-flash-image-preview",
    "google/gemini-2.5-flash-image",
)

SEAT_LABELS = {
    "front_driver": "driver seat (behind the steering wheel, left side in LHD cars)",
    "front_passenger": "front passenger seat (opposite the steering wheel, right side in LHD cars)",
    "rear_left": "rear left seat (left side of the rear row)",
    "rear_right": "rear right seat (right side of the rear row)",
    "rear_bench": "full rear bench seat (entire rear row as one continuous seat)",
}


def _build_prompt(
    seat_id: str,
    other_seat_ids: list[str],
    product_reference: ProductReference | None,
    vehicle_info: VehicleInfo | None,
    *,
    pass_label: str | None = None,
) -> str:
    product_name = product_reference.title if product_reference else "seat cover"
    vehicle = ""
    if vehicle_info and (vehicle_info.brand or vehicle_info.model):
        vehicle = f" Vehicle: {vehicle_info.brand} {vehicle_info.model}."

    target = SEAT_LABELS.get(seat_id, seat_id)
    pass_note = f"\nPass: {pass_label}." if pass_label else ""

    if other_seat_ids:
        others = ", ".join(SEAT_LABELS.get(s, s) for s in other_seat_ids)
        preserve = f"Keep these seats exactly as in Image 1 (unchanged upholstery): {others}."
    else:
        preserve = "Only modify the target seat; keep all other interior parts unchanged."

    return f"""Edit this car interior photo for a virtual seat cover try-on preview.{pass_note}

Image 1: Customer's car interior photo (edit this image).
Image 2: Seat cover product reference — copy pattern, color, stitching, and texture from here.

Task: Apply the seat cover from Image 2 onto the {target} in Image 1.
Product: {product_name}.{vehicle}

Coverage:
- Cover the seat backrest AND seat cushion; include headrest if visible.
- {preserve}

Rules:
- Preserve exact product pattern, colors, stitching, and material from Image 2
- Do NOT change steering wheel, dashboard, doors, windows, center console, or seatbelts
- Match interior lighting and shadows naturally
- Photorealistic; no illustration style
- No watermarks or text overlays

Output one edited photo with the cover fitted only on the specified seat."""


def _extract_image_data_url(message: dict) -> str | None:
    images = message.get("images") or []
    for item in images:
        if not isinstance(item, dict):
            continue
        image_url = item.get("image_url") or {}
        url = image_url.get("url") if isinstance(image_url, dict) else None
        if isinstance(url, str) and url.startswith("data:image"):
            return url

    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url")
                if isinstance(url, str) and url.startswith("data:image"):
                    return url
    return None


async def _call_image_model(
    client: httpx.AsyncClient,
    headers: dict,
    model: str,
    scene_data_url: str,
    product_data_url: str,
    prompt: str,
) -> str | None:
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": scene_data_url}},
                    {"type": "image_url", "image_url": {"url": product_data_url}},
                ],
            }
        ],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": "4:3"},
    }

    response = await client.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    data = response.json()
    message = data["choices"][0]["message"]
    return _extract_image_data_url(message)


async def _generate_with_models(
    scene_data_url: str,
    product_data_url: str,
    prompt: str,
) -> tuple[str, list[str]]:
    settings = get_settings()
    warnings: list[str] = []

    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY gerekli.")

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://otom.ai",
        "X-Title": "Otom Virtual Try-On Generative",
    }

    models_to_try = [settings.openrouter_image_model, *FALLBACK_IMAGE_MODELS]
    seen: set[str] = set()
    models: list[str] = []
    for model in models_to_try:
        if model and model not in seen:
            seen.add(model)
            models.append(model)

    last_error: Exception | None = None

    async with httpx.AsyncClient(timeout=180.0) as client:
        for model in models:
            try:
                result_url = await _call_image_model(
                    client, headers, model, scene_data_url, product_data_url, prompt
                )
                if result_url:
                    if model != settings.openrouter_image_model:
                        warnings.append(f"Yedek model kullanıldı: {model}")
                    return result_url, warnings
                warnings.append(f"{model}: görüntü çıktısı alınamadı.")
            except httpx.HTTPStatusError as exc:
                last_error = exc
                warnings.append(f"{model} başarısız: HTTP {exc.response.status_code}")
                logger.warning("Generative try-on model %s failed: %s", model, exc)
            except Exception as exc:
                last_error = exc
                warnings.append(f"{model} başarısız: {exc}")
                logger.warning("Generative try-on model %s failed: %s", model, exc)

    detail = str(last_error) if last_error else "bilinmeyen hata"
    raise RuntimeError(f"Generatif try-on başarısız: {detail}")


async def _apply_single_seat(
    scene_data_url: str,
    product_data_url: str,
    seat_id: str,
    all_seat_ids: list[str],
    product_reference: ProductReference | None,
    vehicle_info: VehicleInfo | None,
    *,
    pass_label: str | None = None,
) -> tuple[str, list[str]]:
    other_seats = [s for s in all_seat_ids if s != seat_id]
    prompt = _build_prompt(
        seat_id,
        other_seats,
        product_reference,
        vehicle_info,
        pass_label=pass_label,
    )
    return await _generate_with_models(scene_data_url, product_data_url, prompt)


async def run_generative_tryon(
    scene_data_url: str,
    product_data_url: str,
    visible_seat_ids: list[str],
    product_reference: ProductReference | None = None,
    vehicle_info: VehicleInfo | None = None,
) -> tuple[str, float, list[str]]:
    """Görünür her koltuğa sırayla kılıf uygular."""
    if not visible_seat_ids:
        raise ValueError("Uygulanacak görünür koltuk bulunamadı.")

    warnings: list[str] = []
    total = len(visible_seat_ids)
    warnings.append(f"{total} görünür koltuğa sırayla uygulanıyor.")

    scene_url = scene_data_url
    for index, seat_id in enumerate(visible_seat_ids, start=1):
        scene_url, step_warnings = await _apply_single_seat(
            scene_url,
            product_data_url,
            seat_id,
            visible_seat_ids,
            product_reference,
            vehicle_info,
            pass_label=f"{index}/{total} {seat_id}",
        )
        warnings.extend(step_warnings)

    warnings.append(
        "Generatif önizleme — desen/renk yaklaşık olabilir; sipariş görseli değildir."
    )
    confidence = min(0.85, 0.65 + 0.05 * total)
    return scene_url, confidence, warnings


async def prepare_product_data_url(product_data_url: str, product_image) -> str:
    if product_data_url.startswith("data:"):
        return product_data_url
    return encode_image_data(product_image)
