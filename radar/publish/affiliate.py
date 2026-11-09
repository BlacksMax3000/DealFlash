"""Construcción de enlaces de afiliado de Amazon.

El enlace canónico de producto + `?tag=<TAG>` es el formato que Amazon
Associates reconoce (tag -20 para amazon.com). Si el usuario aún no tiene tag,
se devuelve la URL limpia (publicable en pruebas, sin comisión).
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def build_affiliate_link(deal, tag: str, domain: str) -> str | None:
    if not tag:
        return deal.url  # Sin tag aún: enlace limpio (útil en --demo / --dry-run)

    asin = deal.asin
    if not asin:
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", deal.url or "", re.I)
        asin = m.group(1).upper() if m else None

    if asin:
        return f"https://www.{domain}/dp/{asin}/?tag={tag}"

    # URL de Amazon sin ASIN explícito: inyecta/reemplaza el parámetro tag
    if domain in (deal.url or ""):
        parts = urlsplit(deal.url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "tag"]
        query.append(("tag", tag))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    return None  # No es un enlace de Amazon: no hay comisión posible
