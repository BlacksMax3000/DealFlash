"""Composición del mensaje final para Telegram (texto IA + enlace + cumplimiento).

Cumplimiento Amazon Associates:
  - El pie declara la condición de afiliado (obligación de disclosure).
  - Se imprime la fecha/hora de verificación del precio (los precios de Amazon
    cambian; Associates exige no presentarlos como permanentes).
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..utils import escape_tg, fmt_price


def _fallback_body(deal) -> str:
    cur, lst = fmt_price(deal.current_price), fmt_price(deal.list_price)
    discount = f"-{deal.discount_pct:.0f}%" if deal.discount_pct else ""
    rating = f"\n⭐ {deal.rating}★ ({deal.reviews:,} reseñas)" if deal.rating else ""
    return (
        f"🔥 OFERTÓN: {discount}\n"
        f"🛒 {deal.title[:80]}\n"
        f"💰 {cur} (antes {lst}){rating}\n"
        f"Detectado por DealFlash y verificado antes de publicar."
    )


def compose_message(deal, verdict: dict, affiliate_url: str | None) -> str:
    body = (verdict.get("message") or "").strip()
    if not body:
        body = _fallback_body(deal)

    timestamp = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
    link_line = (
        f'\n👉 <a href="{affiliate_url}">COMPRAR EN AMAZON</a>'
        if affiliate_url
        else "\n👉 Busca el producto en Amazon"
    )

    return (
        f"{escape_tg(body)}\n"
        f"{link_line}\n"
        f"🏷️ Somos afiliados de Amazon · ⏱ Precio verificado {timestamp} UTC"
    )


# ------------------------------------------------------------ captación v2 --

DEFAULT_HASHTAGS = ("ofertas", "descuentos", "deals")


def _clean_title(deal, max_len: int | None = None) -> str:
    title = " ".join((deal.title or "").split())
    if max_len and len(title) > max_len:
        title = title[: max_len - 1].rstrip(" ,;:-") + "…"
    return title


def compose_plain(deal, verdict: dict, affiliate_url: str | None,
                  hashtags: tuple[str, ...] | None = None,
                  max_len: int = 295) -> str:
    """Versión compacta en texto plano para Bluesky (límite ~300 grafemas).

    La URL cuenta entera en el límite, así que el título se recorta para que
    el mensaje completo quepa sin cortar el enlace ni los hashtags.
    """
    link = affiliate_url or deal.url or ""
    tags = hashtags or DEFAULT_HASHTAGS
    cur, lst = fmt_price(deal.current_price), fmt_price(deal.list_price)
    pct = f"-{deal.discount_pct:.0f}%" if deal.discount_pct else "OFERTÓN"
    rating = f" ⭐{deal.rating}" if deal.rating else ""

    tail = f"{cur} (antes {lst}){rating}\n{link}\n#{' #'.join(tags)}"
    budget = max(40, max_len - len(tail) - 2)          # 2 = "\n" + "🔥 "
    title = _clean_title(deal, budget)

    return f"🔥 {pct} {title}\n{tail}"


def compose_social(deal, verdict: dict, affiliate_url: str | None) -> str:
    """Versión extendida en texto plano para Discord y Reddit (≤1900 chars)."""
    body = (verdict.get("message") or "").strip()
    if not body:
        body = "Detectado por DealFlash y verificado antes de publicar."

    timestamp = datetime.now(timezone.utc).strftime("%d/%m %H:%M")
    cur, lst = fmt_price(deal.current_price), fmt_price(deal.list_price)
    pct = f"-{deal.discount_pct:.0f}%" if deal.discount_pct else "OFERTÓN"
    rating_line = ""
    if deal.rating:
        reviews = f"{deal.reviews:,} reseñas" if deal.reviews else "verificadas"
        rating_line = f"\n⭐ {deal.rating}★ ({reviews})"

    link = affiliate_url or deal.url or ""
    message = (
        f"🔥 OFERTÓN {pct}\n"
        f"🛒 {_clean_title(deal, 120)}{rating_line}\n"
        f"💰 {cur} (antes {lst})\n"
        f"\n{body}\n"
        f"\n👉 {link}\n"
        f"🏷️ Enlace de afiliado de Amazon · ⏱ Precio verificado {timestamp} UTC"
    )
    return message[:1900]
