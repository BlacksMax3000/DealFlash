"""Carga de configuración: config.yaml (valores) + variables de entorno (secretos)."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# Valores por defecto: config.yaml puede sobreescribir cualquier rama.
DEFAULTS: dict = {
    "mercado": {
        "dominio_amazon": "amazon.com",
        "moneda": "USD",
    },
    "afiliado": {
        "tag": "",                       # Se rellena vía env AMAZON_TAG o aquí
    },
    "recolectores": {
        "rss_feeds": {
            "enabled": True,
            "urls": [
                "https://9to5toys.com/feed/",
                "https://9to5mac.com/feed/",
                "https://9to5google.com/feed/",
                # "https://www.promodescuentos.com/rss/news",  # Puede devolver 403 (Cloudflare) desde IPs de nube
            ],
            "max_articulos_por_feed": 12,
            "patrones_descartar": [
                r"^top\s*\d+", r"recap", r"best of", r"weekly", r"roundup",
                r"newsletter", r"liveblog", r"^deals?\s*:", r"gu[ií]a", r"review[:\s]",
                r"ends? tonight", r"deals?\s+(are\s+)?(now\s+)?live", r"doorbusters?",
                r"live from\s+\$\d+",
            ],
        },
        "amazon_busqueda": {
            "enabled": False,            # El endpoint de búsqueda suele estar protegido contra bots en la nube
            "keywords": ["wireless earbuds deal", "smartwatch deal", "robot vacuum deal"],
            "max_por_keyword": 8,
        },
        "enriquecer_producto": {
            "enabled": True,             # Descarga la página de producto para precio/valoración exactos
        },
    },
    "filtros": {
        "descuento_min_pct": 20.0,
        "descuento_max_pct": 85.0,       # >85% en electrónica casi siempre es estafa o error
        "rating_min": 4.0,
        "resenas_min": 50,
        "precio_min": 5.0,
        "precio_max": 2000.0,
        "palabras_prohibidas": ["replica", "réplica", "falsificado", "knockoff", "imitación", "no name"],
        "marcas_prohibidas": [],
    },
    "publicacion": {
        "max_posts_por_ciclo": 6,
        "max_candidatas_por_ciclo": 12,
        "pausa_entre_mensajes_seg": 4.0,
    },
    "captacion": {
        # Prospección automática: llevar cada oferta aprobada a más superficies
        "web": {
            "enabled": True,
            "directorio": "site",
            "titulo": "DealFlash",
            "base_url": "",              # SITE_BASE_URL > GitHub Pages deducido > localhost
            "max_deals": 60,
            "canal_telegram": "",        # URL pública del canal para el CTA del sitio
        },
        "bluesky": {"enabled": False, "hashtags": ["ofertas", "descuentos", "deals"]},
        "discord": {"enabled": True},    # se activa solo si hay webhooks en el env
        "reddit": {"enabled": False, "subreddits": []},
        "telegram_extra": {"enabled": True},
    },
    "glm": {
        "base_url": "https://api.z.ai/api/paas/v4",
        "modelo": "glm-5.3",             # Alternativas: glm-5.2, glm-5.1 (más económicos)
        "temperature": 0.2,
        "thinking": "disabled",          # "enabled" = análisis más profundo, más lento/caro
        "max_tokens": 900,
    },
    "almacen": {
        "ruta": "data/radar.db",
        "ttl_rechazados_dias": 14,
    },
    "http": {
        "pausa_entre_peticiones_seg": 1.5,
        "timeout_seg": 25,
    },
}


def _merge(base: dict, extra: dict | None) -> dict:
    out = dict(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict, path: str | None = None):
        self._d = _merge(DEFAULTS, data)
        self.path = path

    def get(self, dotted_key: str, default=None):
        node: object = self._d
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ---- Accesos cómodos usados por el resto del código ----
    @property
    def amazon_domain(self) -> str:
        return str(self.get("mercado.dominio_amazon", "amazon.com"))

    @property
    def tag(self) -> str:
        return (os.getenv("AMAZON_TAG") or self.get("afiliado.tag", "") or "").strip()

    @property
    def rss_enabled(self) -> bool:
        return bool(self.get("recolectores.rss_feeds.enabled", True))

    @property
    def rss_urls(self) -> list[str]:
        return list(self.get("recolectores.rss_feeds.urls", []))

    @property
    def rss_max_per_feed(self) -> int:
        return int(self.get("recolectores.rss_feeds.max_articulos_por_feed", 12))

    @property
    def rss_skip_patterns(self) -> list[str]:
        return list(self.get("recolectores.rss_feeds.patrones_descartar", []))

    @property
    def search_enabled(self) -> bool:
        return bool(self.get("recolectores.amazon_busqueda.enabled", False))

    @property
    def search_keywords(self) -> list[str]:
        return list(self.get("recolectores.amazon_busqueda.keywords", []))

    @property
    def enrich_enabled(self) -> bool:
        return bool(self.get("recolectores.enriquecer_producto.enabled", True))

    @property
    def min_discount(self) -> float:
        return float(self.get("filtros.descuento_min_pct", 20.0))

    @property
    def max_discount(self) -> float:
        return float(self.get("filtros.descuento_max_pct", 85.0))

    @property
    def min_rating(self) -> float:
        return float(self.get("filtros.rating_min", 4.0))

    @property
    def min_reviews(self) -> int:
        return int(self.get("filtros.resenas_min", 50))

    @property
    def price_min(self) -> float:
        return float(self.get("filtros.precio_min", 5.0))

    @property
    def price_max(self) -> float:
        return float(self.get("filtros.precio_max", 2000.0))

    @property
    def banned_words(self) -> list[str]:
        return list(self.get("filtros.palabras_prohibidas", []))

    @property
    def banned_brands(self) -> list[str]:
        return list(self.get("filtros.marcas_prohibidas", []))

    @property
    def max_posts(self) -> int:
        return int(self.get("publicacion.max_posts_por_ciclo", 6))

    @property
    def max_candidates(self) -> int:
        return int(self.get("publicacion.max_candidatas_por_ciclo", 12))

    @property
    def post_pause(self) -> float:
        return float(self.get("publicacion.pausa_entre_mensajes_seg", 4.0))

    @property
    def glm(self) -> dict:
        return {
            "base_url": str(self.get("glm.base_url", DEFAULTS["glm"]["base_url"])).rstrip("/"),
            "model": str(self.get("glm.modelo", "glm-5.3")),
            "temperature": float(self.get("glm.temperature", 0.2)),
            "thinking": str(self.get("glm.thinking", "disabled")),
            "max_tokens": int(self.get("glm.max_tokens", 900)),
        }

    @property
    def db_path(self) -> str:
        return str(self.get("almacen.ruta", "data/radar.db"))

    @property
    def reject_ttl_days(self) -> int:
        return int(self.get("almacen.ttl_rechazados_dias", 14))

    @property
    def http_delay(self) -> float:
        return float(self.get("http.pausa_entre_peticiones_seg", 1.5))

    @property
    def http_timeout(self) -> int:
        return int(self.get("http.timeout_seg", 25))

    # ---------------------- captación automática (prospección multi-superficie)

    @property
    def currency(self) -> str:
        return str(self.get("mercado.moneda", "USD"))

    @property
    def site_enabled(self) -> bool:
        return bool(self.get("captacion.web.enabled", True))

    @property
    def site_dir(self) -> str:
        return str(self.get("captacion.web.directorio", "site"))

    @property
    def site_title(self) -> str:
        return str(self.get("captacion.web.titulo", "DealFlash"))

    @property
    def site_max_deals(self) -> int:
        return int(self.get("captacion.web.max_deals", 60))

    @property
    def site_base_url(self) -> str:
        """URL pública del sitio. Prioridad: env SITE_BASE_URL > deducir del repo
        de GitHub Actions (https://owner.github.io/repo/) > config.yaml > local."""
        env = os.getenv("SITE_BASE_URL", "").strip().rstrip("/")
        if env:
            return env
        repo = os.getenv("GITHUB_REPOSITORY", "").strip()   # lo inyecta Actions gratis
        if repo and "/" in repo:
            owner, name = repo.split("/", 1)
            if name == f"{owner}.github.io":
                return f"https://{owner}.github.io"
            return f"https://{owner}.github.io/{name}"
        local = str(self.get("captacion.web.base_url", "") or "").strip().rstrip("/")
        return local or "http://localhost:8000"

    @property
    def telegram_channel_url(self) -> str:
        return (os.getenv("TELEGRAM_CHANNEL_URL")
                or str(self.get("captacion.web.canal_telegram", "") or "")).strip()

    @property
    def extra_chat_ids(self) -> list[str]:
        """Canales/grupos extra donde el bot es admin (TELEGRAM_CHAT_IDS)."""
        if not self.get("captacion.telegram_extra.enabled", True):
            return []
        raw = os.getenv("TELEGRAM_CHAT_IDS", "")
        return [c.strip() for c in raw.split(",") if c.strip()]

    @property
    def bluesky_enabled(self) -> bool:
        return bool(self.get("captacion.bluesky.enabled", False))

    @property
    def bluesky_hashtags(self) -> tuple[str, ...]:
        return tuple(self.get("captacion.bluesky.hashtags",
                              ["ofertas", "descuentos", "deals"]))

    @property
    def discord_webhooks(self) -> list[str]:
        if not self.get("captacion.discord.enabled", True):
            return []
        raw = os.getenv("DISCORD_WEBHOOK_URLS", "")
        return [u.strip() for u in raw.split(",") if u.strip()]

    @property
    def reddit_subreddits(self) -> list[str]:
        if not self.get("captacion.reddit.enabled", False):
            return []
        subs = self.get("captacion.reddit.subreddits", [])
        out: list[str] = []
        for s in subs:
            name = str(s).strip()
            if name.lower().startswith("r/"):
                name = name[2:]
            if name:
                out.append(name)
        return out


def load_config(path: str = "config.yaml") -> Config:
    """Carga .env (si existe) + config.yaml. Nunca falla si falta el YAML."""
    load_dotenv()
    p = Path(path)
    data: dict = {}
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Config(data, str(p) if p.exists() else None)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Falta la variable de entorno {name}. "
            f"Defínela en tu .env local o en los Secrets de GitHub Actions."
        )
    return value
