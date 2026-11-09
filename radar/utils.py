"""Utilidades: HTTP con reintentos, parseo de precios, extracción de ASIN, logging."""

from __future__ import annotations

import html as html_mod
import logging
import re
import sys
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("radar")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_BOTWALL_MARKERS = (
    "captcha", "automated access", "robot check", "enter the characters",
    "verificando que no seas un bot", "to discuss automated access",
)


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def http_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({
        "User-Agent": USER_AGENTS[0],
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    })
    return s


def fetch(session: requests.Session, url: str, timeout: int = 25, **kwargs) -> requests.Response:
    resp = session.get(url, timeout=timeout, **kwargs)
    return resp


def polite_sleep(seconds: float) -> None:
    if seconds > 0:
        time.sleep(seconds)


def looks_like_botwall(text: str) -> bool:
    """Detecta páginas señuelo / challenges de Cloudflare / muros anti-bot."""
    if not text or len(text) < 4096:
        return True
    head = text[:8000].lower()
    return any(m in head for m in _BOTWALL_MARKERS)


# ---------------------------------------------------------------- precios ---

_PRICE_RE = re.compile(r"\$\s?([0-9]{1,4}(?:,[0-9]{3})*(?:\.[0-9]{2})?)")
_REG_PRICE_RE = re.compile(
    r"(?:reg\.?|regularly|list:|orig\.?|originally|worth)\s*\$\s?([0-9,]+(?:\.[0-9]{2})?)", re.I
)
_PCT_OFF_RE = re.compile(r"([0-9]{1,2})\s?%\s?off", re.I)
_AMT_OFF_RE = re.compile(r"\$\s?([0-9,]+(?:\.[0-9]{2})?)\s?(?:off|in savings|discount)", re.I)
_DROP_TO_RE = re.compile(
    r"(?:down to|drops? to|for just|just|only|now|at)\s*\$\s?([0-9,]+(?:\.[0-9]{2})?)", re.I
)


def _to_float(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def parse_price_signals(text: str) -> tuple[float | None, float | None, float | None]:
    """Extrae (precio_actual, precio_anterior, descuento_pct) de un texto tipo título."""
    prices = [_to_float(p) for p in _PRICE_RE.findall(text)]
    prices = [p for p in prices if p is not None and p >= 0.5]
    if not prices:
        return (None, None, None)

    reg = _REG_PRICE_RE.search(text)
    list_price = _to_float(reg.group(1)) if reg else None

    pct_m = _PCT_OFF_RE.search(text)
    amt_m = _AMT_OFF_RE.search(text)
    drop_m = _DROP_TO_RE.search(text)
    amt_value = _to_float(amt_m.group(1)) if amt_m else None

    current = _to_float(drop_m.group(1)) if drop_m else None
    if current is None:
        # Un importe "$X off" es un AHORRO, no un precio: nunca lo uses como precio actual.
        pool = [p for p in prices if amt_value is None or abs(p - amt_value) > 0.01]
        others = [p for p in pool if list_price is None or abs(p - list_price) > 0.01]
        current = min(others) if others else None
    if current is None:
        return (None, None, None)

    if list_price is None and pct_m and current:
        pct = int(pct_m.group(1))
        if 5 <= pct <= 95:
            list_price = round(current / (1 - pct / 100.0), 2)

    if list_price is None and amt_m and current:
        amt = _to_float(amt_m.group(1))
        if amt and amt > 0:
            list_price = round(current + amt, 2)

    if list_price is not None and list_price <= current:
        list_price = max(prices) if max(prices) > current else None

    discount = None
    if list_price and current and list_price > current:
        discount = round((1 - current / list_price) * 100, 1)
    return (current, list_price, discount)


# ------------------------------------------------------------------ ASIN ----

_ASIN_RE = re.compile(
    r"amazon\.[a-z.]+/(?:[a-z0-9\-%]{0,60}/)?(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.I
)


def extract_asin(text: str) -> str | None:
    m = _ASIN_RE.search(text or "")
    return m.group(1).upper() if m else None


def canonical_product_url(domain: str, asin: str) -> str:
    return f"https://www.{domain}/dp/{asin}"


# ------------------------------------------------------------- formatos -----

def fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    if float(value).is_integer():
        return f"${int(value):,}"
    return f"${value:,.2f}"


def escape_tg(text: str) -> str:
    """Escapa los caracteres que Telegram interpreta en modo HTML."""
    return html_mod.escape(text or "", quote=False)
