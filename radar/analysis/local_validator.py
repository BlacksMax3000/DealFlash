"""Validador LOCAL sin IA (modo 0 API): reglas estrictas + lista de marcas conocidas.

Sustituto de GLMAnalyzer con la MISMA interfaz (analyze(deal) -> veredicto).
Se activa automáticamente cuando:
  - no existe la variable/secret ZAI_API_KEY, o
  - la API de GLM falla varias veces seguidas (saldo agotado, caída, etc.).

Sin IA el criterio es MÁS conservador que con ella: solo aprueba marcas de la
lista conocida (Tier A/B) y exige más descuento a las marcas secundarias.
Nada se inventa: el mensaje se construye ÚNICAMENTE con datos reales de la
oferta (precio, descuento, valoración si se conoce).

REPO: radar/analysis/local_validator.py (archivo NUEVO)
"""

from __future__ import annotations

import logging
import re

from ..utils import fmt_price

log = logging.getLogger("radar.local")

# --------------------------------------------------------------------------
# Listas de marcas (comparación por palabra completa, insensible a mayúsculas)
# --------------------------------------------------------------------------
# Tier A: marcas top universalmente reconocidas. Basta el descuento mínimo
# global (>= 20 %, que ya exige el filtro duro) para aprobarlas.
TIER_A = (
    # Tech / audio
    "apple", "iphone", "airpods", "macbook", "ipad", "airtag",
    "sony", "samsung", "lg", "bose", "sonos", "jbl", "beats", "marshall",
    "sennheiser", "audio-technica", "klipsch", "polk",
    "anker", "soundcore", "kindle", "echo", "fire tv", "fire hd",
    "amazon basics",
    "nintendo", "playstation", "xbox", "microsoft", "surface", "steam deck",
    "logitech", "razer", "corsair", "steelseries", "hyperx", "elgato",
    "hp", "dell", "lenovo", "asus", "acer", "msi",
    "dji", "gopro", "garmin", "fitbit", "canon", "nikon", "fujifilm",
    "panasonic", "sandisk", "seagate", "western digital", "crucial",
    "kingston", "pny", "netgear", "tp-link", "tplink", "kasa",
    "wyze", "ring doorbell", "ring video doorbell", "ring alarm",
    "ring spotlight", "ring stick up", "blink", "eufy",
    "roborock", "irobot", "roomba", "dyson", "shark", "ninja", "philips",
    # Hogar / cocina
    "instant pot", "kitchenaid", "keurig", "cuisinart", "hamilton beach",
    "bissell", "levoit", "cosori", "nutribullet", "pyrex", "lodge",
    # Herramientas / exterior
    "dewalt", "milwaukee", "makita", "bosch", "ryobi", "black+decker",
    "black decker", "craftsman", "weber", "traeger", "coleman", "yeti",
    "hydro flask", "stanley",
    # Juguetes / ropa / relojes
    "lego", "hasbro", "mattel", "hot wheels", "barbie",
    "nike", "adidas", "new balance", "crocs", "under armour",
    "casio", "seiko", "timex", "fossil", "ray-ban", "oakley",
)

# Tier B: marcas legítimas pero de segundo nivel → exigen descuento >= 25 %.
TIER_B = (
    "gotrax", "greenworks", "ecoflow", "jackery", "bluetti", "segway",
    "ninebot", "xiaomi", "redmi", "tcl", "hisense", "vizio", "toshiba",
    "insignia", "skullcandy", "jlab", "akg", "edifier", "mophie",
    "otterbox", "spigen", "skechers", "columbia", "the north face",
    "levi's", "levis", "hoover", "gourmia", "oxo", "victorinox", "contigo",
    "thermos", "duracell", "energizer", "pampers", "huggies", "gillette",
    "oral-b", "crest", "worx", "ridgid", "ego power", "sun joe",
    "theragun", "renpho", "hyperice", "midland",
)

# Palabras que delatan productos NO comisionables por Amazon Associates
# (tarjetas de regalo y eBooks no pagan comisión) o directamente basura.
REJECT_WORDS = (
    "gift card", "giftcard", "tarjeta de regalo",
    "ebook", "e-book", "audiobook", "audible",
    "subscription", "suscripción", "sample",
)

# Falsos positivos conocidos: si la marca coincide pero el título contiene
# una de estas palabras, NO se considera esa marca.
#   "apple cider vinegar", "ninja sword", "shark tank", "ring light"…
BRAND_EXCLUSIONS = {
    "apple": ("cider", "vinegar", "sauce"),
    "ninja": ("sword", "turtles"),
    "shark": ("tank",),
    "ring doorbell": (),
}

# Precompilar patrones de detección: palabra completa, insensible a mayúsculas
_PATTERN_CACHE: dict[str, re.Pattern] = {}


def _brand_pattern(brand: str) -> re.Pattern:
    if brand not in _PATTERN_CACHE:
        _PATTERN_CACHE[brand] = re.compile(
            r"(?<![a-z0-9])" + re.escape(brand) + r"(?![a-z0-9])"
        )
    return _PATTERN_CACHE[brand]


def detect_tier(title: str, brand_field: str | None) -> str | None:
    """Devuelve 'A', 'B' o None según la primera marca reconocida en el texto."""
    blob = f"{brand_field or ''} {title or ''}".lower()
    blob = blob.replace("black+decker", "black decker")
    for tier, brands in (("A", TIER_A), ("B", TIER_B)):
        for name in brands:
            if not name.strip():
                continue
            if _brand_pattern(name).search(blob):
                # Comprobar exclusiones (falsos positivos conocidos)
                for parent, bad_words in BRAND_EXCLUSIONS.items():
                    if name == parent or name.startswith(parent + " "):
                        if any(bad in blob for bad in bad_words):
                            break                     # esta coincidencia no vale
                else:
                    return tier
    return None


class RulesAnalyzer:
    """Mismo contrato que GLMAnalyzer, pero 100 % local y sin coste."""

    def __init__(self, cfg):
        self.cfg = cfg

    # ------------------------------------------------------------------ API --
    def analyze(self, deal) -> dict:
        tier = detect_tier(deal.title, deal.brand)

        # --- Rechazos duros sin IA -------------------------------------------
        blob = f"{deal.title or ''} {deal.brand or ''}".lower()
        for word in REJECT_WORDS:
            if word in blob:
                return self._verdict(
                    deal, approved=False, score=1.0,
                    flags=["no_comisionable"],
                    reason=f"contiene '{word}': Amazon Associates no comisiona este producto",
                )

        if tier is None:
            return self._verdict(
                deal, approved=False, score=2.0,
                flags=["marca_desconocida"],
                reason="modo sin IA: solo se aprueban marcas de la lista conocida",
            )

        if (deal.discount_pct is not None and deal.discount_pct >= 55
                and (deal.current_price or 0) < 25):
            return self._verdict(
                deal, approved=False, score=1.5,
                flags=["posible_fraude"],
                reason="descuento extremo + precio bajo: patrón de precio-ancla inflado",
            )

        # --- Umbrales por tier ------------------------------------------------
        min_local = self.cfg.min_discount if tier == "A" else 25.0
        if deal.discount_pct is None or deal.discount_pct < min_local:
            tiene = (f"{deal.discount_pct:.0f}%" if deal.discount_pct is not None
                     else "sin dato")
            return self._verdict(
                deal, approved=False, score=4.0,
                flags=["descuento_justo"],
                reason=f"marca tier {tier} exige >= {min_local:.0f}% (tiene {tiene})",
            )

        # --- Aprobada ----------------------------------------------------------
        flags: list[str] = []
        if tier == "B":
            flags.append("verificacion_basica")
        if deal.rating is None:
            flags.append("rating_no_verificado")

        score = 4.0 + min(deal.discount_pct, 60.0) / 10.0
        if tier == "A":
            score += 0.3
        if deal.rating is not None and deal.rating >= 4.5 and (deal.reviews or 0) >= 500:
            score += 0.5
        score = round(min(score, 10.0), 1)

        return self._verdict(
            deal, approved=True, score=score, flags=flags,
            reason=f"marca tier {tier} · descuento {deal.discount_pct:.0f}% verificado",
        )

    # -------------------------------------------------------------- interno --
    def _verdict(self, deal, approved: bool, score: float,
                 flags: list[str], reason: str) -> dict:
        return {
            "approved": approved,
            "real_discount_pct": deal.discount_pct,
            "score": score,
            "flags": flags,
            "reason": reason,
            "message": self._message(deal) if approved else "",
        }

    def _message(self, deal) -> str:
        """Mensaje de Telegram honesto, construido solo con datos reales."""
        pct = f"-{deal.discount_pct:.0f}%" if deal.discount_pct else "OFERTÓN"
        lines = [f"🔥 OFERTÓN: {pct}"]

        title = " ".join((deal.title or "").split())
        if len(title) > 72:
            title = title[:72].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
        lines.append(f"🛒 {title}")

        price_line = f"💰 {fmt_price(deal.current_price)}"
        if deal.list_price:
            price_line += f" (antes {fmt_price(deal.list_price)})"
            if deal.current_price and deal.list_price > deal.current_price:
                price_line += f" · Ahorras {fmt_price(deal.list_price - deal.current_price)}"
        lines.append(price_line)

        if deal.rating is not None:
            reviews = f" ({deal.reviews:,} reseñas)" if deal.reviews else ""
            lines.append(f"⭐ {deal.rating}★{reviews}")

        lines.append("Verificado por el Radar: marca reconocida y descuento real sobre el precio de lista.")
        return "\n".join(lines)
