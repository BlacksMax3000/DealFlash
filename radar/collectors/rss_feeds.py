"""Recolector RSS: feeds de comunidades de ofertas con enlaces a Amazon.

Estrategia probada:
  1. Lee el feed (9to5toys / 9to5mac / 9to5google... y cualquier feed Pepper si la
     red no lo bloquea; promodescuentos suele devolver 403 desde IPs de nube).
  2. Filtra títulos tipo "roundup" (recopilatorios) y se queda con artículos que
     traen precio explícito en el título.
  3. Descarga el artículo y extrae el PRIMER enlace directo a un producto
     (amazon.com/dp/ASIN) para construir la candidata.
"""

from __future__ import annotations

import logging
import re
import time

import feedparser

from ..models import Deal
from ..utils import fetch, looks_like_botwall, parse_price_signals

log = logging.getLogger("radar.rss")

_OG_IMAGE_RE = re.compile(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']')


def collect(cfg, session) -> list[Deal]:
    """Devuelve candidatas normalizadas a partir de los feeds configurados."""
    deals: list[Deal] = []
    seen_ids: set[str] = set()

    for feed_url in cfg.rss_urls:
        try:
            resp = fetch(session, feed_url, timeout=cfg.http_timeout)
            if resp.status_code != 200 or looks_like_botwall(resp.text):
                log.warning("Feed inaccesible (HTTP %s): %s — se omite este ciclo", resp.status_code, feed_url)
                continue

            parsed = feedparser.parse(resp.content)
            candidates = parsed.entries[: cfg.rss_max_per_feed * 3]
            used = 0
            for entry in candidates:
                if used >= cfg.rss_max_per_feed:
                    break
                title = _clean(entry.get("title", ""))
                link = entry.get("link", "")
                if not title or not link:
                    continue
                if any(re.search(p, title, re.I) for p in cfg.rss_skip_patterns):
                    continue

                current, list_price, discount = parse_price_signals(title)
                if current is None:          # Sin precio explícito no es una oferta concreta
                    continue

                used += 1
                deal = _resolve_article(cfg, session, link, title, current, list_price, discount)
                if deal and deal.id not in seen_ids:
                    seen_ids.add(deal.id)
                    deals.append(deal)
                time.sleep(cfg.http_delay)

        except Exception as exc:  # noqa: BLE001 — un feed roto nunca debe tirar el ciclo
            log.warning("Error procesando feed %s: %s", feed_url, exc)

    log.info("RSS: %d candidatas tras resolver artículos", len(deals))
    return deals


def _clean(title: str) -> str:
    import html
    return html.unescape(title or "").strip()


def _resolve_article(cfg, session, article_url: str, title: str,
                     current: float | None, list_price: float | None,
                     discount: float | None) -> Deal | None:
    """Descarga el artículo y busca el primer ASIN enlazado."""
    try:
        resp = fetch(session, article_url, timeout=cfg.http_timeout)
        if resp.status_code != 200:
            return None
        page = resp.text
        from ..utils import canonical_product_url, extract_asin
        asin = extract_asin(page)
        if not asin:
            return None

        img = None
        m = _OG_IMAGE_RE.search(page)
        if m:
            img = m.group(1)

        return Deal(
            id=f"amz-{asin}",
            title=title,
            url=canonical_product_url(cfg.amazon_domain, asin),
            source="rss",
            asin=asin,
            current_price=current,
            list_price=list_price,
            discount_pct=discount,
            image_url=img,
            notes=[f"articulo:{article_url}"],
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("No se pudo resolver %s: %s", article_url, exc)
        return None
