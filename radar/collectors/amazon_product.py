"""Enriquecedor: descarga la página de producto de Amazon y extrae datos duros.

Verificado en pruebas reales: las páginas /dp/<ASIN> suelen SER accesibles desde
IPs de datacenter (a diferencia de la búsqueda), y exponen precio, precio de
lista, valoración y número de reseñas en el HTML. Si un producto no está
disponible o Amazon oculta el precio, el enriquecimiento degrada sin romper
el ciclo y la candidata conserva los datos del RSS/título.
"""

from __future__ import annotations

import logging
import re

from ..models import Deal
from ..utils import USER_AGENTS, fetch, looks_like_botwall

log = logging.getLogger("radar.enrich")

_PRICE_PATTERNS = [
    r'"priceAmount"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)',
    r'priceToPay[\s\S]{0,200}?a-offscreen">\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)',
    r'corePrice[\s\S]{0,600}?a-offscreen">\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)',
    r'aok-offscreen">\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)',
]
_LIST_PATTERNS = [
    r'"listPrice"\s*:\s*"?([0-9]+(?:\.[0-9]{1,2})?)',
    r'basisPrice[\s\S]{0,600}?a-offscreen">\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)',
    r'List Price:?\s*</[^>]+>\s*\$\s*([0-9][0-9,]*(?:\.[0-9]{2})?)',
]
_RATING_RE = re.compile(r"([0-9](?:\.[0-9])?)\s*out of 5 stars")
_REVIEWS_PATTERNS = [
    r'acrCustomerReviewText[^>]*>\s*([\d,]+)',
    r'"reviewCount"\s*:\s*(\d+)',
    r'([\d,]+)\s+ratings',
]


def _first_number(html: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def enrich(deal: Deal, cfg, session) -> Deal:
    """Completa precio/valoración/reseñas con datos reales de la página de producto."""
    if not deal.asin:
        return deal

    url = f"https://www.{cfg.amazon_domain}/dp/{deal.asin}?language=en_US"
    # Rota el User-Agent de forma estable por ASIN para reducir el throttling de Amazon
    ua = USER_AGENTS[sum(ord(c) for c in deal.asin) % len(USER_AGENTS)]
    try:
        resp = fetch(session, url, timeout=cfg.http_timeout, headers={"User-Agent": ua})
    except Exception as exc:  # noqa: BLE001
        deal.notes.append(f"enriquecimiento_error:{type(exc).__name__}")
        return deal

    if resp.status_code != 200 or looks_like_botwall(resp.text):
        deal.notes.append(f"enriquecimiento_bloqueado:{resp.status_code}")
        log.debug("Página de producto no accesible (%s): %s", resp.status_code, deal.asin)
        return deal

    html = resp.text

    price = _first_number(html, _PRICE_PATTERNS)
    if price:
        deal.current_price = price

    list_price = _first_number(html, _LIST_PATTERNS)
    if list_price and (not deal.current_price or list_price > deal.current_price):
        deal.list_price = list_price

    m = _RATING_RE.search(html)
    if m:
        deal.rating = float(m.group(1))

    for pattern in _REVIEWS_PATTERNS:
        mm = re.search(pattern, html)
        if mm:
            try:
                deal.reviews = int(mm.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    if deal.list_price and deal.current_price and deal.list_price > deal.current_price:
        deal.discount_pct = round((1 - deal.current_price / deal.list_price) * 100, 1)

    if "currently unavailable" in html.lower() and deal.current_price is None:
        deal.notes.append("producto_no_disponible")

    deal.notes.append("enriquecido:amazon")
    return deal
