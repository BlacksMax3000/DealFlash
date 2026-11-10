"""Cliente LLM multi-proveedor con cadena de fallback (100 % free tier).

Cadena: Gemini → Groq → OpenRouter → reglas locales (sin IA, nunca falla).

Los tres proveedores exponen formato /chat/completions compatible con OpenAI
(Google ofrece el endpoint /v1beta/openai/), así que un solo cliente sirve
para todos; lo único que cambia es base_url y el modelo (preset).

Política de degradación (por ciclo):
  - HTTP 401/402/403 (clave inválida o sin saldo)  → el proveedor se desactiva
    de inmediato para el resto del ciclo.
  - HTTP 404 model_not_found / contenido vacío     → cambia automáticamente al
    siguiente modelo de su lista (los modelos free se retiran a menudo).
  - Otros errores (timeout, 5xx, 429…)             → 2 análisis fallidos seguidos
    desactivan el proveedor por el resto del ciclo.
  - Si TODOS fallan o no hay claves               → reglas locales (modo sin IA).
Un proveedor que falla NUNCA corta el ciclo: se pasa al siguiente hasta generar
el veredicto y publicar.

Modelos (revisado nov. 2026; cada preset trae fallbacks por si retiran uno):
  - Gemini:     gemini-3.8-flash vía endpoint OpenAI-compatible de AI Studio.
                OJO: gemini-2.5-flash ya NO se emite a claves nuevas.
  - Groq:       openai/gpt-oss-120b · 30 RPM · 1.000 req/día. OJO:
                llama-3.3-70b-versatile fue RETIRADO el 16/08/2026 (HTTP 404).
                Fallbacks: llama-3.1-8b-instant (14.400 req/día) y
                moonshotai/kimi-k2-instruct.
  - OpenRouter: google/gemma-4-31b-it:free (NO "razona": responde directo).
                nemotron-lightning se descartó: agotaba max_tokens razonando y
                devolvía contenido vacío. Fallbacks: openrouter/free (router
                automático de modelos free) y nemotron-3.5-super-vl.
                Modelos ":free" · 20 RPM · 50 req/día (1.000/día con ≥10 USD
                cargados una vez).
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
        "model_fallbacks": ["gemini-3.8-flash-lite"],
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 900,
        "extra_headers": {},
        "extra_body_by_model": {},
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        # llama-3.3-70b-versatile fue RETIRADO el 16/08/2026 (HTTP 404).
        "model": "openai/gpt-oss-120b",       # 30 RPM · 1.000 req/día (free)
        "model_fallbacks": [
            "llama-3.1-8b-instant",           # 30 RPM · 14.400 req/día (free)
            "moonshotai/kimi-k2-instruct",    # 60 RPM · 1.000 req/día (free)
        ],
        "json_mode": True,
        "temperature": 0.2,
        "max_tokens": 1600,
        "extra_headers": {},
        # gpt-oss "razona" antes de responder: esfuerzo bajo para no agotar el
        # presupuesto de tokens (los presets llama no aceptan este campo).
        "extra_body_by_model": {"openai/gpt-oss-120b": {"reasoning_effort": "low"}},
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        # gemma NO "razona": responde directo. nemotron-lightning se descartó:
        # agotaba max_tokens razonando y devolvía contenido vacío.
        "model": "google/gemma-4-31b-it:free",
        "model_fallbacks": [
            "openrouter/free",                     # router automático de free
            "nvidia/nemotron-3.5-super-vl:free",
        ],
        "json_mode": False,   # muchos modelos free no aceptan response_format
        "temperature": 0.2,
        "max_tokens": 2000,
        "extra_headers": {    # recomendados por OpenRouter (atribución)
            "HTTP-Referer": "https://github.com/BlacksMax3000/DealFlash",
            "X-Title": "DealFlash",
        },
        "extra_body_by_model": {
            # los nemotron razonan: esfuerzo bajo y sin incluir el razonamiento
            "nvidia/nemotron-3.5-super-vl:free": {
                "reasoning": {"effort": "low", "exclude": True},
            },
        },
    },
}


def _build_provider(provider_key: str, user_cfg: dict | None) -> dict:
    """Fusiona el preset del proveedor con la configuración del usuario.

    Deja siempre una lista ``models``: modelo principal + fallbacks
    (config.yaml puede fijar el principal con ``model:``).
    """
    p = dict(PRESETS[provider_key])
    uc = user_cfg or {}
    p["base_url"] = str(uc.get("base_url") or p["base_url"]).rstrip("/")
    model = uc.get("model") or uc.get("modelo")
    if model:
        p["model"] = str(model)
    fallbacks = list(p.get("model_fallbacks") or [])
    p["models"] = [str(p["model"])] + [str(m) for m in fallbacks]
    p["temperature"] = float(uc.get("temperature", p["temperature"]))
    p["max_tokens"] = int(uc.get("max_tokens", p["max_tokens"]))
    if "json_mode" in uc:
        p["json_mode"] = bool(uc["json_mode"])
    return p


class LLMAnalyzer:
    """Un proveedor LLM (Gemini, Groq u OpenRouter) con reintentos y con
    lista propia de modelos de reserva."""

    def __init__(self, name: str, api_key: str, provider_key: str,
                 user_cfg: dict | None = None):
        self.name = name
        self.api_key = api_key
        self.provider_key = provider_key
        self.p = _build_provider(provider_key, user_cfg)
        self.models: list[str] = list(self.p["models"])
        self.model_idx = 0            # posición actual en la lista de modelos
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
                model = self.models[self.model_idx]
                content = self._chat(model, SYSTEM_PROMPT,
                                     user + (correction if attempt == 2 else ""))
                verdict = extract_json(content)
                out = self._normalize(verdict)
                out["provider"] = self.name
                self.fallos_ciclo = 0
                self.last_status = None
                return out
            except (LLMError, requests.RequestException) as exc:
                last_err = exc
                self.last_status = getattr(exc, "status", None)
                log.warning("[%s] intento %d falló para %s (%s): %s",
                            self.name, attempt, deal.id,
                            self.models[self.model_idx], exc)
                if (self._debe_cambiar_modelo(exc)
                        and self.model_idx < len(self.models) - 1):
                    self.model_idx += 1
                    log.warning("🔄 [%s] modelo retirado o sin respuesta → cambio a '%s'",
                                self.name, self.models[self.model_idx])

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

    @staticmethod
    def _debe_cambiar_modelo(exc: Exception) -> bool:
        """El fallo apunta a un modelo inexistente o que no devolvió texto."""
        if isinstance(exc, LLMError):
            if exc.status == 404:
                return True
            txt = str(exc)
            return ("contenido vacío" in txt or "model_not_found" in txt
                    or "does not exist" in txt)
        return False

    def _chat(self, model: str, system: str, user: str) -> str:
        body: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.p["temperature"],
            "max_tokens": self.p["max_tokens"],
        }
        if self.p.get("json_mode"):
            body["response_format"] = {"type": "json_object"}
        extra = (self.p.get("extra_body_by_model") or {}).get(model)
        if extra:
            body.update(extra)

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
