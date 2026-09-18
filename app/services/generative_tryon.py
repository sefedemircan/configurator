"""Generatif try-on — OpenRouter Gemini Image."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.schemas.tryon import ProductReference, VehicleInfo
from app.services.material_hints import (
    is_taytuyu_material,
    material_texture_note,
    needs_insert_nap_pass,
    uses_recolor_preserve,
)
from app.utils.images import encode_image_data

logger = logging.getLogger(__name__)

FALLBACK_IMAGE_MODELS: tuple[str, ...] = ()

LAYER_ORDER = ("yan", "orta", "iplik")

SEAT_LABELS = {
    "front_driver": "driver seat (behind the steering wheel, left side in LHD cars)",
    "front_passenger": "front passenger seat (opposite the steering wheel, right side in LHD cars)",
    "rear_left": "rear left seat (left side of the rear row)",
    "rear_right": "rear right seat (right side of the rear row)",
    "rear_bench": "full rear bench seat (entire rear row as one continuous seat)",
}

LAYER_SPECS: dict[str, dict[str, str]] = {
    "yan": {
        "title": "YAN GÖVDE (side body / outer panels)",
        "body": (
            "Recolor ONLY the DARK / BLACK outer zones from the original seat model, on EVERY visible seat:\n"
            "- Raised side bolsters of the backrest (left and right wings)\n"
            "- Raised side bolsters of the SEAT CUSHION (sitting pad sides) — both driver AND passenger\n"
            "- Shoulder panels and the dark band at the TOP of the backrest, just under the headrest\n"
            "- Outer sides of the seat\n"
            "- Headrest outer wrap: sides, rear, and the dark frame around the center face\n"
            "Leave every LIGHT / CREAM / WHITE insert region untouched for ORTA KISIM.\n"
            "Copy YAN color and surface type from the fabric board. "
            "If the board has MACRO + SEAT DISTANCE panels, use SEAT DISTANCE grain density. "
            "Keep pebble/nappa micro-shadows — do not flatten to paint. "
            "Do NOT invent perforated leather unless the fabric reference clearly shows punched holes."
        ),
    },
    "orta": {
        "title": "ORTA KISIM (center insert / inner panels)",
        "body": (
            "Recolor ONLY the LIGHT / CREAM / WHITE insert zones from the original seat model, "
            "on EVERY visible seat including the background passenger seat:\n"
            "- Center face of the headrest (the inner rectangle framed by a dark border)\n"
            "- Center backrest insert: a vertical padded panel that starts several centimeters BELOW the headrest, "
            "with about 5–6 horizontal rib / channel stitch lines.\n"
            "- Center CUSHION insert (the sitting pad) — MUST be updated on driver AND passenger.\n"
            "Keep the insert outline, rib count, and 3D padding. Do not paint bolsters.\n"
            "Copy ORTA color and nap from the fabric board. "
            "If the board has MACRO + SEAT DISTANCE panels, use SEAT DISTANCE pile density. "
            "Keep fuzzy micro-shadows — not flat cream paint."
        ),
    },
    "iplik": {
        "title": "İPLİK (stitching thread color)",
        "body": (
            "Do not change fabric colors. Recolor only stitching to this thread on EVERY seat:\n"
            "- Contrast stitches on the outer bolsters and around panel seams\n"
            "- Outline stitches that separate the center insert from the bolsters\n"
            "- Horizontal rib stitches on the center insert\n"
            "Keep the original stitch PATHS and panel seams. No logos or extra embroidery."
        ),
    },
}

SEAT_MODEL_MAP = """
IMAGE 1 is the photo to edit. IMAGE 2 is the ORIGINAL unedited interior — the 3D MODEL / PANEL TEMPLATE.
Copy Image 2's seat SHAPES, seams, and zone boundaries exactly. Do not invent a new seat design.

This sport seat is TWO-TONE with sharp factory seams (light insert vs dark outer):

HEADREST
- Light center front face = ORTA KISIM
- Dark outer wrap / sides / rear / border frame around that center = YAN GÖVDE

BACKREST
- Dark left/right bolsters + dark TOP band under the headrest = YAN GÖVDE
- Light center insert = ORTA KISIM
- The light insert does NOT reach the headrest; a dark collar sits between them
- Horizontal ribs exist ONLY on that center insert (about 5–6 lines), not on the bolsters

CUSHION
- Dark wide outer bolsters = YAN GÖVDE
- Light center sitting pad with horizontal ribs = ORTA KISIM
- The boundary follows the physical U-shaped / rectangular seam of the original
- Driver and passenger cushions MUST use the same zone mapping — never leave one cushion original

FORBIDDEN
- Do not flood the whole seat with one material
- Do not erase the two-tone panel layout
- Do not smooth the insert into the bolsters
- Do not change seat geometry, camera, lighting, doors, wheel, console, or seatbelts
- Do not make the two front seats different from each other
""".strip()

IDENTITY_LOCK = """
PHOTO IDENTITY (keep the car, change the covers):
- Same camera angle, framing, and perspective as the original interior photo.
- Same vehicle cabin: dashboard, steering wheel, door cards, pillars, console, seatbelts, floor.
- Do NOT invent a different car or viewpoint.
- Catalog fabric images are MATERIAL / COLOR references only — never copy their camera or full-seat pose.
""".strip()

MATERIAL_MUST_CHANGE = """
MATERIAL CHANGE IS REQUIRED (hard success criteria):
- The original seats are typically black outer bolsters + cream/white center inserts.
- After editing, those zones MUST visibly show the selected YAN GÖVDE and ORTA KISIM colors/textures.
- Leaving the original black/white seat covers unchanged is a FAILURE.
- Stitching must pick up the selected İPLİK thread color where seams are visible.
- Keep seat SHAPES and panel boundaries; only recolor / retexture the upholstery.
- Flat painted plastic with no grain/nap is also a FAILURE.
""".strip()

TEXTURE_SCALE_LOCK = """
FABRIC SCALE (critical):
- Fabric boards may show TWO panels: MACRO (grain identity) and SEAT DISTANCE (correct density).
- Apply materials at SEAT DISTANCE scale. Never stamp the MACRO zoom onto the upholstery.
- Keep visible micro-texture: pebble crevices and/or suede nap. Flat recolor is wrong.
- Relight grain to the cabin. Ignore baked directional light in the swatch photo.
- Do not copy swatch borders, pinking, captions, or board labels onto the seats.
""".strip()


def _vehicle_note(vehicle_info: VehicleInfo | None) -> str:
    if vehicle_info and (vehicle_info.brand or vehicle_info.model):
        return f" Vehicle: {vehicle_info.brand} {vehicle_info.model}."
    return ""


def _preserve_note(other_seat_ids: list[str]) -> str:
    if other_seat_ids:
        others = ", ".join(SEAT_LABELS.get(s, s) for s in other_seat_ids)
        return f"Keep these seats exactly as in Image 1 (unchanged upholstery): {others}."
    return "Only modify the target seat; keep all other interior parts unchanged."


def _all_seats_note(seat_ids: list[str]) -> str:
    labels = ", ".join(SEAT_LABELS.get(s, s) for s in seat_ids)
    return (
        f"Apply this layer to EVERY listed seat identically, in one edit: {labels}. "
        "Backrest, cushion (sitting pad), bolsters, and headrest must match across seats. "
        "If a background seat's cushion still shows the original white/cream insert, the edit is wrong."
    )


def _build_prompt(
    seat_id: str,
    other_seat_ids: list[str],
    product_reference: ProductReference | None,
    vehicle_info: VehicleInfo | None,
    *,
    pass_label: str | None = None,
) -> str:
    product_name = product_reference.title if product_reference else "seat cover"
    target = SEAT_LABELS.get(seat_id, seat_id)
    pass_note = f"\nPass: {pass_label}." if pass_label else ""

    return f"""Edit this car interior photo for a virtual seat cover try-on preview.{pass_note}

{IDENTITY_LOCK}

Image 1: Customer's car interior photo (edit this image).
Image 2: Seat cover product reference — copy pattern, color, stitching, and texture from here ONLY (not camera angle).

Task: Apply the seat cover from Image 2 onto the {target} in Image 1.
Product: {product_name}.{_vehicle_note(vehicle_info)}

Coverage:
- Cover the seat backrest AND seat cushion; include headrest if visible.
- {_preserve_note(other_seat_ids)}

Rules:
- Preserve exact product pattern, colors, stitching, and material from Image 2
- Do NOT change steering wheel, dashboard, doors, windows, center console, or seatbelts
- Do NOT change camera angle or invent a different vehicle
- Match interior lighting and shadows naturally
- Photorealistic; no illustration style
- No watermarks or text overlays

Output one edited photo with the cover fitted only on the specified seat — SAME car, SAME angle."""


def _layer_image_index(present_layers: list[str], key: str) -> int:
    """Image 1 is the scene; layer refs start at 2."""
    return 2 + present_layers.index(key)


def _recolor_layer_block(
    key: str,
    image_idx: int,
    material_type: str | None,
    *,
    is_direct_swatch: bool,
) -> str:
    mat = (material_type or "").strip()
    preserve = uses_recolor_preserve(material_type, key)

    if key == "yan":
        if preserve:
            return (
                f"Görsel {image_idx} = YAN GÖVDE RENK KAYNAĞI"
                + (f" (malzeme: {mat})." if mat else ".")
                + "\n"
                "Sadece koltukların SİYAH / KOYU dış panellerini bu görseldeki renk tonuna çevir:\n"
                "- Sırtlık yan destekleri (sol/sağ), oturma yastığı yan destekleri, omuz bandı, başlık dış çerçevesi.\n"
                "Açık / krem / beyaz insert'lere dokunma (ORTA KISIM).\n"
                "Orijinal siyah derinin mikro dokusu (gözenek, tane, kıvrım, highlight) piksel düzeyinde KALSIN.\n"
                f"Görsel {image_idx} dokusunu koltuğa YAPIŞTIRMA — sadece RENGİ aktar. "
                "Zigzag kenar, dikiş, pano yazısı kopyalanmayacak.\n"
                "Boya kovası yok: ışık alan yerler hedefin açık tonu, gölge hedefin koyu tonu olsun.\n"
                "Delikli spor deri UYDURMA."
            )
        spec = LAYER_SPECS["yan"]["body"]
        extra = material_texture_note(mat, "yan", is_direct_swatch=is_direct_swatch)
        return (
            f"Görsel {image_idx} = YAN GÖVDE DESEN / YÜZEY KAYNAĞI"
            + (f" (malzeme: {mat})." if mat else ".")
            + f"\n{spec}"
            + (f"\n{extra}" if extra else "")
        )

    if key == "orta":
        if preserve:
            taytuyu = is_taytuyu_material(mat)
            nap = (
                f"Bu geçişte insert RENGİNİ Görsel {image_idx} kumaşının ortalama hue/doygunluğuna kilitle. "
                "Yeşil, zeytin, haki, sage kaydırma YASAK — ürün rengi budur. "
                "Sonraki geçişte görünür tay tüyü havı eklenecek (çok kısa keçe değil). "
                if taytuyu
                else "Sahnedeki kumaşın orijinal mikro dokusu (lif, gözenek, kırışık) piksel düzeyinde KALSIN. "
            )
            color_only = (
                f"Görsel {image_idx} dokusunu bu geçişte YAPIŞTIRMA — sadece RENGİ aktar. "
                if taytuyu
                else (
                    f"Görsel {image_idx} dokusunu YAPIŞTIRMA. Sadece RENGİ aktar. "
                )
            )
            return (
                f"Görsel {image_idx} = ORTA KISIM RENK VE DOKU KARAKTERİ KAYNAĞI"
                + (f" (malzeme: {mat})." if mat else ".")
                + "\n"
                "Bu görseli öncelikle 'hedef renk nasıl olmalı' için kullan.\n"
                "Sadece koltukların AÇIK (beyaz / krem / açık gri) panellerini bu tona çevir:\n"
                "- Tüm ön koltuk sırtlık ve oturma yüzeyi insert'leri.\n"
                "- Tüm başlıkların açık ön yüzü (şoför, yolcu, uzakta/camdan görünen arka başlıklar dahil). Hiçbir başlığı atlama.\n"
                "- Görünen tüm arka koltuk açık döşemeleri.\n"
                "Koyu yan desteklere dokunma (YAN GÖVDE).\n"
                f"{nap}"
                f"{color_only}"
                "Pembe/zigzag swatch kenarını koltuğa kopyalama.\n"
                "Aydınlatma ve koltuğun 3D hacmi korunsun; düz boya dolgusu olmasın.\n"
            )
        spec = LAYER_SPECS["orta"]["body"]
        extra = material_texture_note(mat, "orta", is_direct_swatch=is_direct_swatch)
        return (
            f"Görsel {image_idx} = ORTA KISIM DESEN / YÜZEY KAYNAĞI"
            + (f" (malzeme: {mat})." if mat else ".")
            + f"\n{spec}"
            + (f"\n{extra}" if extra else "")
        )

    return (
        f"Görsel {image_idx} = İPLİK RENK KAYNAĞI.\n"
        "Sadece GERÇEK dikiş ipliklerinin rengini bu görseldeki iplik rengine çevir.\n"
        "Dikiş = koltuk yüzeyindeki ince, düzenli, çizgisel tel dikişler "
        "(yan destek dikişleri, insert çevre dikişi, kapitone yatay hatlar).\n"
        "Kalınlık, konum, desen (düz / çift / kapitone) DEĞİŞMEYECEK — sadece renk.\n"
        "İpliğin parlaklık/gölge dokusu kalsın; düz boyalı çizgi olmasın.\n"
        "Rengi kumaşa TAŞIRMA. Emin değilsen o dikişe dokunma."
    )


def _build_combined_configurator_prompt(
    seat_ids: list[str],
    present_layers: list[str],
    product_reference: ProductReference | None,
    vehicle_info: VehicleInfo | None,
    layer_material_types: dict[str, str] | None = None,
    layer_is_direct_swatch: dict[str, bool] | None = None,
) -> str:
    product_name = product_reference.title if product_reference else "iki ton koltuk kılıfı"
    material_types = layer_material_types or {}
    swatch_flags = layer_is_direct_swatch or {}

    image_lines = [
        "- Görsel 1 = DÜZENLENECEK FOTOĞRAF. Çıktı bu karenin retüşlenmiş hali. "
        "Kadraj, açı, perspektif, ışık, gölge, arka plan aynı kalacak."
    ]
    layer_blocks: list[str] = []
    for key in present_layers:
        if key not in LAYER_SPECS:
            continue
        idx = _layer_image_index(present_layers, key)
        spec = LAYER_SPECS[key]
        preserve = uses_recolor_preserve(material_types.get(key), key)
        role = (
            "RENK KAYNAĞI (sadece renk; doku yapıştırılmaz)"
            if preserve
            else "DESEN / YÜZEY KAYNAĞI"
        )
        image_lines.append(f"- Görsel {idx}: {spec['title']} — {role}.")
        layer_blocks.append(
            _recolor_layer_block(
                key,
                idx,
                material_types.get(key),
                is_direct_swatch=bool(swatch_flags.get(key)),
            )
        )

    return f"""Sen profesyonel bir foto-gerçekçi görüntü düzenleme uzmanısın.
Bu bir YENİDEN ÇİZİM veya YENİDEN ÜRETİM görevi DEĞİLDİR; hassas retüş / renklendirme görevidir.
Orijinal fotoğrafın kendisi korunacak; yalnızca belirtilen koltuk bölgelerinin rengi değişecek.

Ürün: {product_name}.{_vehicle_note(vehicle_info)}
{_all_seats_note(seat_ids)}

GÖRSELLER
{chr(10).join(image_lines)}

PANEL HARİTASI (orijinal iki ton spor koltuk — sınırları uydurma):
- Açık insert (başlık ön yüzü, sırtlık orta panel ~5–6 yatay kanal, oturma yastığı orta) = ORTA KISIM
- Koyu yan destek / omuz / başlık çerçevesi = YAN GÖVDE
- Insert başlığa kadar uzanmaz; arada koyu yaka vardır
- Şoför ve yolcu aynı harita; bir yastığı orijinal bırakmak hata

YAPILACAK İŞLEMLER
{chr(10).join(layer_blocks)}

KESİNLİKLE DOKUNULMAYACAK
- Kapı iç panelleri ve kapı döşemeleri — açık olsalar bile ASLA değiştirme. Kapı koltuk değildir.
- Direksiyon, gösterge, vites, konsol, tavan, cam, ayna, emniyet kemeri, tutamak, plastik trim
- Camdan görünen dış dünya (ağaç, gökyüzü, yol, başka araç). Camı boyama / maskeleme.
- Gökyüzü veya ağaç bokeh'i olan açık alanlar koltuk DEĞİLDİR
- Araç gövdesi, kapı çerçevesi, A/B/C direği
- Kadraj, kırpma, en-boy oranı, döndürme, yansıtma

RENK DÖNÜŞÜMÜ
- Referanstaki tonu bölgenin ortalama / baseline rengi olarak uygula
- Orijinal pikselin göreli parlaklığı korunsun
- Bant, leke, poster, boya kovası efekti olmasın

DOKU
- Retüş katmanlarında referans dokusunu yapıştırma
- Sahnenin kendi mikro dokusu, dikiş yolları, panel birleşimleri aynı yerde kalsın
- Netlik aynı kalsın; bulanıklaştırma, yeniden örnekleme, HDR, ekstra grain YOK
- Çizim / illüstrasyon / 3D render görünümüne kayma

ÇIKTI ÖNCESİ KONTROL
- Tüm görünür koltuk başlıklarının açık yüzü değişti mi?
- Tüm ön ve arka açık insert'ler değişti mi? Kapıya dokunulmadı mı?
- YAN koyu bölgeler yeni YAN rengine döndü mü, yoksa hâlâ orijinal siyah / hâlâ tüm koltuk tek renk mi?
- Camdaki gökyüzü/ağaç yanlışlıkla boyanmadı mı?
- ORTA rengi referans kumaşın tonunda mı, yoksa yeşil/olive'e kaydı mı?
- Dikiş rengi kumaşa taşmadı mı?
- Doku, kıvrım, gölge, çözünürlük orijinal gibi mi?
Biri hayırsa çıktı vermeden düzelt.

ÖZET: Görsel 1'i al, sadece koltuk YAN / ORTA / İPLİK bölgelerini belirtilen referanslara göre retüşle, dokuyu ve kabini koru, kapıya ve cama dokunma."""


def _build_grain_refine_prompt() -> str:
    return """Surgical SURFACE GRAIN refine only.

Image 1: Interior with new seat covers already applied — EDIT THIS.
Following images are fabric scale boards (MACRO + SEAT DISTANCE) and/or fabric references.

Task: Strengthen upholstery micro-texture so YAN and ORTA match the SEAT DISTANCE panels.
- Do NOT change colors, two-tone panel layout, stitch paths, camera, or cabin.
- Do NOT revert seats to the original black/white covers.
- Do NOT stamp MACRO zoom (elephant skin) and do NOT flatten to painted plastic.
- Relight grain to the existing cabin light; keep crevice / nap micro-shadows.
- Do not add perforations, logos, or text.
- Leave already-masked windows as they are.

Output the same photo with richer fabric grain only."""


def _build_orta_nap_prompt(*, taytuyu: bool) -> str:
    if taytuyu:
        character = (
            "TAY TÜYÜ = orta-kısa, net GÖRÜNÜR hav (önceki iyi uzunluk). "
            "Hav eklemek RENGİ değiştirmez."
        )
        goal = "Sadece AÇIK insert'lere tay tüyü havı işle. Hue/doygunluk/açıklık AYNI kalsın."
        target = """HEDEF (tay tüyü):
- Orta-kısa sık hav: koltuk mesafesinde tüy net okunur
- Yönlü nap / yumuşak pooling SERBEST
- Kürk, peluş, ayrı uzun kıl yok; düz keçe de yok
- RENK: Görsel 1'deki insert tonunu AYNEN koru — Görsel 2'den renk alma"""
        fail = """HARD FAIL:
- Düz keçe / düz boya (tüy yok)
- Hayvan tüyü, sahte kürk, peluş, şönil
- RENK KAYMASI: sıcak kahve, deve tüyü, tan, camel, yeşil, zeytin, sage
- Deri parıltısı / gözenek"""
        out = "Çıktı: aynı fotoğraf, ORTA insert Görsel 1 renginde + orta-kısa görünür tay tüyü."
    else:
        character = "Kısa havlı kumaş; uzun peluş veya deri DEĞİL. Hav görünür olsun. Renk değişmesin."
        goal = "Sadece AÇIK insert'lere kısa havlı kumaş yüzeyi işle; rengi değiştirme."
        target = "HEDEF: kısa, sık, görünür hav; mat. Görsel 1 insert rengi kilit."
        fail = "HARD FAIL: düz boya, uzun tüy, kürk, deri parıltısı, renk kayması."
        out = "Çıktı: aynı fotoğraf, yalnızca ORTA insert'te kısa görünür hav; aynı renk."
    return f"""Cerrahi ORTA KISIM doku geçişi. Yeniden çizim değil.

Görsel 1: YAN + ORTA rengi zaten uygulanmış araç içi — BUNU DÜZENLE. Insert rengi DOĞRU.
Görsel 2: sadece tüy/hav karakteri. Zigzag kenarı yok say. Makro ölçeği ve makro RENGİNİ koltuğa taşıma.

Görev: {goal}
{character}

KİLİT (bozulursa hata):
- Insert rengi = Görsel 1 insert'i (yeniden boyama YOK)
- YAN GÖVDE, kadraj, cam, kapı, dikiş YOLLARI, kanal sayısı aynı kalsın

{target}

{fail}

{out}"""


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


def _ordered_layer_urls(layer_data_urls: dict[str, str] | None) -> list[tuple[str, str]]:
    if not layer_data_urls:
        return []
    ordered: list[tuple[str, str]] = []
    for key in LAYER_ORDER:
        url = layer_data_urls.get(key)
        if url:
            ordered.append((key, url))
    return ordered


async def _call_image_model(
    client: httpx.AsyncClient,
    headers: dict,
    model: str,
    scene_data_url: str,
    reference_data_urls: list[str],
    prompt: str,
    aspect_ratio: str = "4:3",
    panel_map_data_url: str | None = None,
) -> str | None:
    content: list[dict] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": scene_data_url}},
    ]
    if panel_map_data_url:
        content.append({"type": "image_url", "image_url": {"url": panel_map_data_url}})
    for url in reference_data_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": aspect_ratio},
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
    reference_data_urls: list[str],
    prompt: str,
    aspect_ratio: str = "4:3",
    panel_map_data_url: str | None = None,
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
                    client,
                    headers,
                    model,
                    scene_data_url,
                    reference_data_urls,
                    prompt,
                    aspect_ratio=aspect_ratio,
                    panel_map_data_url=panel_map_data_url,
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
    reference_data_urls: list[str],
    seat_id: str,
    all_seat_ids: list[str],
    product_reference: ProductReference | None,
    vehicle_info: VehicleInfo | None,
    *,
    pass_label: str | None = None,
    aspect_ratio: str = "4:3",
) -> tuple[str, list[str]]:
    other_seats = [s for s in all_seat_ids if s != seat_id]
    prompt = _build_prompt(
        seat_id,
        other_seats,
        product_reference,
        vehicle_info,
        pass_label=pass_label,
    )
    return await _generate_with_models(
        scene_data_url,
        reference_data_urls,
        prompt,
        aspect_ratio=aspect_ratio,
    )


def _layer_reference_url(
    key: str,
    layer_data_urls: dict[str, str],
    swatch_urls: dict[str, str],
    material_types: dict[str, str],
) -> str | None:
    """Recolor-preserve layers use the raw swatch photo (color only), not the scale board."""
    if key in {"yan", "orta"} and uses_recolor_preserve(material_types.get(key), key):
        return layer_data_urls.get(key) or swatch_urls.get(key)
    return swatch_urls.get(key) or layer_data_urls.get(key)


async def _apply_configurator_layers(
    scene_data_url: str,
    visible_seat_ids: list[str],
    present_layers: list[str],
    layer_data_urls: dict[str, str],
    product_reference: ProductReference | None,
    vehicle_info: VehicleInfo | None,
    aspect_ratio: str,
    layer_material_types: dict[str, str] | None = None,
    layer_swatch_urls: dict[str, str] | None = None,
    layer_is_direct_swatch: dict[str, bool] | None = None,
) -> tuple[str, list[str]]:
    """Single retouch pass: recolor mapped seat zones, keep photo micro-texture."""
    warnings: list[str] = []
    swatch_urls = layer_swatch_urls or {}
    material_types = layer_material_types or {}

    refs: list[str] = []
    fabric_refs: list[str] = []
    all_preserve = True
    for key in present_layers:
        url = _layer_reference_url(key, layer_data_urls, swatch_urls, material_types)
        if url:
            refs.append(url)
            if key in {"yan", "orta"}:
                fabric_refs.append(url)
                if not uses_recolor_preserve(material_types.get(key), key):
                    all_preserve = False

    if not refs:
        raise ValueError("Configurator katman referansları boş.")

    prompt = _build_combined_configurator_prompt(
        visible_seat_ids,
        present_layers,
        product_reference,
        vehicle_info,
        layer_material_types=layer_material_types,
        layer_is_direct_swatch=layer_is_direct_swatch,
    )
    scene_url, step_warnings = await _generate_with_models(
        scene_data_url,
        refs,
        prompt,
        aspect_ratio=aspect_ratio,
    )
    warnings.extend(step_warnings)
    warnings.append("Retüş geçişi: YAN renk korundu; ORTA renk oturtuldu (cam kapatılmadı).")

    orta_mat = material_types.get("orta")
    orta_url = (
        _layer_reference_url("orta", layer_data_urls, swatch_urls, material_types)
        if "orta" in present_layers
        else None
    )
    if orta_url and needs_insert_nap_pass(orta_mat, "orta"):
        try:
            nap_url, nap_warnings = await _generate_with_models(
                scene_url,
                [orta_url],
                _build_orta_nap_prompt(taytuyu=is_taytuyu_material(orta_mat)),
                aspect_ratio=aspect_ratio,
            )
            warnings.extend(nap_warnings)
            if nap_url:
                scene_url = nap_url
                warnings.append(
                    "ORTA nap geçişi: kısa görünür tay tüyü havı insert'e işlendi; YAN kilitli."
                )
            else:
                warnings.append("ORTA nap geçişi görüntü döndürmedi; renk geçişi kullanıldı.")
        except Exception as exc:
            logger.warning("ORTA nap pass skipped: %s", exc)
            warnings.append(f"ORTA nap geçişi atlandı: {exc}")
    elif fabric_refs and not all_preserve:
        try:
            refined_url, refine_warnings = await _generate_with_models(
                scene_url,
                fabric_refs,
                _build_grain_refine_prompt(),
                aspect_ratio=aspect_ratio,
            )
            warnings.extend(refine_warnings)
            if refined_url:
                scene_url = refined_url
                warnings.append("Desenli katman için tane geçişi uygulandı.")
            else:
                warnings.append("Tane güçlendirme görüntü döndürmedi; ilk geçiş kullanıldı.")
        except Exception as exc:
            logger.warning("Grain refine skipped: %s", exc)
            warnings.append(f"Tane güçlendirme atlandı: {exc}")

    return scene_url, warnings


async def run_generative_tryon(
    scene_data_url: str,
    product_data_url: str,
    visible_seat_ids: list[str],
    product_reference: ProductReference | None = None,
    vehicle_info: VehicleInfo | None = None,
    layer_data_urls: dict[str, str] | None = None,
    layer_swatch_urls: dict[str, str] | None = None,
    layer_material_types: dict[str, str] | None = None,
    layer_is_direct_swatch: dict[str, bool] | None = None,
    aspect_ratio: str = "4:3",
) -> tuple[str, float, list[str]]:
    """Görünür koltuklara kılıf uygular."""
    if not visible_seat_ids:
        raise ValueError("Uygulanacak görünür koltuk bulunamadı.")

    ordered_layers = _ordered_layer_urls(layer_data_urls)
    present_layers = [key for key, _ in ordered_layers]
    reference_data_urls = [url for _, url in ordered_layers] or [product_data_url]

    warnings: list[str] = []
    total = len(visible_seat_ids)

    if present_layers:
        warnings.append(
            f"{total} görünür koltuk: YAN retüş + ORTA renk, gerekirse ayrı nap geçişi."
        )
        scene_url, step_warnings = await _apply_configurator_layers(
            scene_data_url,
            visible_seat_ids,
            present_layers,
            layer_data_urls or {},
            product_reference,
            vehicle_info,
            aspect_ratio,
            layer_material_types=layer_material_types,
            layer_swatch_urls=layer_swatch_urls,
            layer_is_direct_swatch=layer_is_direct_swatch,
        )
        warnings.extend(step_warnings)
    else:
        warnings.append(f"{total} görünür koltuğa sırayla uygulanıyor.")
        scene_url = scene_data_url
        for index, seat_id in enumerate(visible_seat_ids, start=1):
            scene_url, step_warnings = await _apply_single_seat(
                scene_url,
                reference_data_urls,
                seat_id,
                visible_seat_ids,
                product_reference,
                vehicle_info,
                pass_label=f"{index}/{total} {seat_id}",
                aspect_ratio=aspect_ratio,
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
