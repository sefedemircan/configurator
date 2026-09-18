"""
Otom Virtual Try-On — sabit sahne + YAN GÖVDE / ORTA KISIM / İPLİK kombinasyonu.

Çalıştırma:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from dotenv import load_dotenv
from PIL import Image

from app.config import get_settings
from app.schemas.tryon import ProductLayers, ProductReference, TryOnCompositeRequest
from app.services.pipeline import run_tryon_pipeline
from app.utils.images import encode_image_data

load_dotenv()

DATA_DIR = ROOT / "data"
SCENE_PATH = ROOT / "_DSF9666.JPG"
SCENE_MAX_SIDE = 1600
SWATCH_CATALOG_PATH = DATA_DIR / "test_swatches.json"
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_SKIP_DATA_FILES = {"koltuk_bilgileri.json", "iplik_bilgileri.json", "test_swatches.json"}


def _swatch_item(path: Path, *, kod: str, tur_adi: str, tipi: str, grup: str) -> dict:
    return {
        "URUN_KODU": kod,
        "TUR_ADI": tur_adi,
        "TİPİ": tipi,
        "KOLTUK": "TEST SWATCH",
        "GRUP": grup,
        "GORSEL_URL": str(path.resolve()),
        "is_fabric_swatch": True,
    }


def _fabric_sample_items() -> tuple[list[dict], list[dict]]:
    """Local close-up fabric photos for texture-quality testing."""
    yan: list[dict] = []
    orta: list[dict] = []
    used: set[str] = set()

    if SWATCH_CATALOG_PATH.exists():
        for spec in json.loads(SWATCH_CATALOG_PATH.read_text(encoding="utf-8")):
            filename = str(spec.get("file") or "").strip()
            path = DATA_DIR / filename
            if not filename or not path.exists():
                continue
            used.add(path.name.lower())
            item = _swatch_item(
                path,
                kod=str(spec.get("kod") or path.stem),
                tur_adi=str(spec.get("tur_adi") or path.stem),
                tipi=str(spec.get("tipi") or "SWATCH"),
                grup=str(spec.get("grup") or "ORTA KISIM"),
            )
            if item["GRUP"] == "YAN GÖVDE":
                yan.append(item)
            else:
                orta.append(item)

    for path in sorted(DATA_DIR.iterdir(), key=lambda p: p.name.lower()):
        if path.suffix.lower() not in _IMAGE_EXTS:
            continue
        if path.name in _SKIP_DATA_FILES or path.name.lower() in used:
            continue
        item = _swatch_item(
            path,
            kod=f"SAMPLE {path.stem}",
            tur_adi=path.stem,
            tipi="SWATCH",
            grup="ORTA KISIM",
        )
        orta.append(item)
        yan.append(
            {**item, "GRUP": "YAN GÖVDE", "TİPİ": "DÜZ DERİ"}
        )

    return yan, orta


st.set_page_config(
    page_title="Otom Koltuk Configurator",
    page_icon="🚗",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
    .block-container {
        padding-top: 1.25rem;
        padding-bottom: 2rem;
        max-width: 920px;
    }
    [data-testid="stSidebar"] { display: none; }
    [data-testid="collapsedControl"] { display: none; }
    .stButton > button {
        min-height: 3rem;
        font-size: 1.05rem;
        border-radius: 12px;
    }
    .stDownloadButton > button {
        min-height: 2.75rem;
        border-radius: 12px;
    }
    [data-testid="stSelectbox"] > div { border-radius: 12px; }
    h1 { font-size: 1.7rem !important; margin-bottom: 0.25rem !important; }
    img { border-radius: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def _load_json(path_str: str) -> list[dict]:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


@st.cache_data
def _load_scene_bytes(path_str: str) -> bytes:
    return Path(path_str).read_bytes()


def _seat_label(item: dict) -> str:
    code = str(item.get("URUN_KODU") or "").strip()
    name = str(item.get("TUR_ADI") or "").strip()
    material = str(item.get("TİPİ") or "").strip()
    design = str(item.get("KOLTUK") or "").strip()
    head = " — ".join(part for part in (code, name) if part)
    tail = " | ".join(part for part in (material, design) if part)
    return f"{head} | {tail}" if tail else head


def _thread_label(item: dict) -> str:
    code = str(item.get("iplik_kodu") or "").strip()
    color = str(item.get("iplik_rengi") or "").strip()
    return " — ".join(part for part in (code, color) if part) or "İplik"


def _filter_group(items: list[dict], group: str) -> list[dict]:
    return [
        item
        for item in items
        if item.get("GRUP") == group and str(item.get("GORSEL_URL") or "").strip()
    ]


def _downscale(image: Image.Image, max_side: int = SCENE_MAX_SIDE) -> Image.Image:
    image = image.convert("RGBA")
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.LANCZOS,
    )


def _run_pipeline(request: TryOnCompositeRequest):
    return asyncio.run(run_tryon_pipeline(request))


def _select_item(label: str, items: list[dict], key: str) -> dict:
    index = st.selectbox(
        label,
        options=range(len(items)),
        format_func=lambda i, _items=items: _seat_label(_items[i]),
        key=key,
    )
    return items[index]


def _preview_url(url: str, caption: str) -> None:
    if not url:
        st.caption("Görsel URL yok")
        return
    path = Path(url)
    if path.exists() and path.is_file():
        st.image(str(path), caption=caption, use_container_width=True)
    else:
        st.image(url, caption=caption, use_container_width=True)


def main() -> None:
    st.title("Otom Koltuk Configurator")
    st.caption(
        "Sabit araç görseline JSON’daki YAN GÖVDE, ORTA KISIM ve İPLİK "
        "görsel_url referanslarını giydirin."
    )

    get_settings.cache_clear()
    if not get_settings().openrouter_api_key:
        st.error(
            "OPENROUTER_API_KEY tanımlı değil. Streamlit Cloud’da "
            "App settings → Secrets içine ekleyin."
        )
        st.code('OPENROUTER_API_KEY = "sk-or-..."', language="toml")
        return

    if not SCENE_PATH.exists():
        st.error(f"Sabit sahne görseli bulunamadı: {SCENE_PATH.name}")
        return

    scene_bytes = _load_scene_bytes(str(SCENE_PATH))
    scene_image = _downscale(Image.open(io.BytesIO(scene_bytes)))
    st.image(scene_image, caption="Sabit sahne — _DSF9666.JPG", use_container_width=True)

    st.markdown(
        """
        Giydirme, orijinal fotoğrafın **retüşü**dür (yeniden çizim değil):
        - **YAN** — sahnedeki deri tane korunur, swatch yalnızca renk
        - **ORTA taytüyü** — renk sonra ayrı nap geçişi (damar/hav swatch’tan)
        - **İPLİK** — sadece dikiş hattı rengi
        - Cam ve kapı panellerine dokunulmaz
        """
    )

    try:
        koltuk_items = _load_json(str(DATA_DIR / "koltuk_bilgileri.json"))
        iplik_items = [
            item
            for item in _load_json(str(DATA_DIR / "iplik_bilgileri.json"))
            if str(item.get("gorsel_url") or "").strip()
        ]
    except Exception as exc:
        st.error(f"JSON okunamadı: {exc}")
        return

    yan_items = _fabric_sample_items()[0] + _filter_group(koltuk_items, "YAN GÖVDE")
    orta_items = _fabric_sample_items()[1] + _filter_group(koltuk_items, "ORTA KISIM")

    if not yan_items or not orta_items or not iplik_items:
        st.error("YAN GÖVDE, ORTA KISIM veya İPLİK seçenekleri JSON’da bulunamadı.")
        return

    st.info(
        "Test swatch’ları listelerin başında: **YAN** pebble deri, **ORTA** taytüyü/süet. "
        "Yeni `data/` fotoğrafları da otomatik düşer."
    )

    st.subheader("Kombinasyon")
    col_yan, col_orta, col_iplik = st.columns(3)

    with col_yan:
        yan = _select_item("YAN GÖVDE", yan_items, "yan")
        _preview_url(str(yan.get("GORSEL_URL") or ""), _seat_label(yan))

    with col_orta:
        orta = _select_item("ORTA KISIM", orta_items, "orta")
        _preview_url(str(orta.get("GORSEL_URL") or ""), _seat_label(orta))

    with col_iplik:
        iplik_index = st.selectbox(
            "İPLİK",
            options=range(len(iplik_items)),
            format_func=lambda i: _thread_label(iplik_items[i]),
            key="iplik",
        )
        iplik = iplik_items[iplik_index]
        _preview_url(str(iplik.get("gorsel_url") or ""), _thread_label(iplik))

    yan_url = str(yan.get("GORSEL_URL") or "").strip()
    orta_url = str(orta.get("GORSEL_URL") or "").strip()
    iplik_url = str(iplik.get("gorsel_url") or "").strip()
    can_run = bool(yan_url and orta_url and iplik_url)

    st.divider()
    if st.button("Oluştur", type="primary", disabled=not can_run, use_container_width=True):
        combo_title = (
            f"YAN GÖVDE: {_seat_label(yan)} | "
            f"ORTA KISIM: {_seat_label(orta)} | "
            f"İPLİK: {_thread_label(iplik)}"
        )
        layers = ProductLayers(yan=yan_url, orta=orta_url, iplik=iplik_url)
        request = TryOnCompositeRequest(
            scene_image=encode_image_data(scene_image),
            product_layers=layers,
            product_reference=ProductReference(
                title=combo_title,
                handle="configurator-combo",
                image_url=yan_url if yan_url.startswith("http") else "local-yan-sample",
                product_category="universal_koltuk_kilifi",
            ),
            layer_material_types={
                "yan": str(yan.get("TİPİ") or "").strip(),
                "orta": str(orta.get("TİPİ") or "").strip(),
            },
            layer_is_direct_swatch={
                "yan": bool(yan.get("is_fabric_swatch")),
                "orta": bool(orta.get("is_fabric_swatch")),
            },
            seat_target="auto",
        )

        with st.spinner("Kılıf giydiriliyor (orijinal panel modeli korunarak)..."):
            get_settings.cache_clear()
            try:
                result = _run_pipeline(request)
            except Exception as exc:
                st.error(f"Pipeline hatası: {exc}")
                return

        st.session_state["last_result"] = {
            "title": combo_title,
            "confidence": result.placement_confidence,
            "warnings": result.warnings,
            "image": result.result_image,
        }

    last = st.session_state.get("last_result")
    if not last:
        return

    st.caption(last["title"])
    st.success(f"Tamamlandı — güven: {last['confidence']:.0%}")
    for warning in last["warnings"]:
        st.warning(warning)

    result_img = Image.open(
        io.BytesIO(base64.b64decode(last["image"].split(",", 1)[-1]))
    )

    before, after = st.columns(2)
    with before:
        st.markdown("**Orijinal**")
        st.image(scene_image, use_container_width=True)
    with after:
        st.markdown("**Sonuç**")
        st.image(result_img, use_container_width=True)

    buf = io.BytesIO()
    result_img.convert("RGB").save(buf, format="JPEG", quality=90)
    st.download_button(
        "Sonucu indir",
        data=buf.getvalue(),
        file_name="otom-configurator-result.jpg",
        mime="image/jpeg",
        use_container_width=True,
    )


if __name__ == "__main__":
    main()
