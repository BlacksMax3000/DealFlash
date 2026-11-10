"""Cliente LLM multi-proveedor con cadena de fallback (100 % free tier).

Cadena: Gemini → Groq → OpenRouter → reglas locales (sin IA, nunca falla).

Los tres proveedores exponen formato /chat/completions compatible con OpenAI
(Google ofrece el endpoint /v1beta/openai/), así que un solo cliente sirve
para todos; lo único que cambia es base_url y el modelo (preset).

Política de degradación (por ciclo):
  - HTTP 401/402/403 (clave inválida o sin saldo)  → el proveedor se desactiva
    de inmediato para el resto del ciclo.
  - Otros errores (timeout, 5xx, 429…)             → 2 análisis fallidos seguidos
    desactivan el proveedor por el resto del ciclo.
  - Si TODOS fallan o no hay claves               → reglas locales (modo sin IA).
Un proveedor que falla NUNCA corta el ciclo: se pasa al siguiente hasta generar
el veredicto y publicar.

Free tiers (verificados con llamadas reales, nov. 2025):
  - Gemini:     gemini-3.8-flash vía endpoint OpenAI-compatible de AI Studio.
                OJO: gemini-2.5-flash ya NO está disponible para claves nuevas.
  - Groq:       llama-3.3-70b-versatile · 30 RPM · 1.000 req/día
  - OpenRouter: modelos ":free" · 20 RPM · 50 req/día (1.000/día con ≥10 USD
                cargados una vez). nemotron-lightning "razona" antes de responder:
                necesita max_tokens alto (2000) o devolverá contenido vacío.

REPO: radar/analysis/llm_client.py (archivo NUEVO; glm_client.py queda obsoleto)
"""

from __future__ import annotations

import json
import logging
import re

import requests

from .prompt import SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger("radar.llm")


class LLMError(RuntimeError):
    """Error de llamada o de respuesta de un proveedor LLM."""

    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON balanceado (tolera ```json``` y texto extra)."""
    if not text:
        raise LLMError("respuesta vacía del modelo")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMError("la respuesta no contiene JSON")
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"JSON inválido: {exc}") from exc


# ---------------------------------------------------------------------------
# Presets por proveedor (config.yaml puede sobreescribir cualquier valor)
# ---------------------------------------------------------------------------
PRESETS: dict[str, dict] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.8-flash",     # 2.5 ya no se emite a claves nuevas
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 900,
        "extra_headers": {},
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",   # 1.000 req/día en free tier
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 900,
        "extra_headers": {},
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3.5-lightning:free",
        "json_mode": False,   # muchos modelos free no aceptan response_format
        "temperature": 0.2,
        "max_tokens": 2000,   # el modelo razona (~1.200 tokens) antes de responder
        "extra_headers": {    # recomendados por OpenRouter (atribución)
            "HTTP-Referer": "https://github.com/radar-de-ofertas",
            "X-Title": "Radar de Ofertas",
        },
    },
}


def _build_provider(provider_key: str, user_cfg: dict | None) -> dict:
    """Fusiona el preset del proveedor con la configuración del usuario."""
    p = dict(PRESETS[provider_key])
    uc = user_cfg or {}
    p["base_url"] = str(uc.get("base_url") or p["base_url"]).rstrip("/")
    model = uc.get("model") or uc.get("modelo")
    if model:
        p["model"] = str(model)
    p["temperature"] = float(uc.get("temperature", p["temperature"]))
    p["max_tokens"] = int(uc.get("max_tokens", p["max_tokens"]))
    if "json_mode" in uc:
        p["json_mode"] = bool(uc["json_mode"])
    return p


class LLMAnalyzer:
    """Un proveedor LLM (Gemini, Groq u OpenRouter) con reintentos."""

    def __init__(self, name: str, api_key: str, provider_key: str,
                 user_cfg: dict | None = None):
        self.name = name
        self.api_key = api_key
        self.provider_key = provider_key
        self.p = _build_provider(provider_key, user_cfg)
        self.demoted = False          # desactivado para el resto del ciclo
        self.fallos_ciclo = 0         # análisis fallidos consecutivos (ciclo)
        self.last_status: int | None = None

    # ------------------------------------------------------------------ API --
    def analyze(self, deal) -> dict:
        """Devuelve el veredicto JSON del modelo; ante fallo, veredicto negativo."""
        user = build_user_prompt(deal)
        correction = (
            "\n\nAVISO: tu respuesta anterior no fue un JSON válido. "
            "Responde EXCLUSIVAMENTE con el objeto JSON del esquema."
        )
        last_err: Exception | None = None
        for attempt in (1, 2):
            try:
                content = self._chat(SYSTEM_PROMPT, user + (correction if attempt == 2 else ""))
                verdict = extract_json(content)
                out = self._normalize(verdict)
                out["provider"] = self.name
                self.fallos_ciclo = 0
                self.last_status = None
                return out
            except (LLMError, requests.RequestException) as exc:
                last_err = exc
                self.last_status = getattr(exc, "status", None)
                log.warning("[%s] intento %d falló para %s: %s",
                            self.name, attempt, deal.id, exc)

        log.error("[%s] análisis imposible para %s (%s)", self.name, deal.id, last_err)
        return {
            "approved": False,
            "real_discount_pct": None,
            "score": 0,
            "flags": ["error_analisis"],
            "reason": f"error de análisis: {str(last_err)[:100]}",
            "message": "",
            "provider": self.name,
        }

    def _chat(self, system: str, user: str) -> str:
        body: dict = {
            "model": self.p["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.p["temperature"],
            "max_tokens": self.p["max_tokens"],
        }
        if self.p.get("json_mode"):
            body["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Language": "en-US,en",
        }
        headers.update(self.p.get("extra_headers") or {})

        resp = requests.post(
            f"{self.p['base_url']}/chat/completions",
            headers=headers,
            json=body,
            timeout=120,
        )
        if resp.status_code != 200:
            raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}", status=resp.status_code)
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise LLMError(f"estructura de respuesta inesperada: {resp.text[:200]}") from exc
        if not content:
            # Típico de modelos que agotan max_tokens "razonando" sin responder
            raise LLMError(f"contenido vacío: {resp.text[:200]}")
        return content

    # -------------------------------------------------------------- normal. --
    @staticmethod
    def _normalize(verdict: dict) -> dict:
        out = {
            "approved": bool(verdict.get("approved") is True),
            "real_discount_pct": verdict.get("real_discount_pct"),
            "score": float(verdict.get("score") or 0),
            "flags": [str(f) for f in (verdict.get("flags") or [])],
            "reason": str(verdict.get("reason") or "")[:200],
            "message": str(verdict.get("message") or "").strip(),
        }
        try:
            out["score"] = round(out["score"], 1)
        except (TypeError, ValueError):
            out["score"] = 0.0
        return out


class ChainedAnalyzer:
    """Ejecuta la cadena de proveedores con degradación; las reglas locales
    son el suelo que garantiza que SIEMPRE hay veredicto."""

    DEMOTE_HTTP = {401, 402, 403}          # clave inválida / sin saldo / prohibido

    def __init__(self, chain: list[LLMAnalyzer], local):
        self.chain = chain
        self.local = local

    def analyze(self, deal) -> dict:
        for a in self.chain:
            if a.demoted:
                continue
            verdict = a.analyze(deal)
            if "error_analisis" not in verdict.get("flags", []):
                a.fallos_ciclo = 0
                return verdict

            if a.last_status in self.DEMOTE_HTTP:
                a.demoted = True
                log.warning("🚪 [%s] desactivado el resto del ciclo: HTTP %s (¿clave o saldo?)",
                            a.name, a.last_status)
                continue

            a.fallos_ciclo += 1
            if a.fallos_ciclo >= 2:
                a.demoted = True
                log.warning("🚪 [%s] desactivado el resto del ciclo: %d fallos seguidos",
                            a.name, a.fallos_ciclo)

        # Suelo: reglas locales (sin IA) — nunca falla ni necesita red de IA
        verdict = self.local.analyze(deal)
        verdict["provider"] = "reglas-locales"
        return verdict
