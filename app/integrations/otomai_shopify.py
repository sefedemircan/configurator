from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
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
    product_title: str = ""
    variant_id: str = ""
    variant_title: str = ""
    color: str = ""
    selection_key: str = ""


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

    for variant in data.get("variant_summary") or data.get("variants") or []:
        if isinstance(variant, dict):
            add(
                variant.get("image_url", "") or (variant.get("image") or {}).get("url", ""),
                variant.get("color") or variant.get("title") or data.get("title", ""),
            )

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


def _format_variant_price(amount: Any, currency: str = "TRY") -> str:
    if amount is None:
        return "—"
    try:
        value = float(amount)
        return f"{value:,.0f} {currency}".replace(",", ".")
    except (TypeError, ValueError):
        return str(amount)


def _selection_key(product_id: str, variant_id: str = "", image_url: str = "") -> str:
    return f"{product_id}|{variant_id}|{image_url}"


def _product_to_catalog(product: dict[str, Any]) -> CatalogProduct | None:
    images = extract_images_from_payload(product)
    if not images:
        featured = product.get("featuredImage") or {}
        if featured.get("url"):
            images = [{"url": featured["url"], "caption": product.get("title", "")}]

    if not images:
        return None

    product_title = str(product.get("title", ""))
    product_id = str(product.get("id", ""))
    image_url = images[0]["url"]
    return CatalogProduct(
        title=product_title,
        handle=str(product.get("handle", "")),
        image_url=image_url,
        price=_format_price(product),
        product_id=product_id,
        all_images=images,
        product_title=product_title,
        selection_key=_selection_key(product_id, image_url=image_url),
    )


def _expand_product_variants(product: dict[str, Any]) -> list[CatalogProduct]:
    """Ürünü renk/variant bazında ayrı seçilebilir satırlara açar."""
    product_title = str(product.get("title", "")).strip()
    handle = str(product.get("handle", ""))
    product_id = str(product.get("id", ""))
    featured = (product.get("featuredImage") or {}).get("url") or ""
    currency = (
        product.get("priceRangeV2", {})
        .get("minVariantPrice", {})
        .get("currencyCode", "TRY")
    )
    gallery = extract_images_from_payload(product)
    fallback_image = featured or (gallery[0]["url"] if gallery else "")

    variants = product.get("variant_summary") or product.get("variants") or []
    if not isinstance(variants, list) or not variants:
        base = _product_to_catalog(product)
        return [base] if base else []

    usable_variants = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and variant.get("available_for_sale", True)
    ]
    if not usable_variants:
        usable_variants = [v for v in variants if isinstance(v, dict)]

    # Tek "Default Title" variant ise ürün seviyesinde tut.
    if len(usable_variants) == 1:
        only = usable_variants[0]
        only_title = str(only.get("title") or "").strip().casefold()
        if only_title in {"", "default title"}:
            base = _product_to_catalog(product)
            return [base] if base else []

    expanded: list[CatalogProduct] = []
    for variant in usable_variants:
        color = str(variant.get("color") or variant.get("title") or "").strip()
        variant_title = str(variant.get("title") or color).strip()
        variant_id = str(variant.get("id") or "")
        image_url = str(variant.get("image_url") or "").strip() or fallback_image
        if not image_url:
            continue

        label = product_title
        if color and color.casefold() not in product_title.casefold():
            label = f"{product_title} — {color}"

        expanded.append(
            CatalogProduct(
                title=label,
                handle=handle,
                image_url=image_url,
                price=_format_variant_price(variant.get("price"), currency),
                product_id=product_id,
                all_images=[{"url": image_url, "caption": color or label}, *gallery],
                product_title=product_title,
                variant_id=variant_id,
                variant_title=variant_title,
                color=color,
                selection_key=_selection_key(product_id, variant_id, image_url),
            )
        )

    if expanded:
        return expanded

    base = _product_to_catalog(product)
    return [base] if base else []


def search_catalog_products(
    vehicle_brand_model: str = "",
    product_category: str = "koltuk_kilifi",
) -> list[CatalogProduct]:
    get_product_detail, list_universal, search_by_vehicle = _load_shopify_client()

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
    seen_keys: set[str] = set()
    seen_product_titles: set[str] = set()

    for product in products_raw:
        if not isinstance(product, dict):
            continue

        title = str(product.get("title", "")).strip()
        if not title or title in seen_product_titles:
            continue
        seen_product_titles.add(title)

        try:
            detailed = _parse_json(get_product_detail(title))
        except Exception:
            detailed = product

        if detailed.get("message") and not detailed.get("title"):
            detailed = product

        for item in _expand_product_variants(detailed):
            if item.selection_key in seen_keys:
                continue
            seen_keys.add(item.selection_key)
            catalog.append(item)

    return catalog


def get_catalog_product_detail(product_title: str) -> CatalogProduct:
    get_product_detail, _, _ = _load_shopify_client()
    data = _parse_json(get_product_detail(product_title))
    expanded = _expand_product_variants(data)
    if not expanded:
        raise ValueError(f"Ürün görseli bulunamadı: {product_title}")
    return expanded[0]


def shopify_configured() -> bool:
    return bool(
        os.getenv("OTOMSTORE_SHOPIFY_API_URL", "").strip()
        and os.getenv("OTOMSTORE_SHOPIFY_ADMIN_ACCESS_TOKEN", "").strip()
    )
