"""LLM-Vorbewertung: Artikel -> strukturierte Signale (festes JSON-Schema)."""
from __future__ import annotations

import json
import logging
import re

import requests

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Du bist ein nüchterner Marktanalyst. Du bekommst eine Nachricht und bewertest, \
ob sie in den nächsten Tagen bis zu einer Woche eine Kursbewegung erwarten lässt.

Antworte NUR mit JSON in dieser Form:
{"signals": [{
  "level": "titel" | "segment" | "makro",
  "target": "Ticker oder Name (z. B. NVDA, KI-Halbleiter, DAX, Brent)",
  "region": "US" | "EU" | "DE" | "CN" | "JP" | "IN" | "EM" | "global",
  "direction": "long" | "short" | "neutral",
  "magnitude": 1-5,
  "horizon": "tage" | "woche",
  "confidence": 0.0-1.0,
  "surprise": 1-5,
  "rationale": "ein bis zwei Sätze, deutsch",
  "invalidation": "was die Einschätzung widerlegen würde",
  "related": ["Zweitrundeneffekte, z. B. Zulieferer oder Konkurrenten"]
}]}

Regeln:
- Keine Marktrelevanz -> {"signals": []}.
- magnitude: 1 = Rauschen, 3 = spürbar für den Wert, 5 = marktbewegend (CEO-Rücktritt, Skandal, Notenbank-Überraschung).
- surprise niedrig ansetzen, wenn das Ereignis erwartet oder wahrscheinlich schon eingepreist ist.
- confidence ehrlich: Bei dünner Faktenlage unter 0.5 bleiben.
- Höchstens 3 Signale pro Nachricht. Nichts erfinden, was nicht im Text steht."""

LEVELS = {"titel", "segment", "makro"}
DIRECTIONS = {"long", "short", "neutral"}
HORIZONS = {"tage", "woche"}


def build_user_prompt(article: dict) -> str:
    return (
        f"Quelle: {article['source']} ({article['source_kind']}, Region {article['region']})\n"
        f"Titel: {article['title']}\n"
        f"Zusammenfassung: {article['summary'] or '-'}"
    )


def _clamp_int(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def parse_signals(text: str) -> list[dict]:
    """Extrahiert und validiert Signale aus der LLM-Antwort. Ungültige Einträge werden verworfen."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("Kein JSON in der LLM-Antwort")
    data = json.loads(match.group(0))
    result = []
    for raw in data.get("signals", [])[:3]:
        if not isinstance(raw, dict):
            continue
        level, direction = raw.get("level"), raw.get("direction")
        target = str(raw.get("target", "")).strip()
        if level not in LEVELS or direction not in DIRECTIONS or not target:
            continue
        try:
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        related = raw.get("related") or []
        result.append({
            "level": level,
            "target": target[:80],
            "region": str(raw.get("region", "global"))[:20],
            "direction": direction,
            "magnitude": _clamp_int(raw.get("magnitude"), 1, 5, 1),
            "horizon": raw.get("horizon") if raw.get("horizon") in HORIZONS else "woche",
            "confidence": confidence,
            "surprise": _clamp_int(raw.get("surprise"), 1, 5, 1),
            "rationale": str(raw.get("rationale", "")).strip()[:500],
            "invalidation": str(raw.get("invalidation", "")).strip()[:300],
            "related": [str(r)[:60] for r in related if r][:5] if isinstance(related, list) else [],
        })
    return result


def score_article(article: dict, api_key: str, model: str, timeout: int = 60) -> list[dict]:
    """Ruft das LLM auf und gibt validierte Signale zurück."""
    resp = requests.post(
        API_URL,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": model,
            "max_tokens": 1000,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": build_user_prompt(article)}],
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    text = "".join(block.get("text", "") for block in resp.json().get("content", []))
    return parse_signals(text)
