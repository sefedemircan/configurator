"""
Otom Virtual Try-On — sade, mobil uyumlu Streamlit arayüzü.

Çalıştırma:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from dotenv import load_dotenv
from PIL import Image

from app.config import get_settings
from app.integrations.otomai_shopify import (
    CatalogProduct,
    search_catalog_products,
    shopify_configured,
)
from app.schemas.tryon import ProductLayers, ProductReference, TryOnCompositeRequest
from app.services.pipeline import run_tryon_pipeline
from app.utils.images import encode_image_data

load_dotenv()

st.set_page_config(
    page_title="Otom Virtual Try-On",
    page_icon="🚗",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    /* Mobile-first spacing */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        padding-left: 1rem;
        padding-right: 1rem;
        max-width: 480px;
    }
    [data-testid="stSidebar"] { display: none; }
    [data-testid="collapsedControl"] { display: none; }
    /* Larger tap targets */
    .stButton > button {
        min-height: 3rem;
        font-size: 1.05rem;
        border-radius: 12px;
    }
    .stDownloadButton > button {
        min-height: 2.75rem;
        border-radius: 12px;
    }
    /* File uploader & select feel larger on phone */
    [data-testid="stFileUploader"] section,
    [data-testid="stSelectbox"] > div {
        border-radius: 12px;
    }
    h1 { font-size: 1.6rem !important; margin-bottom: 0.25rem !important; }
    .stCaption, [data-testid="stCaptionContainer"] {
        font-size: 0.95rem !important;
    }
    img { border-radius: 12px; }
    @media (min-width: 640px) {
        .block-container { max-width: 560px; padding-top: 1.5rem; }
        h1 { font-size: 1.9rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def pil_to_data_url(image: Image.Image, fmt: str = "JPEG") -> str:
    return encode_image_data(image.convert("RGBA"), fmt=fmt)


def run_pipeline(request: TryOnCompositeRequest):
    return asyncio.run(run_tryon_pipeline(request))


def _init_session_state() -> None:
    defaults = {
        "catalog_products": [],
        "selected_product": None,
        "selected_image_url": None,
        "product_reference": None,
        "catalog_loaded": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _ensure_catalog() -> list[CatalogProduct]:
    if st.session_state.catalog_loaded and st.session_state.catalog_products:
        return st.session_state.catalog_products

    with st.spinner("Ürünler yükleniyor..."):
        products = search_catalog_products(
            vehicle_brand_model="",
            product_category="universal_koltuk_kilifi",
        )
    st.session_state.catalog_products = products
    st.session_state.catalog_loaded = True
    return products


def _render_product_picker() -> ProductLayers | None:
    if not shopify_configured():
        st.error(
            "Shopify yapılandırması eksik. `.env` dosyasına "
            "`OTOMSTORE_SHOPIFY_API_URL` ve `OTOMSTORE_SHOPIFY_ADMIN_ACCESS_TOKEN` ekleyin."
        )
        return None

    try:
        products = _ensure_catalog()
    except Exception as exc:
        st.error(f"Katalog hatası: {exc}")
        return None

    if not products:
        st.warning("Ürün bulunamadı.")
        return None

    product_labels = [f"{p.title} — {p.price}" for p in products]
    selected_index = st.selectbox(
        "Ürün / renk seçin",
        options=range(len(products)),
        format_func=lambda i: product_labels[i],
    )
    selected: CatalogProduct = products[selected_index]
    selection_key = selected.selection_key or selected.title

    if st.session_state.selected_product != selection_key:
        # Variant satırları katalog yüklenirken detaydan açıldığı için
        # tekrar detail çekip ilk galeri görseline düşürmüyoruz.
        st.session_state.selected_product = selection_key
        st.session_state.selected_image_url = selected.image_url

    chosen_image = st.session_state.selected_image_url or selected.image_url
    caption = selected.title
    if selected.color and selected.color not in caption:
        caption = f"{selected.product_title or selected.title} — {selected.color}"
    st.image(chosen_image, caption=caption, use_container_width=True)

    layers = ProductLayers(base=chosen_image)
    st.session_state.product_reference = ProductReference(
        title=selected.product_title or selected.title,
        handle=selected.handle,
        image_url=chosen_image,
        shopify_id=selected.variant_id or selected.product_id,
        product_category="universal_koltuk_kilifi",
    )
    return layers


def main() -> None:
    _init_session_state()

    st.title("Otom Virtual Try-On")
    st.caption("Fotoğraf yükleyin, ürün seçin, aracınızda görün.")

    scene_file = st.file_uploader(
        "Araç içi fotoğraf",
        type=["jpg", "jpeg", "png", "webp"],
        key="scene",
        help="Galeriden seçin veya fotoğraf çekin.",
    )

    scene_image: Image.Image | None = None
    if scene_file:
        scene_image = Image.open(scene_file).convert("RGBA")
        st.image(scene_image, use_container_width=True)

    st.subheader("Ürün")
    product_layers = _render_product_picker()

    has_product = bool(product_layers and product_layers.base)
    can_run = scene_image is not None and has_product

    st.divider()

    if st.button("Aracımda Gör", type="primary", disabled=not can_run, use_container_width=True):
        if not scene_image or not product_layers:
            st.error("Fotoğraf ve ürün gerekli.")
            return

        request = TryOnCompositeRequest(
            scene_image=pil_to_data_url(scene_image),
            product_layers=product_layers,
            product_reference=st.session_state.get("product_reference"),
            seat_target="auto",
        )

        with st.spinner("Try-on çalışıyor..."):
            get_settings.cache_clear()
            try:
                result = run_pipeline(request)
            except Exception as exc:
                st.error(f"Pipeline hatası: {exc}")
                return

        if result.product_reference:
            st.caption(result.product_reference.title)

        st.success(f"Tamamlandı — güven: {result.placement_confidence:.0%}")

        for warning in result.warnings:
            st.warning(warning)

        result_img = Image.open(
            io.BytesIO(base64.b64decode(result.result_image.split(",", 1)[-1]))
        )

        # Single-column stack — better on phones than side-by-side
        st.markdown("**Orijinal**")
        st.image(scene_image, use_container_width=True)
        st.markdown("**Sonuç**")
        st.image(result_img, use_container_width=True)

        buf = io.BytesIO()
        result_img.convert("RGB").save(buf, format="JPEG", quality=90)
        st.download_button(
            "Sonucu indir",
            data=buf.getvalue(),
            file_name="otom-tryon-result.jpg",
            mime="image/jpeg",
            use_container_width=True,
        )


if __name__ == "__main__":
    main()
