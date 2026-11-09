"""Cliente de la API de Z.ai (GLM-5) + analizador con reintentos y fail-closed.

Endpoint real verificado: POST https://api.z.ai/api/paas/v4/chat/completions
Auth: Bearer <ZAI_API_KEY>. Salida forzada a JSON con response_format.
Política fail-closed: si el análisis falla, la oferta NO se publica.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from .prompt import SYSTEM_PROMPT, build_user_prompt

log = logging.getLogger("radar.glm")


class GLMError(RuntimeError):
    pass


def extract_json(text: str) -> dict:
    """Extrae el primer objeto JSON balanceado de una respuesta (tolera ```json```)."""
    if not text:
        raise GLMError("respuesta vacía del modelo")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GLMError("la respuesta no contiene JSON")
    blob = t[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError as exc:
        raise GLMError(f"JSON inválido: {exc}") from exc


class GLMAnalyzer:
    def __init__(self, api_key: str, glm_cfg: dict):
        self.api_key = api_key
        self.g = glm_cfg

    # ------------------------------------------------------------------ API --
    def analyze(self, deal) -> dict:
        """Devuelve el veredicto JSON del modelo; ante fallo, veredicto negativo."""
        user = build_user_prompt(deal)
        correction = (
            "\n\nAVISO: tu respuesta anterior no fue un JSON válido. "
            "Responde EXCLUSIVAMENTE con el objeto JSON del esquema."
        )
        last_err: Exception | None = None
        for attempt in range(1, 3):
            try:
                content = self._chat(SYSTEM_PROMPT, user + (correction if attempt == 2 else ""))
                verdict = extract_json(content)
                return self._normalize(verdict)
            except (GLMError, requests.RequestException) as exc:
                last_err = exc
                log.warning("GLM intento %d falló para %s: %s", attempt, deal.id, exc)

        log.error("Análisis GLM imposible para %s (%s) — fail-closed, no se publica", deal.id, last_err)
        return {
            "approved": False,
            "real_discount_pct": None,
            "score": 0,
            "flags": ["error_analisis"],
            "reason": f"error de análisis: {str(last_err)[:80]}",
            "message": "",
        }

    def _chat(self, system: str, user: str) -> str:
        body = {
            "model": self.g["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.g["temperature"],
            "max_tokens": self.g["max_tokens"],
            "response_format": {"type": "json_object"},
            "thinking": {"type": self.g["thinking"]},
        }
        resp = requests.post(
            f"{self.g['base_url']}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept-Language": "en-US,en",
            },
            json=body,
            timeout=120,
        )
        if resp.status_code != 200:
            raise GLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GLMError(f"estructura de respuesta inesperada: {str(data)[:200]}") from exc
        if not content:
            raise GLMError(f"contenido vacío: {str(data)[:200]}")
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
