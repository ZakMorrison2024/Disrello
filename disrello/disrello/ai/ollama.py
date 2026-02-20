# Backwards-compatible shim (older components imported disrello.ai.ollama)
from __future__ import annotations

from typing import List

from ..config import BotConfig
from .router import chat as _chat, taskify as _taskify, list_models as _list_models, get_effective_provider_and_model


async def chat(cfg: BotConfig, prompt: str, context_lines: List[str]) -> str:
    provider = "ollama"
    model = cfg.ollama_model
    return await _chat(cfg, prompt, context_lines, provider=provider, model=model)


async def taskify(cfg: BotConfig, conversation_text: str) -> str:
    provider = "ollama"
    model = cfg.ollama_model
    return await _taskify(cfg, conversation_text, provider=provider, model=model)


async def list_local_models(cfg: BotConfig) -> List[str]:
    return await _list_models(cfg, "ollama")

