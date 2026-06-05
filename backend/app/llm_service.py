from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

_OLLAMA_AVAILABLE: bool | None = None


def summarize_flow(flow_name: str, technical_steps: list[str]) -> tuple[str, bool]:
    global _OLLAMA_AVAILABLE
    if os.getenv("BFO_ENABLE_AI", "0").lower() not in {"1", "true", "yes"}:
        return _fallback_summary(technical_steps), False
    if _OLLAMA_AVAILABLE is False:
        return _fallback_summary(technical_steps), False

    model = os.getenv("OLLAMA_MODEL", "gemma4")
    prompt = (
        "Translate this code flow into one concise business-language sentence. "
        "Do not invent details. Flow: "
        + flow_name
        + ". Steps: "
        + " -> ".join(technical_steps)
    )
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
    timeout_seconds = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    request = urllib.request.Request(f"{base_url}/api/generate", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
            text = _clean_ai_summary(str(data.get("response", "")).strip())
            if text:
                _OLLAMA_AVAILABLE = True
                return text, True
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        _OLLAMA_AVAILABLE = False
    return _fallback_summary(technical_steps), False


def _fallback_summary(technical_steps: list[str]) -> str:
    return f"AI summary unavailable. Deterministic analysis found: {' -> '.join(technical_steps)}."


def _clean_ai_summary(text: str) -> str:
    if not text:
        return ""
    lines = [line.strip().strip('"') for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.lower().startswith(("here is", "this sentence", "it avoids", "the sentence", "translation")):
            continue
        sentence = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0].strip().strip('"')
        if sentence:
            return sentence[:280]
    return lines[0][:280] if lines else ""
