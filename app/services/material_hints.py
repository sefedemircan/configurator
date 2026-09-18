"""Kumaş tipi (TİPİ) → generatif prompt ipuçları."""

from __future__ import annotations

MATERIAL_TEXTURE_RULES: dict[str, dict[str, str]] = {
    "LAKOST KUMAŞ": {
        "yan": (
            "Material: LAKOST / pique KNIT CLOTH — waffle or pique grid of raised yarn nodes, "
            "soft textile, not leather. Copy the repeating bump/channel scale from the swatch. "
            "STRICTLY FORBIDDEN: circular punched ventilation holes, dark pinprick perforations, "
            "sport-seat perforated leather, mesh vents, or Alcantara. "
            "If you see hole-like noise, treat it as knit texture and keep the surface continuous."
        ),
        "orta": (
            "Material: LAKOST knit on center insert — repeating pique/waffle nodes and recessed "
            "channels from the swatch, continuous fabric, no ventilation holes."
        ),
    },
    "DÜZ DERİ": {
        "yan": (
            "Material: unperforated plain leather (DÜZ DERİ). Copy the grain from the fabric board "
            "(pebble / nappa grain is correct if the photo shows it). Matte to semi-matte. "
            "ZERO punched holes, ZERO mesh. Do not flatten to painted plastic."
        ),
        "orta": (
            "Material: unperforated plain leather on the center insert — keep the board's grain, "
            "no invented perforations, no flat paint."
        ),
    },
    "PEBBLE DERİ": {
        "yan": (
            "Material: heavily pebbled leather — copy the raised islands and deep crevices from the swatch "
            "at furniture scale. Semi-matte, not smooth vinyl, ZERO punched holes."
        ),
        "orta": (
            "Material: heavily pebbled leather on the insert — match the swatch grain, no perforations."
        ),
    },
    "DOT TYPE DERİ": {
        "yan": (
            "Material: DOT TYPE leather — copy the exact dot/perforation size and spacing from the fabric board only. "
            "Do not invent a different hole pattern."
        ),
        "orta": "Material: match the fabric board center panel leather exactly.",
    },
    "NAKIŞLI DERİ-KUMAŞ": {
        "yan": "Material: embroidered leather-fabric mix — copy embroidery and base texture from the fabric board exactly.",
        "orta": "Material: embroidered center panel — match the fabric board exactly.",
    },
    "MİLANO SÜET": {
        "yan": (
            "Material: MILANO SUEDE — short-pile fuzzy nap with irregular tufts and micro-shadows. "
            "It is SUEDE / pile cloth, not smooth leather. Keep a soft fuzzy read, not flat felt."
        ),
        "orta": (
            "Material: MILANO SUEDE on the center insert — dense short pile, visible nap and "
            "micro-shadows between tufts. Not leather, not flat cream paint, not perforated Alcantara."
        ),
    },
    "TAYTÜYÜ SÜET": {
        "yan": (
            "Material: TAY TÜYÜ — short visible pile/flock, matte. "
            "Not leather, not long fur."
        ),
        "orta": (
            "Material: TAY TÜYÜ = medium-short VISIBLE pile. "
            "Nap pass must NOT recolor: keep the already-applied insert hue (no tan/camel, no olive). "
            "Directional nap OK. HARD FAIL: flat paint, long fur/plush, color shift, leather shine."
        ),
    },
}

# Catalog labels that fight a close-up photo (e.g. DÜZ DERİ vs pebble grain).
_CATALOG_OVERRIDE_WHEN_SWATCH = frozenset({"DÜZ DERİ", "DUZ DERI"})

SWATCH_SURFACE_NOTES: dict[str, str] = {
    "yan": (
        "PHOTO SWATCH (ignore catalog 'smooth leather' labels): the board has MACRO + SEAT DISTANCE. "
        "Read grain identity from MACRO (pebble / nappa crevices, satin peaks). "
        "Paint the seat at SEAT DISTANCE density — pebbles are ~2–3 mm, a fine grain, NOT elephant skin. "
        "Relight to the cabin; do not paste the swatch's baked directional highlights. "
        "Keep crevice micro-shadows so the surface stays 3D, not a flat recolor."
    ),
    "orta": (
        "PHOTO SWATCH: the board has MACRO + SEAT DISTANCE. "
        "MACRO shows pile identity; SEAT DISTANCE is the correct short-pile density on the insert. "
        "Keep a visible short nap. Not flat cream paint, not long fur clumps. "
        "Do not copy pinked / zigzag swatch edges onto the seat."
    ),
}

DEFAULT_YAN_ANTI_PERFORATION = (
    "CRITICAL ANTI-HALLUCINATION: Do NOT invent circular ventilation holes on bolsters. "
    "Automotive perforated leather is a common false prior — reject it unless the fabric board "
    "clearly shows punched holes. Copy ONLY the close-up board surface."
)

YAN_PRODUCT_RENDER_GUIDE = """
Image 3 is a CLOSE-UP FABRIC BOARD cropped from the selected YAN GÖVDE product render.
Image 4 is the full catalog seat render for color context.

Transfer rules:
- Bolsters / outer panels must look like Image 3's fabric tiles — same color and surface
- Ignore Image 4's center insert panels in this pass
- Never replace a continuous cloth/leather surface with perforated sport leather
""".strip()

_MATERIAL_ALIASES = {
    "MILANO SUET": "MİLANO SÜET",
    "MILANO SÜET": "MİLANO SÜET",
    "MİLANO SUET": "MİLANO SÜET",
    "DUZ DERI": "DÜZ DERİ",
    "TAYTUYU SUET": "TAYTÜYÜ SÜET",
    "TAYTÜYÜ SUET": "TAYTÜYÜ SÜET",
    "TAYTUYU SÜET": "TAYTÜYÜ SÜET",
}


def _normalize_material_key(material_type: str) -> str:
    return " ".join(material_type.strip().upper().split())


def _lookup_material_rules(material_type: str | None) -> dict[str, str]:
    if not material_type:
        return {}
    normalized = _normalize_material_key(material_type)
    key = _MATERIAL_ALIASES.get(normalized, normalized)
    rules = MATERIAL_TEXTURE_RULES.get(key)
    if rules:
        return rules
    if "TAYTÜYÜ" in normalized or "TAYTUYU" in normalized:
        return MATERIAL_TEXTURE_RULES["TAYTÜYÜ SÜET"]
    if "SÜET" in normalized or "SUET" in normalized or "SUEDE" in normalized:
        return MATERIAL_TEXTURE_RULES["MİLANO SÜET"]
    return {}


_PATTERN_TRANSFER_TOKENS = (
    "NAKIŞ",
    "NAKIS",
    "JAKAR",
    "LAKOST",
    "PİKE",
    "PIKE",
    "PEBBLE",
    "DOT",
    "DELİK",
    "DELIK",
    "PERFOR",
)


def uses_recolor_preserve(material_type: str | None, layer_key: str = "") -> bool:
    """True: keep the photo's micro-texture, transfer color only."""
    if layer_key == "iplik":
        return True
    if not material_type:
        return True
    normalized = _normalize_material_key(material_type)
    return not any(token in normalized for token in _PATTERN_TRANSFER_TOKENS)


def is_taytuyu_material(material_type: str | None) -> bool:
    if not material_type:
        return False
    normalized = _normalize_material_key(material_type)
    return "TAYTÜYÜ" in normalized or "TAYTUYU" in normalized


def needs_insert_nap_pass(material_type: str | None, layer_key: str = "orta") -> bool:
    """ORTA pile/suede is not in the original cream insert — add nap after recolor."""
    if layer_key != "orta" or not material_type:
        return False
    if is_taytuyu_material(material_type):
        return True
    normalized = _normalize_material_key(material_type)
    return "SÜET" in normalized or "SUET" in normalized or "SUEDE" in normalized


def material_texture_note(
    material_type: str | None,
    layer_key: str,
    *,
    is_direct_swatch: bool = False,
) -> str:
    parts: list[str] = []
    normalized = _normalize_material_key(material_type) if material_type else ""

    if is_direct_swatch:
        swatch_note = SWATCH_SURFACE_NOTES.get(layer_key)
        if swatch_note:
            parts.append(swatch_note)
        if normalized and normalized not in _CATALOG_OVERRIDE_WHEN_SWATCH:
            catalog = _lookup_material_rules(material_type).get(layer_key, "")
            if catalog:
                parts.append(catalog)
    else:
        catalog = _lookup_material_rules(material_type).get(layer_key, "")
        if catalog:
            parts.append(catalog)

    if layer_key == "yan" and "DELİK" not in normalized and "PERFOR" not in normalized:
        parts.append(DEFAULT_YAN_ANTI_PERFORATION)
    elif not parts and layer_key == "yan":
        parts.append(DEFAULT_YAN_ANTI_PERFORATION)

    return "\n".join(parts)
