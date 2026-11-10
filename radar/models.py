"""Modelo de datos central: la oferta (Deal) que viaja por todo el pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Deal:
    """Una oferta candidata, normalizada, cualquiera que sea su origen."""

    id: str                              # Identificador estable: amz-<ASIN> o hash de URL
    title: str                           # Título original del producto/oferta
    url: str                             # URL del producto (Amazon) o del artículo
    source: str                          # rss | amazon_search | demo
    asin: str | None = None
    brand: str | None = None
    current_price: float | None = None   # Precio actual en USD
    list_price: float | None = None      # Precio de referencia / tachado
    discount_pct: float | None = None    # % de descuento calculado
    rating: float | None = None          # Valoración media (0-5)
    reviews: int | None = None           # Número de reseñas
    community_votes: int | None = None   # "Temperatura" de la comunidad (red Pepper)
    image_url: str | None = None
    fetched_at: str = field(default_factory=utcnow_iso)
    notes: list[str] = field(default_factory=list)   # Trazabilidad (qué detectó cada módulo)

    def to_prompt_dict(self) -> dict:
        """Subconjunto compacto que se envía al modelo de IA."""
        return {
            "titulo": self.title,
            "marca": self.brand,
            "precio_actual_usd": self.current_price,
            "precio_anterior_usd": self.list_price,
            "descuento_pct": self.discount_pct,
            "valoracion": self.rating,
            "resenas": self.reviews,
            "fuente": self.source,
            "notas": self.notes or None,
        }
