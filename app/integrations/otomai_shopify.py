from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass
class CatalogProduct:
    title: str
    handle: str
    image_url: str
    price: str
    product_id: str
    all_images: list[dict[str, str]]


def _resolve_otomai_path() -> Path:
    configured = os.getenv("OTOMAI_BACKEND_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "otomai"


@lru_cache
def _load_shopify_client():
    otomai_path = _resolve_otomai_path()
    if not otomai_path.is_dir():
        raise FileNotFoundError(
            f"otomai backend bulunamadı: {otomai_path}. "
            "OTOMAI_BACKEND_PATH ortam değişkenini ayarlayın."
        )
    path_str = str(otomai_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    from shopify_client import (  # type: ignore[import-not-found]
        get_product_detail,
        list_universal_koltuk_kilifi_products,
        search_products_by_vehicle,
    )

    return get_product_detail, list_universal_koltuk_kilifi_products, search_products_by_vehicle


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Shopify yanıtı geçersiz JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Beklenmeyen Shopify yanıtı")
    if data.get("error"):
        raise ValueError(str(data["error"]))
    return data


def extract_images_from_payload(data: dict[str, Any]) -> list[dict[str, str]]:
    """example_llm_client.extract_product_images ile aynı mantık."""
    images: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: str, caption: str = "") -> None:
        if not url or url in seen:
            return
        seen.add(url)
        images.append({"url": url, "caption": caption or ""})

    if isinstance(data.get("products"), list):
        for product in data["products"]:
            featured = product.get("featuredImage") or {}
            add(featured.get("url", ""), product.get("title") or featured.get("altText") or "")

    featured = data.get("featuredImage") or {}
    add(featured.get("url", ""), data.get("title") or featured.get("altText") or "")

    for image in data.get("images", []):
        if isinstance(image, dict):
            add(image.get("url", ""), image.get("altText") or data.get("title", ""))

    return images


def _format_price(product: dict[str, Any]) -> str:
    amount = (
        product.get("priceRangeV2", {})
        .get("minVariantPrice", {})
        .get("amount")
    )
    currency = (
        product.get("priceRangeV2", {})
        .get("minVariantPrice", {})
        .get("currencyCode", "TRY")
    )
    if amount is None:
        return "—"
    try:
        value = float(amount)
        return f"{value:,.0f} {currency}".replace(",", ".")
    except (TypeError, ValueError):
        return str(amount)


def _product_to_catalog(product: dict[str, Any]) -> CatalogProduct | None:
    images = extract_images_from_payload(product)
    if not images:
        featured = product.get("featuredImage") or {}
        if featured.get("url"):
            images = [{"url": featured["url"], "caption": product.get("title", "")}]

    if not images:
        return None

    return CatalogProduct(
        title=str(product.get("title", "")),
        handle=str(product.get("handle", "")),
        image_url=images[0]["url"],
        price=_format_price(product),
        product_id=str(product.get("id", "")),
        all_images=images,
    )


def search_catalog_products(
    vehicle_brand_model: str = "",
    product_category: str = "koltuk_kilifi",
) -> list[CatalogProduct]:
    _, list_universal, search_by_vehicle = _load_shopify_client()

    if product_category == "universal_koltuk_kilifi":
        raw = list_universal(limit=40)
    else:
        raw = search_by_vehicle(
            vehicle_brand_model=vehicle_brand_model.strip(),
            product_category=product_category,
        )

    data = _parse_json(raw)
    products_raw = data.get("products", [])
    if not isinstance(products_raw, list):
        return []

    catalog: list[CatalogProduct] = []
    seen_titles: set[str] = set()
    for product in products_raw:
        if not isinstance(product, dict):
            continue
        item = _product_to_catalog(product)
        if not item or item.title in seen_titles:
            continue
        seen_titles.add(item.title)
        catalog.append(item)

    return catalog


def get_catalog_product_detail(product_title: str) -> CatalogProduct:
    get_product_detail, _, _ = _load_shopify_client()
    data = _parse_json(get_product_detail(product_title))
    item = _product_to_catalog(data)
    if not item:
        raise ValueError(f"Ürün görseli bulunamadı: {product_title}")
    return item


def shopify_configured() -> bool:
    return bool(
        os.getenv("OTOMSTORE_SHOPIFY_API_URL", "").strip()
        and os.getenv("OTOMSTORE_SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip()
    )
