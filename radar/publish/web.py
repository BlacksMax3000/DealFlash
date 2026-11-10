"""Generador del sitio estático de CAPTACIÓN (SEO programático, $0 en Pages).

Cada oferta aprobada se convierte en una página pública indexable por Google:

    site/index.html     portada con los últimas ofertas
    site/p/<slug>.html  ficha SEO de la oferta (JSON-LD Product + Offer)
    site/feed.xml       RSS 2.0 (lectores de feeds y agregadores)
    site/sitemap.xml    para Google Search Console
    site/robots.txt     permite rastreo + referencia al sitemap
    site/style.css      hoja de estilos (tema oscuro "ofertas")

El sitio se REGENERA COMPLETO en cada ciclo a partir del snapshot de la BD
(storage/store.py → tabla `deals`), así que es idempotente: no duplica nada
y refleja siempre los últimos N ofertas publicadas. GitHub Actions lo
commitea y lo despliega gratis con GitHub Pages.

Cada ficha lleva el enlace de afiliado (rel="nofollow sponsored", como exige
Amazon) y un CTA hacia el canal de Telegram: el sitio convierte búsquedas de
Google en suscriptores y compras.
"""

from __future__ import annotations

import html as html_mod
import json
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

log = __import__("logging").getLogger("radar.web")


def esc(text) -> str:
    return html_mod.escape(str(text if text is not None else ""), quote=True)


def _slugify(text: str, max_len: int = 60) -> str:
    """Título → slug ASCII en minúsculas ('Sony WH-1000XM6 …' → 'sony-wh-1000xm6')."""
    norm = unicodedata.normalize("NFKD", text or "")
    ascii_text = norm.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:max_len].rstrip("-") or "oferta").lower()


def _deal_slug(deal: dict) -> str:
    """Slug único por oferta: título legible + cola del ID (anti-colisión)."""
    tail = "".join(c for c in str(deal.get("deal_id", "")) if c.isalnum())[-8:].lower()
    return f"{_slugify(deal.get('title', ''))}-{tail}"


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    f = float(value)
    return f"${int(f):,}" if f.is_integer() else f"${f:,.2f}"


def _pub_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return format_datetime(dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt)
    except (ValueError, TypeError):
        return format_datetime(datetime.now(timezone.utc))


def _disp_date(iso: str) -> str:
    """Fecha corta para humanos: '09/11/2026 02:41'."""
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return (iso or "")[:16].replace("T", " ")


def _json_ld(deal: dict, aff_url: str, currency: str) -> str:
    """Schema.org Product + Offer: es lo que Google usa para el 'rich snippet'."""
    ld: dict = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": deal.get("title", "Oferta"),
        "offers": {
            "@type": "Offer",
            "price": f"{float(deal['price']):.2f}" if deal.get("price") else None,
            "priceCurrency": currency,
            "url": aff_url,
            "availability": "https://schema.org/InStock",
        },
    }
    if deal.get("rating") and deal.get("reviews"):
        ld["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": float(deal["rating"]),
            "reviewCount": int(deal["reviews"]),
        }
    if deal.get("brand"):
        ld["brand"] = {"@type": "Brand", "name": deal["brand"]}
    if deal.get("image_url"):
        ld["image"] = deal["image_url"]
    ld["offers"] = {k: v for k, v in ld["offers"].items() if v}
    return json.dumps(ld, ensure_ascii=False)


# ----------------------------------------------------------------- páginas --

_CSS = """
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--txt:#e6edf3;--dim:#8b949e;
--acc:#f78166;--ok:#3fb950;--link:#58a6ff}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--txt)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:880px;margin:0 auto;padding:20px 16px 48px}
header.site{border-bottom:1px solid var(--line);padding:18px 0;margin-bottom:22px}
header.site h1{margin:0 0 4px;font-size:1.5rem}
header.site p{margin:0;color:var(--dim)}
.cta-tg{display:inline-block;margin-top:10px;background:var(--ok);color:#041209;
font-weight:700;padding:8px 14px;border-radius:8px}
.cta-tg:hover{text-decoration:none;filter:brightness(1.1)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin:14px 0}
.badge{display:inline-block;background:var(--acc);color:#180300;font-weight:800;
border-radius:7px;padding:2px 9px;font-size:.9rem}
h2.deal{margin:8px 0 4px;font-size:1.12rem}
h2.deal a{color:var(--txt)}
.price{font-size:1.25rem;font-weight:800;color:var(--ok)}
.old{color:var(--dim);text-decoration:line-through;margin-left:8px}
.meta{color:var(--dim);font-size:.9rem;margin-top:6px}
.buy{display:inline-block;margin-top:10px;background:var(--acc);color:#180300;
font-weight:800;padding:9px 16px;border-radius:8px}
.buy:hover{text-decoration:none;filter:brightness(1.08)}
.btn-amz{display:inline-block;margin-top:14px;background:var(--acc);color:#180300;
font-weight:800;padding:12px 22px;border-radius:9px;font-size:1.05rem}
.btn-amz:hover{text-decoration:none;filter:brightness(1.08)}
.info{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px 18px;margin:16px 0;color:var(--dim);font-size:.92rem}
.info b{color:var(--txt)}
footer{margin-top:34px;color:var(--dim);font-size:.85rem;border-top:1px solid
var(--line);padding-top:14px}
""".strip()


def _head(title: str, description: str, base: str, page_url: str | None,
          feed: bool = False) -> str:
    canonical = f'\n  <link rel="canonical" href="{esc(page_url)}">' if page_url else ""
    feed_line = ('\n  <link rel="alternate" type="application/rss+xml" '
                 'title="RSS de ofertas" href="feed.xml">') if feed else ""
    return (
        f'<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{esc(title)}</title>\n'
        f'<meta name="description" content="{esc(description[:160])}">{canonical}{feed_line}\n'
        f'<link rel="stylesheet" href="style.css">'
    )


def _header_html(cfg) -> str:
    tg = cfg.telegram_channel_url
    cta = (f'<a class="cta-tg" href="{esc(tg)}" rel="noopener">🚀 Únete al canal '
           f'de Telegram — ofertas antes que caduquen</a>') if tg else ""
    return (
        '<header class="site">'
        f'<h1>⚡ {esc(cfg.site_title)}</h1>'
        f'<p>Ofertas de {esc(cfg.amazon_domain)} verificadas por un analista de IA: '
        'descuentos REALES (no precios inflados), valoración mínima 4.0★ y '
        'descarte de réplicas y fraudes.</p>'
        f'{cta}</header>'
    )


def _footer_html(cfg) -> str:
    return (
        '<footer>'
        '🏷️ Este sitio contiene enlaces de afiliado de Amazon: si compras a través '
        'de ellos recibimos una comisión sin coste adicional para ti. '
        'Los precios cambian o caducan: verifica el precio final en Amazon.<br>'
        f'🤖 Generado automáticamente por {esc(cfg.site_title)} · '
        f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC'
        '</footer>'
    )


def _deal_card(deal: dict, base: str) -> str:
    slug = _deal_slug(deal)
    page = f"{base}/p/{slug}.html"
    cur, lst = _fmt_price(deal.get("price")), _fmt_price(deal.get("list_price"))
    discount = deal.get("discount")
    badge = (f'<span class="badge">-{float(discount):.0f}%</span>'
             if discount else '<span class="badge">OFERTA</span>')
    rating = ""
    if deal.get("rating"):
        reviews = f" · {int(deal['reviews']):,} reseñas" if deal.get("reviews") else ""
        rating = (f'<div class="meta">⭐ {deal["rating"]}★{reviews} · 🕒 '
                  f'{_disp_date(deal.get("published_at", ""))}</div>')
    return (
        f'<div class="card">{badge}'
        f'<h2 class="deal"><a href="p/{slug}.html">{esc(deal.get("title", ""))}</a></h2>'
        f'<div><span class="price">{esc(cur)}</span>'
        f'<span class="old">{esc(lst)}</span></div>'
        f'{rating}'
        f'<a class="buy" href="{esc(deal.get("aff_url") or deal.get("url",""))}" '
        f'rel="nofollow sponsored" target="_blank">Ver en Amazon →</a>'
        f'</div>'
    )


def _deal_page(deal: dict, cfg, base: str) -> str:
    slug = _deal_slug(deal)
    page_url = f"{base}/p/{slug}.html"
    aff = deal.get("aff_url") or deal.get("url", "")
    cur, lst = _fmt_price(deal.get("price")), _fmt_price(deal.get("list_price"))
    discount = deal.get("discount")
    pct = f"{float(discount):.0f}% OFF" if discount else "OFERTÓN"
    body = (deal.get("verdict_msg") or "").strip()
    rating_html = ""
    if deal.get("rating"):
        reviews = f" · {int(deal['reviews']):,} reseñas" if deal.get("reviews") else ""
        rating_html = f'<div class="meta">⭐ {deal["rating"]}★{reviews}</div>'
    when = _disp_date(deal.get("published_at", ""))
    min_disc = f"{cfg.min_discount:.0f}"
    min_rat = f"{cfg.min_rating:g}"

    tg = cfg.telegram_channel_url
    tg_cta = (f'<a class="cta-tg" href="{esc(tg)}" rel="noopener">📡 Recibe ofertas '
              'en Telegram antes de que caduquen</a>') if tg else ""

    return f'''<!DOCTYPE html>
<html lang="es">
<head>
{_head(f'{pct}: {deal.get("title", "Oferta")[:60]} · {esc(cur)}',
       body or f"{pct} en {cfg.amazon_domain}: {cur} antes {lst}. Verificado por IA.",
       base, page_url).replace('href="style.css"', 'href="../style.css"')}
</head>
<body><div class="wrap">
{_header_html(cfg)}
<article class="card">
  <span class="badge">{esc(pct)}</span>
  <h2 class="deal">{esc(deal.get("title", ""))}</h2>
  <div><span class="price">{esc(cur)}</span><span class="old">{esc(lst)}</span></div>
  {rating_html}
  <div class="meta">🕒 Detectado y verificado el {esc(when)} UTC · marca: {esc(deal.get("brand") or "—")}</div>
  <p>{esc(body)}</p>
  <a class="btn-amz" href="{esc(aff)}" rel="nofollow sponsored" target="_blank">
    💸 Ver precio en {esc(cfg.amazon_domain)} →</a>
</article>
<div class="info">
  <b>¿Por qué es una oferta verificada?</b> DealFlash compara el precio actual
  contra el precio de lista, exige un descuento real ≥ {esc(min_disc)}%,
  valoración ≥ {esc(min_rat)}★ con reseñas suficientes y descarta
  réplicas, productos sin marca y señales de fraude antes de publicarlo.
  {tg_cta}
</div>
{_footer_html(cfg)}
</div>
<script type="application/ld+json">{_json_ld(deal, aff, cfg.currency)}</script>
</body></html>'''


def _index_page(deals: list[dict], cfg, base: str) -> str:
    cards = "\n".join(_deal_card(d, base) for d in deals) or (
        '<div class="card">Aún no hay ofertas publicadas. DealFlash está '
        'esperando la próxima oferta verificada…</div>'
    )
    return f'''<!DOCTYPE html>
<html lang="es">
<head>
{_head(f'{cfg.site_title} — ofertas verificadas de {cfg.amazon_domain}',
       'Descuentos reales ≥ 20% verificados por IA. Sin precios inflados, '
       'sin réplicas, sin fraudes.', base, base, feed=True)}
</head>
<body><div class="wrap">
{_header_html(cfg)}
{cards}
<div class="info">📄 <a href="feed.xml">Suscríbete por RSS</a> · cada ficha lleva
sello de hora porque <b>los precios caducan</b>.</div>
{_footer_html(cfg)}
</div></body></html>'''


def _rss(deals: list[dict], cfg, base: str) -> str:
    items = []
    for d in deals:
        title = f"{d.get('title', 'Oferta')} — {_fmt_price(d.get('price'))}"
        desc = (d.get("verdict_msg") or "").strip()[:300] or f"Descuento verificado en {cfg.amazon_domain}"
        items.append(
            f"<item><title>{esc(title)}</title>"
            f'<link>{esc(d.get("aff_url") or d.get("url",""))}</link>'
            f'<guid isPermaLink="false">{esc(d.get("deal_id",""))}</guid>'
            f"<pubDate>{_pub_date(d.get('published_at',''))}</pubDate>"
            f"<description>{esc(desc)}</description></item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0"><channel>'
        f"<title>{esc(cfg.site_title)}</title>"
        f"<link>{esc(base)}</link>"
        f"<description>Ofertas verificadas de {esc(cfg.amazon_domain)} con IA: "
        'descuentos reales, sin réplicas ni fraude.</description>'
        f"<language>es</language>"
        f"{''.join(items)}</channel></rss>"
    )


def _sitemap(deals: list[dict], cfg, base: str) -> str:
    urls = [base]
    for d in deals:
        urls.append(f"{base}/p/{_deal_slug(d)}.html")
    body = "".join(
        f"<url><loc>{esc(u)}</loc>"
        f"<lastmod>{datetime.now(timezone.utc).strftime('%Y-%m-%d')}</lastmod></url>"
        for u in urls
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f"{body}</urlset>")


# ------------------------------------------------------------------ genera --

def generate_site(cfg, store) -> Path:
    """Regenera el sitio completo a partir del snapshot de ofertas publicadas."""
    base = cfg.site_base_url.rstrip("/")
    deals = store.published_deals(cfg.site_max_deals)
    out = Path(cfg.site_dir)
    (out / "p").mkdir(parents=True, exist_ok=True)

    (out / "style.css").write_text(_CSS, encoding="utf-8")
    (out / "index.html").write_text(_index_page(deals, cfg, base), encoding="utf-8")
    (out / "feed.xml").write_text(_rss(deals, cfg, base), encoding="utf-8")
    (out / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8"
    )
    if cfg.site_base_url and cfg.site_base_url != "http://localhost:8000":
        (out / "sitemap.xml").write_text(_sitemap(deals, cfg, base), encoding="utf-8")

    for deal in deals:
        (out / "p" / f"{_deal_slug(deal)}.html").write_text(
            _deal_page(deal, cfg, base), encoding="utf-8"
        )

    # Limpia fichas de ofertas que ya no están en la ventana de N publicados
    keep = {f"{_deal_slug(d)}.html" for d in deals}
    for old in (out / "p").glob("*.html"):
        if old.name not in keep:
            old.unlink()

    log.info("Sitio de captación: %d fichas + portada + RSS en %s", len(deals), out)
    return out
