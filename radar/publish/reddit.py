"""Captación en Reddit (OPCIONAL — desactivada por defecto por seguridad).

⚠️ LÉELO ANTES DE ACTIVARLO:
  - Muchos subreddits de ofertas PROHÍBEN enlaces de afiliado o exigen un
    disclosure explícito. Publicar sin respetar las reglas = ban de cuenta
    y de dominio (shadowban del tag de afiliado).
  - Crea una app tipo "script" en https://www.reddit.com/prefs/apps y pon las
    credenciales en los secrets (REDDIT_CLIENT_ID / SECRET / USERNAME / PASSWORD).
  - Activa solo subreddits concretos en config.yaml → captacion.reddit.subreddits,
    tras leer sus reglas. Empieza por UNO y observa la reacción de la comunidad.

La app se autentica con OAuth password-grant (solo funciona con apps "script")
y publica la oferta como POST de enlace con título limpio.
"""

from __future__ import annotations

import logging

import requests

from ..config import require_env

log = logging.getLogger("radar.reddit")


def _user_agent(username: str) -> str:
    # Reddit exige un User-Agent descriptivo y único por app
    return f"script:dealflash:v2 (by /u/{username})"


def post_link(subreddit: str, title: str, url: str, session: requests.Session) -> dict:
    """Publica un post de enlace en un subreddit. Requiere las 4 vars REDDIT_*."""
    client_id = require_env("REDDIT_CLIENT_ID")
    client_secret = require_env("REDDIT_CLIENT_SECRET")
    username = require_env("REDDIT_USERNAME")
    password = require_env("REDDIT_PASSWORD")
    ua = _user_agent(username)

    token_resp = session.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "password", "username": username, "password": password},
        headers={"User-Agent": ua},
        timeout=20,
    )
    if token_resp.status_code >= 400:
        raise RuntimeError(f"Reddit OAuth {token_resp.status_code}: {token_resp.text[:160]}")
    token = token_resp.json()["access_token"]

    resp = session.post(
        "https://oauth.reddit.com/api/submit",
        headers={"User-Agent": ua, "Authorization": f"bearer {token}"},
        data={
            "api_type": "json",
            "sr": subreddit,
            "title": title[:300],
            "url": url,
            "resubmit": True,
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Reddit submit {resp.status_code}: {resp.text[:160]}")
    errors = resp.json().get("json", {}).get("errors") or []
    if errors:
        raise RuntimeError(f"Reddit rechazó el post: {errors[:1]}")
    log.info("Publicado en Reddit: r/%s", subreddit)
    return resp.json()
