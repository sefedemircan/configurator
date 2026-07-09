import json
import logging
import re

import httpx

from app.config import get_settings
from app.schemas.tryon import Point2D, SeatRegion

logger = logging.getLogger(__name__)

VALID_SEAT_IDS = frozenset(
    {
        "front_driver",
        "front_passenger",
        "rear_left",
        "rear_right",
        "rear_bench",
    }
)

# Arka koltuklar önce, ön koltuklar sonra — üst üste binmeyi azaltır.
SEAT_APPLY_ORDER = [
    "rear_left",
    "rear_right",
    "rear_bench",
    "front_driver",
    "front_passenger",
]

VISION_PROMPT = """Analyze this car interior photo for virtual seat cover placement.

Identify every seat that is clearly visible in the image (up to 5 seats).
Include front seats, rear seats, or a full rear bench — only if their upholstery is visible.

Return ONLY valid JSON:
{
  "confidence": 0.0-1.0,
  "seats": [
    {
      "seat_id": "front_driver" | "front_passenger" | "rear_left" | "rear_right" | "rear_bench",
      "label": "human readable Turkish label",
      "visible": true,
      "confidence": 0.0-1.0,
      "corners": [
        {"x": 0.0-1.0, "y": 0.0-1.0},
        {"x": 0.0-1.0, "y": 0.0-1.0},
        {"x": 0.0-1.0, "y": 0.0-1.0},
        {"x": 0.0-1.0, "y": 0.0-1.0}
      ]
    }
  ],
  "camera_angle": "frontal" | "side_passenger" | "side_driver" | "rear" | "overhead",
  "photo_quality": "good" | "fair" | "poor",
  "warnings": []
}

Rules:
- seat_id must be one of the allowed values
- Use rear_bench for one continuous rear seat row; use rear_left/rear_right for split rear seats
- Only include seats with visible upholstery (visible: true)
- corners: top-left, top-right, bottom-right, bottom-left (normalized 0-1)
- If no seats visible, return confidence 0 and empty seats array"""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _default_seat_regions() -> list[SeatRegion]:
    return [
        SeatRegion(
            seat_id="front_driver",
            label="Ön sürücü koltuğu",
            confidence=0.35,
            corners=[
                Point2D(x=0.08, y=0.42),
                Point2D(x=0.46, y=0.42),
                Point2D(x=0.44, y=0.88),
                Point2D(x=0.06, y=0.88),
            ],
        ),
        SeatRegion(
            seat_id="front_passenger",
            label="Ön yolcu koltuğu",
            confidence=0.35,
            corners=[
                Point2D(x=0.54, y=0.42),
                Point2D(x=0.92, y=0.42),
                Point2D(x=0.94, y=0.88),
                Point2D(x=0.56, y=0.88),
            ],
        ),
    ]


def order_visible_seat_ids(seat_ids: list[str]) -> list[str]:
    unique = list(dict.fromkeys(seat_ids))
    if "rear_bench" in unique:
        unique = [s for s in unique if s not in {"rear_left", "rear_right"}]
    return [seat_id for seat_id in SEAT_APPLY_ORDER if seat_id in unique]


def get_visible_seat_ids(regions: list[SeatRegion]) -> list[str]:
    return order_visible_seat_ids([region.seat_id for region in regions])


async def detect_seat_regions(
    scene_image_data_url: str,
) -> tuple[list[SeatRegion], float, list[str], str | None]:
    settings = get_settings()
    warnings: list[str] = []

    if not settings.openrouter_api_key:
        warnings.append("OpenRouter API anahtarı yok; varsayılan ön koltuklar kullanılıyor.")
        regions = _default_seat_regions()
        return regions, 0.35, warnings, None

    payload = {
        "model": settings.openrouter_vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": scene_image_data_url}},
                ],
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://otom.ai",
        "X-Title": "Otom Virtual Try-On",
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            text_parts = [part.get("text", "") for part in content if isinstance(part, dict)]
            content = "".join(text_parts)

        parsed = _extract_json(str(content))
        overall_confidence = float(parsed.get("confidence", 0.5))
        warnings.extend(str(w) for w in parsed.get("warnings", []) if w)

        photo_quality = parsed.get("photo_quality")
        if photo_quality == "poor":
            warnings.append("Fotoğraf kalitesi düşük; farklı açıdan çekmeyi deneyin.")
            overall_confidence = min(overall_confidence, 0.4)

        seats_raw = parsed.get("seats", [])
        regions: list[SeatRegion] = []
        for seat in seats_raw:
            if seat.get("visible") is False:
                continue

            seat_id = str(seat.get("seat_id", "")).strip()
            if seat_id not in VALID_SEAT_IDS:
                continue

            corners_raw = seat.get("corners", [])
            if len(corners_raw) != 4:
                continue

            corners = [
                Point2D(x=float(c["x"]), y=float(c["y"]))
                for c in corners_raw
                if "x" in c and "y" in c
            ]
            if len(corners) != 4:
                continue

            regions.append(
                SeatRegion(
                    seat_id=seat_id,
                    label=str(seat.get("label", seat_id)),
                    confidence=float(seat.get("confidence", overall_confidence)),
                    corners=corners,
                )
            )

        if not regions:
            warnings.append("Görünür koltuk tespit edilemedi; varsayılan ön koltuklar kullanılıyor.")
            regions = _default_seat_regions()
            overall_confidence = min(overall_confidence, 0.35)

        camera_angle = parsed.get("camera_angle")
        if isinstance(camera_angle, str):
            camera_angle = camera_angle.strip().lower()
        else:
            camera_angle = None

        visible_ids = get_visible_seat_ids(regions)
        warnings.append(
            f"Görünür koltuklar: {', '.join(visible_ids)} ({len(visible_ids)} adet)."
        )

        return regions, overall_confidence, warnings, camera_angle

    except Exception as exc:
        logger.exception("Vision detection failed: %s", exc)
        warnings.append("Görüntü analizi başarısız; varsayılan ön koltuklar kullanılıyor.")
        return _default_seat_regions(), 0.3, warnings, None
