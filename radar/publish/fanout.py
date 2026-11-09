"""Capa de CAPTACIÓN (prospección automática): lleva cada oferta aprobada a
todas las superficies habilitadas donde ya hay compradores esperando ofertas.

Realidad de Telegram (honestidad de diseño): la Bot API NO permite escribirle
primero a un usuario que no inició el chat, y automatizar una cuenta de
usuario para mandar DMs en frío viola los Términos de Servicio y acaba en ban.
Por eso la prospección aquí es multi-superficie y conformista:

  1. Telegram extendido   → canales/grupos extra donde el bot es admin
                            (TELEGRAM_CHAT_IDS, separados por coma)
  2. Sitio SEO            → radar/publish/web.py (se genera aparte en main.py)
  3. Bluesky              → post automático (API abierta, gratis)
  4. Discord              → webhooks de servidores de ofertas
  5. Reddit               → opcional, solo subreddits con reglas respetadas

Cada superficie falla DE FORMA AISLADA: un error en una no aborta el ciclo ni
las demás. El resultado es un dict {superficie: ok} para el log del ciclo.
"""

from __future__ import annotations

import logging

import requests

from . import bluesky, discord, reddit, telegram
from .compose import compose_plain, compose_social

log = logging.getLogger("radar.fanout")


def _try(surface: str, results: dict[str, bool], fn) -> None:
    """Ejecuta una superficie aislando su fallo (fail-soft)."""
    try:
        fn()
        results[surface] = True
        log.info("📡 Captación OK → %s", surface)
    except Exception as exc:  # noqa: BLE001 — aislamiento deliberado
        results[surface] = False
        log.warning("📡 Captación FALLÓ → %s: %s", surface, exc)


def fan_out(deal, verdict: dict, aff_url: str | None, cfg,
            session: requests.Session, tg_token: str | None,
            html_message: str | None) -> dict[str, bool]:
    """Reparte UNA oferta aprobada a todas las superficies habilitadas."""
    results: dict[str, bool] = {}

    # 1) Telegram extendido: canales/grupos extra donde el bot es admin
    for chat_id in cfg.extra_chat_ids:
        if tg_token and html_message:
            _try(f"telegram:{chat_id}", results,
                 lambda cid=chat_id: telegram.send_message(tg_token, cid, html_message, session))

    # 2) Bluesky
    if cfg.bluesky_enabled:
        if not aff_url:
            log.info("Captación Bluesky omitida: sin enlace de afiliado")
        else:
            import os

            handle = os.getenv("BLUESKY_HANDLE", "").strip()
            pwd = os.getenv("BLUESKY_APP_PASSWORD", "").strip()
            if handle and pwd:
                text = compose_plain(deal, verdict, aff_url, cfg.bluesky_hashtags)
                _try("bluesky", results,
                     lambda: bluesky.post_text(handle, pwd, text, session))
            else:
                log.info("Captación Bluesky omitida: faltan BLUESKY_HANDLE / BLUESKY_APP_PASSWORD")

    # 3) Discord (varios webhooks)
    for hook in cfg.discord_webhooks:
        label = f"discord:{hook.split('/')[-1][:8]}"
        _try(label, results,
             lambda h=hook: discord.post_webhook(h, compose_social(deal, verdict, aff_url), session))

    # 4) Reddit (opcional; solo si hay subreddits configurados)
    if cfg.reddit_subreddits:
        title = f"[-{deal.discount_pct:.0f}%] {deal.title[:80]}" if deal.discount_pct else deal.title[:90]
        for sub in cfg.reddit_subreddits:
            _try(f"reddit:r/{sub}", results,
                 lambda s=sub: reddit.post_link(s, title, aff_url or deal.url, session))

    return results
