from __future__ import annotations

import aiohttp
from typing import Any, Dict, List, Optional

from ..config import BotConfig


def _auth_headers(api_key: str) -> Dict[str, str]:
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def _join(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    path = (path or "").lstrip("/")
    return f"{base}/{path}"


async def chat_messages(
    cfg: BotConfig,
    messages: List[Dict[str, str]],
    temperature: float,
    model: Optional[str] = None,
) -> str:
    if not cfg.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (set in .env)")

    payload = {
        "model": (model or cfg.openai_model),
        "messages": messages,
        "temperature": float(temperature),
    }

    url = _join(cfg.openai_base_url, "v1/chat/completions")
    timeout = aiohttp.ClientTimeout(total=cfg.openai_timeout_s)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload, headers=_auth_headers(cfg.openai_api_key)) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"OpenAI-compatible error {resp.status}: {txt[:500]}")
            data = await resp.json()

    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = (choices[0].get("message") or {}).get("content")
    return (msg or "").strip()


async def list_models(cfg: BotConfig) -> List[str]:
    if not cfg.openai_api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (set in .env)")

    url = _join(cfg.openai_base_url, "v1/models")
    timeout = aiohttp.ClientTimeout(total=min(15.0, cfg.openai_timeout_s))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=_auth_headers(cfg.openai_api_key)) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"OpenAI-compatible error {resp.status}: {txt[:500]}")
            data = await resp.json()

    out: List[str] = []
    for m in (data.get("data") or []):
        mid = (m.get("id") or "").strip()
        if mid:
            out.append(mid)
    out = sorted(set(out))
    return out

