import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.schemas.tryon import TryOnCompositeRequest, TryOnCompositeResponse
from app.services.pipeline import run_tryon_pipeline, stream_tryon_pipeline

router = APIRouter(prefix="/api/v1/tryon", tags=["tryon"])


def _verify_api_key(x_api_key: str | None) -> None:
    settings = get_settings()
    if settings.tryon_api_key and x_api_key != settings.tryon_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/composite", response_model=TryOnCompositeResponse)
async def composite_tryon(
    request: TryOnCompositeRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> TryOnCompositeResponse:
    _verify_api_key(x_api_key)

    if not request.scene_image.strip():
        raise HTTPException(status_code=422, detail="scene_image is required")

    try:
        return await run_tryon_pipeline(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Try-on pipeline failed: {exc}") from exc


@router.post("/composite/stream")
async def composite_tryon_stream(
    request: TryOnCompositeRequest,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> StreamingResponse:
    _verify_api_key(x_api_key)

    if not request.scene_image.strip():
        raise HTTPException(status_code=422, detail="scene_image is required")

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for event in stream_tryon_pipeline(request):
                yield f"data: {json.dumps(event.model_dump())}\n\n"
        except Exception as exc:
            error_event = {"type": "error", "text": str(exc)}
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
