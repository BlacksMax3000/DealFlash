"""Captación en Bluesky vía AT Protocol puro (sin SDK, solo requests).

Es la red social más barata de automatizar: el registro es gratis, la API es
abierta y solo pide una "contraseña de app" (se crea en bsky.app → Ajustes →
Contraseñas de app; se puede revocar en cualquier momento).

Endpoints:
  - POST /xrpc/com.atproto.server.createSession  (login)
  - POST /xrpc/com.atproto.repo.createRecord     (publicar post)

Nota: el límite de un post es de 300 grafemas; compose.compose_plain ya
recorta el título para que quepa el enlace y los hashtags.
"""

from __future__ import annotations

import logging

import requests

from ..models import utcnow_iso

log = logging.getLogger("radar.bluesky")

_BASE = "https://bsky.social/xrpc"


def post_text(handle: str, app_password: str, text: str,
              session: requests.Session, langs: list[str] | None = None) -> dict:
    """Publica un post de texto. `text` debe caber en 300 grafemas."""
    login = session.post(
        f"{_BASE}/com.atproto.server.createSession",
        json={"identifier": handle, "password": app_password},
        timeout=20,
    )
    if login.status_code >= 400:
        raise RuntimeError(f"Bluesky login {login.status_code}: {login.text[:160]}")
    jwt = login.json()["accessJwt"]

    record = {
        "$type": "app.bsky.feed.post",
        "text": text[:300],
        "createdAt": utcnow_iso(),
        "langs": langs or ["es"],
    }
    resp = session.post(
        f"{_BASE}/com.atproto.repo.createRecord",
        headers={"Authorization": f"Bearer {jwt}"},
        json={"repo": handle, "collection": "app.bsky.feed.post", "record": record},
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Bluesky post {resp.status_code}: {resp.text[:160]}")
    data = resp.json()
    log.info("Publicado en Bluesky: @%s", handle)
    return data
