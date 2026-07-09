import logging
from collections.abc import AsyncIterator

from app.schemas.tryon import SeatRegion, TryOnCompositeRequest, TryOnCompositeResponse, TryOnStreamEvent
from app.services.generative_tryon import prepare_product_data_url, run_generative_tryon
from app.services.product_composite import compose_product_image
from app.services.vision import detect_seat_regions, get_visible_seat_ids, order_visible_seat_ids
from app.utils.images import decode_image_data, encode_image_data

logger = logging.getLogger(__name__)


def _resolve_visible_seats(
    regions: list[SeatRegion],
    seat_target: str,
    warnings: list[str],
) -> list[str]:
    detected = get_visible_seat_ids(regions)

    if seat_target == "auto":
        return detected

    if seat_target not in detected:
        warnings.append(
            f"Seçilen koltuk ({seat_target}) görünür değil; yine de uygulanmaya çalışılacak."
        )
        return order_visible_seat_ids([seat_target])

    return [seat_target]


async def run_tryon_pipeline(request: TryOnCompositeRequest) -> TryOnCompositeResponse:
    warnings: list[str] = []
    stages = ["decode_scene", "vision_detection"]

    scene_image = decode_image_data(request.scene_image)
    scene_data_url = request.scene_image
    if not scene_data_url.startswith("data:"):
        scene_data_url = encode_image_data(scene_image)

    regions, vision_confidence, vision_warnings, _camera_angle = await detect_seat_regions(
        scene_data_url
    )
    warnings.extend(vision_warnings)

    visible_seats = _resolve_visible_seats(regions, request.seat_target, warnings)

    stages.append("product_composite")
    product_image = await compose_product_image(request.product_layers)
    product_data_url = await prepare_product_data_url(
        request.product_layers.base or "",
        product_image,
    )

    for seat_id in visible_seats:
        stages.append(f"generative_tryon_{seat_id}")

    result_data_url, confidence, gen_warnings = await run_generative_tryon(
        scene_data_url=scene_data_url,
        product_data_url=product_data_url,
        visible_seat_ids=visible_seats,
        product_reference=request.product_reference,
        vehicle_info=request.vehicle_info,
    )
    warnings.extend(gen_warnings)
    stages.append("done")

    blended_confidence = round((confidence + vision_confidence) / 2, 3)

    return TryOnCompositeResponse(
        result_image=result_data_url,
        placement_confidence=blended_confidence,
        seat_regions=regions,
        warnings=warnings,
        pipeline_stages=stages,
        product_reference=request.product_reference,
    )


async def stream_tryon_pipeline(request: TryOnCompositeRequest) -> AsyncIterator[TryOnStreamEvent]:
    yield TryOnStreamEvent(type="status", text="Araç içi fotoğraf analiz ediliyor...")

    scene_image = decode_image_data(request.scene_image)
    scene_data_url = request.scene_image
    if not scene_data_url.startswith("data:"):
        scene_data_url = encode_image_data(scene_image)

    regions, vision_confidence, vision_warnings, _camera_angle = await detect_seat_regions(
        scene_data_url
    )

    warnings = list(vision_warnings)
    visible_seats = _resolve_visible_seats(regions, request.seat_target, warnings)

    yield TryOnStreamEvent(
        type="status",
        text=f"{len(visible_seats)} görünür koltuk tespit edildi.",
        warnings=vision_warnings,
    )

    yield TryOnStreamEvent(type="status", text="Ürün görseli hazırlanıyor...")
    product_image = await compose_product_image(request.product_layers)
    product_data_url = await prepare_product_data_url(
        request.product_layers.base or "",
        product_image,
    )

    for index, seat_id in enumerate(visible_seats, start=1):
        yield TryOnStreamEvent(
            type="status",
            text=f"Kılıf uygulanıyor ({index}/{len(visible_seats)}): {seat_id}...",
        )

    try:
        result_data_url, confidence, gen_warnings = await run_generative_tryon(
            scene_data_url=scene_data_url,
            product_data_url=product_data_url,
            visible_seat_ids=visible_seats,
            product_reference=request.product_reference,
            vehicle_info=request.vehicle_info,
        )
        warnings.extend(gen_warnings)
    except Exception as exc:
        yield TryOnStreamEvent(type="error", text=str(exc))
        return

    blended_confidence = round((confidence + vision_confidence) / 2, 3)

    yield TryOnStreamEvent(
        type="tryon_preview_ready",
        result_image=result_data_url,
        placement_confidence=blended_confidence,
        warnings=warnings,
    )
    yield TryOnStreamEvent(type="done", text="Önizleme hazır.")
