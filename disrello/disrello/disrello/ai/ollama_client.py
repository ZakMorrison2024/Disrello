from __future__ import annotations

import aiohttp
from typing import Any, Dict, List, Optional, Tuple

from ..config import BotConfig


async def chat_messages(cfg: BotConfig, messages: List[Dict[str, str]], temperature: float, model: Optional[str] = None) -> str:
    payload = {
        "model": (model or cfg.ollama_model),
        "messages": messages,
        "stream": False,
        "options": {
                "temperature": float(temperature),
                # Keep context modest; huge ctx = huge RAM
                "num_ctx": 2048,
                # helps on lower memory machines (harmless if ignored)
                "low_vram": True,
            },

    }
    url = f"{cfg.ollama_url}/api/chat"
    timeout = aiohttp.ClientTimeout(total=cfg.ollama_timeout_s)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"Ollama error {resp.status}: {txt[:500]}")
            data = await resp.json()
    return ((data.get("message") or {}).get("content") or "").strip()


async def list_models(cfg: BotConfig) -> List[str]:
    url = f"{cfg.ollama_url}/api/tags"
    timeout = aiohttp.ClientTimeout(total=min(15.0, cfg.ollama_timeout_s))
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                txt = await resp.text()
                raise RuntimeError(f"Ollama error {resp.status}: {txt[:300]}")
            data = await resp.json()
    models = []
    for m in (data.get("models") or []):
        name = (m.get("name") or "").strip()
        if name:
            models.append(name)
    # newest first is usually fine; keep as returned, but ensure uniqueness
    seen = set()
    out = []
    for n in models:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out

