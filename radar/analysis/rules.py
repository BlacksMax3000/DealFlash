"""Filtro cuantitativo duro (sin IA): descarta lo inviable antes de gastar tokens GLM."""
from __future__ import annotations


def hard_filter(deal, cfg) -> tuple[bool, str]:
    """Devuelve (pasa, motivo). Motivos estables para trazabilidad en la base de datos."""
    if deal.current_price is None:
        return False, "sin_precio"

    if "producto_no_disponible" in deal.notes:
        return False, "producto_no_disponible"

    if not (cfg.price_min <= deal.current_price <= cfg.price_max):
        return False, "precio_fuera_rango"

    if deal.discount_pct is None:
        return False, "sin_datos_descuento"

    # Regla de negocio #1 del cliente: descuento real >= 20%
    if deal.discount_pct < cfg.min_discount:
        return False, "descuento_insuficiente"

    # >85% en electrónica casi siempre es estafa, error de precio o producto basura
    if deal.discount_pct > cfg.max_discount:
        return False, "demasiado_bueno_para_ser_real"

    # Regla de negocio #2: valoración >= 4.0 con >= 50 reseñas (si se conocen)
    if deal.rating is not None and deal.rating < cfg.min_rating:
        return False, "rating_bajo"
    if deal.reviews is not None and deal.reviews < cfg.min_reviews:
        return False, "pocas_reseñas"

    # Regla de negocio #3: sin réplicas / marcas prohibidas
    blob = f"{deal.title} {deal.brand or ''}".lower()
    for word in cfg.banned_words:
        if word.lower() in blob:
            return False, f"palabra_prohibida:{word}"
    brand = (deal.brand or "").lower().strip()
    for banned in cfg.banned_brands:
        if banned.lower().strip() and banned.lower().strip() == brand:
            return False, f"marca_prohibida:{banned}"

    # Señal anti-spam: títulos en mayúsculas gritonas
    letters = [c for c in deal.title if c.isalpha()]
    if len(letters) > 20 and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        return False, "titulo_spam"

    return True, "ok"
