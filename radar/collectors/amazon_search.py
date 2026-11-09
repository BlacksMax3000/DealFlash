"""Recolector por búsqueda en Amazon (opcional, desactivado por defecto).

ADVERTENCIA ARQUITECTÓNICA:
  El endpoint /s?k=... de Amazon está protegido con muros anti-bot y devuelve
  señuelos o captchas a IPs de datacenter (GitHub Actions). Por eso está
  `enabled: false` en config.yaml. El módulo existe porque funciona razonablemente
  bien desde IPs residenciales (tu PC). El sistema degrada con elegancia: si
  detecta un muro, registra un aviso y continúa con el resto de fuentes.
"""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

from ..models import Deal
from ..utils import fetch, looks_like_botwall

log = logging.getLogger("radar.amazon_search")


def collect(cfg, session) -> list[Deal]:
    if not cfg.search_enabled:
        return []

    deals: list[Deal] = []
    max_per_kw = int(cfg.get("recolectores.amazon_busqueda.max_por_keyword", 8))

    for keyword in cfg.search_keywords:
        url = f"https://www.{cfg.amazon_domain}/s?k={quote_plus(keyword)}"
        try:
            resp = fetch(session, url, timeout=cfg.http_timeout)
            if resp.status_code != 200 or looks_like_botwall(resp.text):
                log.warning(
                    "Búsqueda de Amazon bloqueada/vacía para '%s' (HTTP %s) — se omite. "
                    "Ejecuta desde IP residencial o desactiva este recolector.",
                    keyword, resp.status_code,
                )
                continue
            found = _parse_search(resp.text, cfg, keyword)
            log.info("Búsqueda '%s': %d resultados parseados", keyword, len(found))
            deals.extend(found[:max_per_kw])
        except Exception as exc:  # noqa: BLE001
            log.warning("Error en búsqueda '%s': %s", keyword, exc)
        time.sleep(max(cfg.http_delay * 2, 2.0))

    return deals


def _num(text: str) -> float | None:
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]{2})?)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _parse_search(html: str, cfg, keyword: str) -> list[Deal]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[Deal] = []
    for node in soup.select('div[data-component-type="s-search-result"][data-asin]'):
        asin = node.get("data-asin", "")
        if len(asin) != 10:
            continue
        head = node.select_one("h2 span")
        title = head.get_text(strip=True) if head else ""
        if not title:
            continue

        current = list_price = None
        rating = reviews = None

        p = node.select_one("span.a-price span.a-offscreen")
        if p:
            current = _num(p.get_text())
        lp = node.select_one("span.a-price.a-text-price span.a-offscreen")
        if lp:
            list_price = _num(lp.get_text())
        alt = node.select_one("span.a-icon-alt")
        if alt:
            m = re.match(r"([0-9.]+)", alt.get_text())
            if m:
                rating = float(m.group(1))
        rc = node.select_one("span.a-size-base.s-underline-text")
        if rc:
            try:
                reviews = int(rc.get_text().replace(",", "").strip())
            except ValueError:
                reviews = None

        discount = None
        if current and list_price and list_price > current:
            discount = round((1 - current / list_price) * 100, 1)

        out.append(Deal(
            id=f"amz-{asin}",
            title=title[:300],
            url=f"https://www.{cfg.amazon_domain}/dp/{asin}",
            source="amazon_search",
            asin=asin,
            current_price=current,
            list_price=list_price,
            discount_pct=discount,
            rating=rating,
            reviews=reviews,
            notes=[f"keyword:{keyword}"],
        ))
    return out
