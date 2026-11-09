"""Captación en Discord vía webhooks de canal (la vía más simple y gratis).

Un webhook es una URL de canal que acepta POST sin login. Se crea en Discord:
Ajustes del canal → Integraciones → Webhooks → Nuevo webhook → Copiar URL.

Soporta varias URLs separadas por coma (DISCORD_WEBHOOK_URLS) para publicar
en varios servidores de ofertas a la vez. Gestiona el 429 con `retry_after`.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("radar.discord")


def post_webhook(url: str, text: str, session: requests.Session,
                 max_attempts: int = 3) -> dict:
    """Publica un mensaje por webhook. `text` ≤ 2000 chars (Discord)."""
    payload = {"content": text[:2000], "allowed_mentions": {"parse": []}}

    for attempt in range(1, max_attempts + 1):
        resp = session.post(url, json=payload, timeout=15)
        if resp.status_code in (200, 204):
            return {}
        if resp.status_code == 429:
            try:
                wait = float(resp.json().get("retry_after", 2))
            except ValueError:
                wait = 2.0
            log.warning("Rate limit de Discord: esperando %.1fs", wait)
            time.sleep(wait + 0.5)
            continue
        raise RuntimeError(f"Discord webhook {resp.status_code}: {resp.text[:160]}")

    raise RuntimeError("Discord webhook: sin respuesta válida tras varios intentos")
