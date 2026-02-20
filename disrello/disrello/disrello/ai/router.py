from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..config import BotConfig
from . import ollama_client, openai_compat
from .ram_limits import model_fits_ram, normalize_ram_gb, DEFAULT_RAM_GB


SUPPORTED_PROVIDERS = ("ollama", "openai")  # openai = OpenAI-compatible (OpenAI, Groq, etc.)

# Default "small/cheap" preference lists (override with env vars)
DEFAULT_PREFERRED_OLLAMA = [
    "phi3.5",
    "phi3",
    "llama3.2:1b",
    "llama3.2:3b",
    "gemma2:2b",
    "qwen2.5:3b",
    "mistral:7b",
]
DEFAULT_PREFERRED_OPENAI = [
    # keep generic: user can override via env or !ai model set
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-3.5-turbo",
]


def get_effective_provider_and_model(cfg: BotConfig, guild_ai: Dict) -> Tuple[str, str]:
    provider = (guild_ai.get("provider") or cfg.llm_provider).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        provider = cfg.llm_provider

    model = (guild_ai.get("model") or "").strip()
    if model:
        return provider, model

    # No guild-specific model: pick a sensible default
    if provider == "openai":
        return provider, cfg.openai_model
    return provider, cfg.ollama_model


async def list_models(cfg: BotConfig, provider: str) -> List[str]:
    provider = (provider or "").strip().lower()
    if provider == "openai":
        return await openai_compat.list_models(cfg)
    if provider == "ollama":
        return await ollama_client.list_models(cfg)
    raise RuntimeError(f"Unsupported provider: {provider}")


def _preferred_list(cfg: BotConfig, provider: str) -> List[str]:
    provider = (provider or "").strip().lower()
    if provider == "openai":
        return cfg.preferred_openai_models or DEFAULT_PREFERRED_OPENAI
    return cfg.preferred_ollama_models or DEFAULT_PREFERRED_OLLAMA


async def choose_small_model_if_possible(cfg: BotConfig, provider: str, available: List[str], ram_gb: int = DEFAULT_RAM_GB) -> Optional[str]:
    if not cfg.prefer_small_models:
        return None
    ram_gb = normalize_ram_gb(ram_gb)

    pref = _preferred_list(cfg, provider)
    avail_set = {a.strip() for a in available if a and a.strip()}

    for want in pref:
        if want in avail_set and model_fits_ram(want, ram_gb):
            return want
        for a in avail_set:
            if a.lower() == want.lower() and model_fits_ram(a, ram_gb):
                return a
    return None



async def chat_messages(cfg: BotConfig, provider: str, model: str, messages: List[Dict[str, str]], temperature: float) -> str:
    provider = (provider or "").strip().lower()
    if provider == "openai":
        return await openai_compat.chat_messages(cfg, messages, temperature=temperature, model=model)
    if provider == "ollama":
        return await ollama_client.chat_messages(cfg, messages, temperature=temperature, model=model)
    raise RuntimeError(f"Unsupported provider: {provider}")


async def chat(cfg: BotConfig, prompt: str, context_lines: List[str], provider: str, model: str) -> str:
    system = (
        "You are a helpful Discord chatbot.\n"
        "Rules:\n"
        "- Reply naturally and concisely (one message).\n"
        "- Don't invent tasks unless asked.\n"
        "- If asked to extract tasks, only extract what was explicitly stated.\n"
    )
    context_text = "\n".join([f"- {c}" for c in context_lines if c])
    user_content = f"Recent channel context:\n{context_text}\n\nUser message:\n{prompt}"
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]
    return await chat_messages(cfg, provider, model, msgs, temperature=cfg.ollama_temperature)


async def taskify(cfg: BotConfig, conversation_text: str, provider: str, model: str) -> str:
    system = (
        "You convert a short Discord conversation into TODO tasks.\n"
        "STRICT RULES:\n"
        "- ONLY extract tasks explicitly stated or clearly intended.\n"
        "- DO NOT add suggestions or planning steps.\n"
        "- Output ONLY a bullet list using '-' bullets. No headings.\n"
        "- Max 5 bullets.\n"
        "- If no clear tasks, output exactly: - No clear tasks\n"
    )
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": f"Conversation:\n{conversation_text}\n\nTasks:"}]
    return await chat_messages(cfg, provider, model, msgs, temperature=0.2)


async def summarise(cfg: BotConfig, conversation_text: str, keywords: List[str], provider: str, model: str) -> str:
    system = (
        "You summarise a Discord channel discussion.\n"
        "Output format (strict):\n"
        "Topic: <one line>\n"
        "Key points:\n"
        "- ...\n"
        "Decisions:\n"
        "- ... (or - None)\n"
        "Open questions:\n"
        "- ... (or - None)\n"
        "Keep it concise. Do not invent facts."
    )
    kw = ", ".join(keywords[:10]) if keywords else ""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": f"Keywords (optional): {kw}\n\nConversation:\n{conversation_text}\n\nSummary:"}]
    return await chat_messages(cfg, provider, model, msgs, temperature=0.2)

