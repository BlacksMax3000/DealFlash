"""Publicación en Telegram vía Bot API pura (sin SDK extra).

Documentación: https://core.telegram.org/bots/api#sendmessage
Gestiona: rate-limit (429 + retry_after), fallos de parseo HTML (reintenta en
texto plano) y errores de red con reintentos.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("radar.telegram")


class TelegramError(RuntimeError):
    pass


def get_me(token: str, session: requests.Session) -> dict:
    """Verifica el token del bot (prueba de conexión al arrancar)."""
    resp = session.get(f"https://api.telegram.org/bot{token}/getMe", timeout=20)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"Token de bot inválido: {data}")
    return data["result"]


def send_message(token: str, chat_id: str, text: str,
                 session: requests.Session, max_attempts: int = 4) -> dict:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, max_attempts + 1):
        try:
            resp = session.post(url, json=payload, timeout=30)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            if attempt == max_attempts:
                raise TelegramError(f"error de red: {exc}") from exc
            time.sleep(3)
            continue

        if data.get("ok"):
            return data

        code = data.get("error_code")
        desc = str(data.get("description", ""))

        if code == 429:
            wait = int(data.get("parameters", {}).get("retry_after", 5)) + 1
            log.warning("Rate limit de Telegram: esperando %ds", wait)
            time.sleep(wait)
            continue

        if code == 400 and "parse" in desc.lower():
            log.warning("Fallo de parseo HTML, reintentando en texto plano: %s", desc)
            payload["parse_mode"] = None
            continue

        raise TelegramError(f"Telegram {code}: {desc}")

    raise TelegramError("no se pudo enviar tras varios intentos")
