"""Orquestador del Radar de Ofertas.

Uso:
    python -m radar.main                 # ciclo real (recolecta → filtra → valida → publica)
    python -m radar.main --dry-run       # flujo real pero NO publica en Telegram
    python -m radar.main --demo          # datos de ejemplo + veredictos simulados (sin claves)
    python -m radar.main --collect-only  # solo recolecta y muestra candidatas
    python -m radar.main --limit 5 -v    # procesa 5 candidatas con logs de depuración

Validación con fallback (100 % free tier): Gemini → Groq → OpenRouter → reglas
locales. GLM/z.ai quedó DESCARTADO (requiere créditos). Se usa el primer
proveedor con clave; si uno falla (clave, saldo, caída) se desactiva por el
ciclo y pasa al siguiente — nunca se corta el ciclo. Sin ninguna clave
funciona igual con reglas estrictas locales (no necesita ninguna API).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import demo as demo_mod
from .analysis.llm_client import ChainedAnalyzer, LLMAnalyzer
from .analysis.local_validator import RulesAnalyzer
from .analysis.rules import hard_filter
from .collectors import amazon_product, amazon_search, rss_feeds
from .config import load_config, require_env
from .models import Deal
from .publish import fanout, telegram
from .publish import web as web_pub
from .publish.affiliate import build_affiliate_link
from .publish.compose import compose_message, compose_plain
from .storage.store import SeenStore
from .utils import http_session, polite_sleep, setup_logging

log = logging.getLogger("radar.main")


# ------------------------------------------------------------ recolección --

def gather_deals(cfg, session) -> list[Deal]:
    """Recolecta crudo de todas las fuentes activas, sin duplicados por ID."""
    deals: list[Deal] = []
    if cfg.rss_enabled:
        deals += rss_feeds.collect(cfg, session)
    if cfg.search_enabled:
        deals += amazon_search.collect(cfg, session)

    unique: list[Deal] = []
    seen: set[str] = set()
    for deal in deals:
        if deal.id not in seen:
            seen.add(deal.id)
            unique.append(deal)
    return unique


def enrich_deals(cfg, session, deals: list[Deal]) -> list[Deal]:
    """Descarga la página de producto de cada candidata para datos duros."""
    if not cfg.enrich_enabled:
        return deals
    for deal in deals:
        amazon_product.enrich(deal, cfg, session)
        # Amazon aplica throttling agresivo: pausa más larga que en el resto de fuentes
        polite_sleep(max(cfg.http_delay, 2.5))
    return deals


# Motivos que el ENRIQUECIMIENTO puede curar (falta de datos, no datos malos):
PARKABLE = {"sin_precio", "sin_datos_descuento"}


def apply_rules(cfg, store: SeenStore, deals: list[Deal],
                mark_parkable: bool = False) -> tuple[list[Deal], list[Deal]]:
    """Filtro duro en dos niveles.

    - Descarte definitivo: se registra en la BD con su motivo.
    - Aparcadas (sin precio / sin descuento): NO se marcan todavía porque la
      página de producto de Amazon podría aportarles los datos que faltan.
    Devuelve (pasan, aparcadas).
    """
    passing: list[Deal] = []
    parked: list[Deal] = []
    for deal in deals:
        ok, motivo = hard_filter(deal, cfg)
        if ok:
            passing.append(deal)
        elif motivo in PARKABLE and not mark_parkable:
            log.info("⏸ [%s] aparca (esperando enriquecimiento): %s", deal.id, motivo)
            parked.append(deal)
        else:
            log.info("⛔ [%s] descartada por reglas: %s", deal.id, motivo)
            store.mark(deal, "rule_dropped")
    return passing, parked


# --------------------------------------------------------------- pipeline --

# Cadena de proveedores IA con fallback (orden = prioridad). 100 % free tier.
# GLM (z.ai) quedó descartado: requiere créditos.
# Cada tupla: nombre visible, variable de entorno (secret), clave de config.yaml
IA_PROVIDERS: tuple[tuple[str, str, str], ...] = (
    ("Gemini", "GEMINI_API_KEY", "gemini"),
    ("Groq", "GROQ_API_KEY", "groq"),
    ("OpenRouter", "OPENROUTER_API_KEY", "openrouter"),
)


def build_analyzer(cfg):
    """Construye la cadena de validación según las claves disponibles.

    Con claves: Gemini → Groq → OpenRouter → reglas locales (suelo garantizado).
    Sin ninguna clave: reglas locales (modo sin IA, cero APIs).
    """
    chain = []
    for nombre, env_var, clave_cfg in IA_PROVIDERS:
        key = os.getenv(env_var, "").strip()
        if key:
            chain.append(LLMAnalyzer(nombre, key, clave_cfg, cfg.get(clave_cfg, {}) or {}))

    local = RulesAnalyzer(cfg)
    if not chain:
        log.info("🧭 MODO SIN IA: ninguna API de IA configurada — validación 100%% local por reglas")
        return local
    log.info("🧠 Cadena de validación IA: %s → reglas locales", " → ".join(a.name for a in chain))
    return ChainedAnalyzer(chain, local)


def run_pipeline(cfg, args) -> int:
    session = http_session()
    store = SeenStore(cfg.db_path)

    # --- Modo y credenciales -------------------------------------------------
    if args.demo:
        log.info("🧪 MODO DEMO: datos de ejemplo y veredictos simulados (no se toca la red de Amazon)")
        analyzer = demo_mod.FakeAnalyzer()
        deals = demo_mod.demo_deals()
    else:
        analyzer = build_analyzer(cfg)
        deals = gather_deals(cfg, session)
        if not deals:
            log.warning("Ningún recolector devolvió candidatas — revisa config.yaml o los avisos anteriores")

    publishing = not (args.dry_run or args.demo)
    if args.dry_run:
        log.info("🏃 DRY-RUN: no se publicará nada en Telegram")
    if publishing:
        token = require_env("TELEGRAM_BOT_TOKEN")
        chat_id = require_env("TELEGRAM_CHAT_ID")
        me = telegram.get_me(token, session)
        log.info("🤖 Bot verificado: @%s → canal %s", me.get("username"), chat_id)

    # --- Deduplicación + filtro duro ----------------------------------------
    nuevas = [d for d in deals if store.is_new(d.id)]
    log.info("Candidatas: %d recibidas · %d nuevas (no vistas antes)", len(deals), len(nuevas))

    cap = cfg.max_candidates if args.limit is None else args.limit
    passing, parked = apply_rules(cfg, store, nuevas)
    if args.demo:  # en demo no hay enriquecimiento: las aparcadas son descartes finales
        for deal in parked:
            log.info("⛔ [%s] descartada por reglas: datos incompletos", deal.id)
            store.mark(deal, "rule_dropped")
        parked = []
    candidates = (passing + parked)[:cap]

    # --- Enriquecimiento con datos reales de Amazon ---------------------------
    if not args.demo and candidates:
        candidates = enrich_deals(cfg, session, candidates)
        candidates, _ = apply_rules(cfg, store, candidates, mark_parkable=True)  # veredicto final con datos duros

    log.info("Tras filtro duro + enriquecimiento: %d candidatas para análisis", len(candidates))

    # --- Validación (cadena IA o reglas) + publicación ------------------------
    stats = {"analizadas": 0, "aprobadas": 0, "publicadas": 0}

    for deal in candidates:
        if stats["publicadas"] >= cfg.max_posts:
            log.info("Límite de publicación por ciclo alcanzado (%d) — el resto esperará al próximo", cfg.max_posts)
            break

        stats["analizadas"] += 1
        verdict = analyzer.analyze(deal)
        via = verdict.get("provider", "—")

        flags = ", ".join(verdict["flags"]) or "sin alertas"
        log.info("🔎 [%s] vía %s · score %.1f · %s · %s", deal.id, via, verdict["score"],
                 "APROBADA" if verdict["approved"] else "RECHAZADA", flags)

        if not verdict["approved"]:
            if "error_analisis" in verdict["flags"]:
                # Error transitorio: NO se marca como rechazada para que esta
                # candidata se reevalúe en el próximo ciclo.
                log.warning("[%s] error transitorio de análisis — se reintentará el próximo ciclo", deal.id)
            else:
                store.mark(deal, "rejected", verdict["score"])
            continue

        stats["aprobadas"] += 1
        aff_url = build_affiliate_link(deal, cfg.tag, cfg.amazon_domain)
        message = compose_message(deal, verdict, aff_url)

        if args.dry_run or args.demo:
            log.info("MENSAJE (no publicado):\n%s", message)
            if aff_url:
                log.info("Enlace de afiliado: %s", aff_url)
            plain = compose_plain(deal, verdict, aff_url)
            log.info("Versión captación social (≤300 chars): %s…", plain[:90])
        else:
            token = require_env("TELEGRAM_BOT_TOKEN")
            telegram.send_message(token, chat_id, message, session)
            log.info("🚀 Publicada en Telegram: %s", deal.id)

            # --- Prospección automática: reparte la oferta a todas las superficies
            captacion = fanout.fan_out(deal, verdict, aff_url, cfg, session, token, message)
            if captacion:
                ok = sum(1 for v in captacion.values() if v)
                detalle = ", ".join(f"{k}:{'✓' if v else '✗'}" for k, v in captacion.items())
                log.info("📡 Captación: %d/%d superficies OK · %s", ok, len(captacion), detalle)

            polite_sleep(cfg.post_pause)

        # Snapshot para el sitio de captación (también en demo/dry-run: vista previa)
        store.save_published(deal, verdict["score"], verdict.get("message"), aff_url)
        store.mark(deal, "published", verdict["score"])
        stats["publicadas"] += 1

    # --- Cierre ---------------------------------------------------------------
    # Sitio de captación (SEO): se regenera COMPLETO desde la BD, idempotente.
    if cfg.site_enabled and store.published_count():
        try:
            out = web_pub.generate_site(cfg, store)
            log.info("🌐 Sitio de captación listo en %s (portada + RSS + sitemap)", out)
        except Exception as exc:  # el sitio nunca debe tumbar el ciclo
            log.warning("No se pudo generar el sitio de captación: %s", exc)

    purged = store.purge(cfg.reject_ttl_days)
    _summary(store, stats, purged)
    store.close()
    return 0


def _summary(store: SeenStore, stats: dict, purged: int) -> None:
    log.info(
        "══ RESUMEN DEL CICLO ══ analizadas: %d · aprobadas: %d · publicadas: %d · "
        "rechazos purgados: %d · estado histórico: %s",
        stats["analizadas"], stats["aprobadas"], stats["publicadas"], purged, store.stats(),
    )


# ------------------------------------------------------------ collect-only --

def cmd_collect_only(cfg, limit: int | None) -> int:
    """Prueba de fuentes: recolecta, filtra y enriquece, pero no analiza ni publica."""
    session = http_session()
    deals = gather_deals(cfg, session)
    log.info("Recolectadas %d candidatas crudas", len(deals))

    store = SeenStore(cfg.db_path)
    passing, _ = apply_rules(cfg, store, deals)
    survivors = enrich_deals(cfg, session, passing[: (limit or 8)])
    survivors, _ = apply_rules(cfg, store, survivors, mark_parkable=True)

    log.info("─" * 78)
    for deal in survivors:
        log.info(
            "· %s | %s → %s | -%s%% | ⭐%s (%s res.) | %s",
            deal.id,
            deal.source,
            f"{deal.current_price:.2f}" if deal.current_price else "s/p",
            deal.discount_pct if deal.discount_pct is not None else "—",
            deal.rating if deal.rating is not None else "—",
            f"{deal.reviews:,}" if deal.reviews else "—",
            deal.title[:60],
        )
    log.info("─" * 78)
    store.close()
    return 0


# -------------------------------------------------------------------- CLI --

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="radar",
        description="Radar de Ofertas — bot de ofertas con GLM + Telegram (cero coste)",
    )
    parser.add_argument("--demo", action="store_true",
                        help="pipeline completo con datos de ejemplo, sin claves ni red")
    parser.add_argument("--dry-run", action="store_true",
                        help="flujo real (fuentes + GLM) pero sin publicar en Telegram")
    parser.add_argument("--collect-only", action="store_true",
                        help="solo recolecta, filtra y enriquece; muestra candidatas y sale")
    parser.add_argument("--limit", type=int, default=None,
                        help="máximo de candidatas a procesar en este ciclo")
    parser.add_argument("-v", "--verbose", action="store_true", help="logs de depuración")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    cfg = load_config()

    try:
        if args.collect_only:
            return cmd_collect_only(cfg, args.limit)
        return run_pipeline(cfg, args)
    except KeyboardInterrupt:
        log.warning("Interrumpido por el usuario")
        return 130


if __name__ == "__main__":
    sys.exit(main())
