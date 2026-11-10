"""Modo DEMO: pipeline completo de punta a punta sin ninguna clave ni red.

Objetivo: que puedas verificar la lógica (reglas → análisis → enlace de
afiliado → mensaje final) antes de configurar los secretos. Los veredictos
simulan EXACTAMENTE la salida JSON que produce la IA en producción.
Ejecución:  python -m radar.main --demo --dry-run
"""

from __future__ import annotations

from .models import Deal


def demo_deals() -> list[Deal]:
    """Siete candidatas que cubren todos los caminos del pipeline."""
    base = "https://www.amazon.com/dp/{}"
    cases = [
        # (id, título, precio actual, precio anterior, %, rating, reseñas, destino)
        ("B0DEMO001", "Bose QuietComfort Ultra Wireless Headphones, Spatial Audio",
         249.0, 429.0, 42.0, 4.7, 18420, "aprobada"),
        ("B0DEMO002", "Apple AirPods Pro 3 Wireless Earbuds, USB-C",
         219.0, 249.0, 12.1, 4.8, 9310, "descuento_insuficiente"),
        ("B0DEMO003", "Sony WH-1000XM6 Wireless Noise Canceling Headphones",
         328.0, 449.0, 26.9, 4.8, 2105, "aprobada"),
        ("B0DEMO004", "Replica Designer Watch Gold Luxury Men Gift Box Set",
         39.99, 199.99, 80.0, None, None, "palabra_prohibida"),
        ("B0DEMO005", "Wireless Earbuds Pro X5 Ultra Bluetooth 5.4 Headphones",
         21.99, 79.99, 72.5, 3.9, 88, "rating_bajo"),
        ("B0DEMO006", "2026 New SmartWatch Z9 Ultra Max Pro Flash Deal 80% OFF",
         19.99, 99.99, 80.0, None, None, "fraude_glm"),
        ("B0DEMO007", "KitchenAid Artisan Series 5-Qt Tilt-Head Stand Mixer",
         279.99, 459.99, 39.1, 4.8, 12300, "aprobada"),
    ]
    deals = []
    for asin, title, cur, lst, pct, rating, reviews, destino in cases:
        deals.append(Deal(
            id=f"amz-{asin}",
            title=title,
            url=base.format(asin),
            source="demo",
            asin=asin,
            current_price=cur,
            list_price=lst,
            discount_pct=pct,
            rating=rating,
            reviews=reviews,
            notes=[f"demo:{destino}"],
        ))
    return deals


# Veredictos "de GLM" pre-escritos para las demo (formato idéntico al real).
DEMO_VERDICTS: dict[str, dict] = {
    "amz-B0DEMO001": {
        "approved": True,
        "real_discount_pct": 42.0,
        "score": 9.2,
        "flags": [],
        "reason": "Marca top de audio, 42% real de ahorro y valoración sobresaliente con más de 18 mil reseñas.",
        "message": (
            "🔥 OFERTÓN: -42%\n"
            "🎧 Bose QuietComfort Ultra\n"
            "💰 $249 (antes $429)\n"
            "⭐ 4.7★ (18,420 reseñas)\n"
            "Los tope de gama de Bose con cancelación adaptativa y audio espacial: $180 de ahorro real."
        ),
    },
    "amz-B0DEMO003": {
        "approved": True,
        "real_discount_pct": 26.9,
        "score": 8.1,
        "flags": [],
        "reason": "Buena marca, descuento real verificable y valoración muy alta.",
        "message": (
            "🔥 OFERTÓN: -27%\n"
            "🎧 Sony WH-1000XM6\n"
            "💰 $328 (antes $449)\n"
            "⭐ 4.8★ (2,105 reseñas)\n"
            "Los líderes de cancelación de ruido de Sony con $121 de descuento directo."
        ),
    },
    "amz-B0DEMO007": {
        "approved": True,
        "real_discount_pct": 39.1,
        "score": 8.6,
        "flags": [],
        "reason": "Clásico de cocina con 39% real de descuento y valoración sólida.",
        "message": (
            "🔥 OFERTÓN: -39%\n"
            "🍰 KitchenAid Artisan 5-Qt\n"
            "💰 $279.99 (antes $459.99)\n"
            "⭐ 4.8★ (12,300 reseñas)\n"
            "La batidora de pie más deseada, $180 menos que su precio habitual."
        ),
    },
    "amz-B0DEMO006": {
        "approved": False,
        "real_discount_pct": None,
        "score": 1.5,
        "flags": ["descuento_falso", "posible_fraude", "rating_no_verificado"],
        "reason": "Genérico sin marca con ancla de precio inflada y descuento de 80% típico de estafa.",
        "message": "",
    },
}


class FakeAnalyzer:
    """Sustituto de GLMAnalyzer para el modo demo (misma interfaz)."""

    def analyze(self, deal) -> dict:
        verdict = DEMO_VERDICTS.get(deal.id)
        if verdict:
            return dict(verdict)
        return {
            "approved": False,
            "real_discount_pct": None,
            "score": 0.0,
            "flags": ["datos_insuficientes"],
            "reason": "sin veredicto de demo para esta candidata",
            "message": "",
        }
