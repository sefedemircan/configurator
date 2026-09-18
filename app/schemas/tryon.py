from typing import Literal

from pydantic import BaseModel, Field


class Point2D(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class SeatRegion(BaseModel):
    seat_id: str
    label: str
    confidence: float = Field(ge=0, le=1)
    corners: list[Point2D] = Field(min_length=4, max_length=4)
    center: Point2D | None = None


class VehicleInfo(BaseModel):
    year: str = ""
    brand: str = ""
    model: str = ""
    vehicle_type: str = ""
    seat_count: int = 5


class ProductLayerSelection(BaseModel):
    deger: str = ""
    name: str = ""
    image: str | None = None


class ProductLayers(BaseModel):
    base: str | None = None
    yan: str | None = None
    orta: str | None = None
    iplik: str | None = None
    overlay: str | None = None


class ProductReference(BaseModel):
    """Shopify katalog referansı — try-on'da kullanılan görsel kaynağı."""
    title: str
    handle: str | None = None
    image_url: str
    shopify_id: str | None = None
    product_category: str | None = None


class TryOnCompositeRequest(BaseModel):
    scene_image: str
    product_layers: ProductLayers
    product_reference: ProductReference | None = None
    vehicle_info: VehicleInfo | None = None
    layer_material_types: dict[str, str] = Field(default_factory=dict)
    layer_is_direct_swatch: dict[str, bool] = Field(default_factory=dict)
    layer_product_codes: dict[str, str] = Field(default_factory=dict)
    layer_color_names: dict[str, str] = Field(default_factory=dict)
    seat_target: Literal[
        "auto",
        "front_driver",
        "front_passenger",
        "rear_left",
        "rear_right",
        "rear_bench",
    ] = "auto"


class TryOnCompositeResponse(BaseModel):
    result_image: str
    placement_confidence: float
    seat_regions: list[SeatRegion] = []
    warnings: list[str] = []
    pipeline_stages: list[str] = []
    product_reference: ProductReference | None = None


class TryOnStreamEvent(BaseModel):
    type: Literal["status", "tryon_preview_ready", "error", "done"]
    text: str | None = None
    result_image: str | None = None
    placement_confidence: float | None = None
    warnings: list[str] = []
