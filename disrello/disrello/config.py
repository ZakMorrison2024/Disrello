from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, str(default)).strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_csv(name: str) -> List[str]:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


@dataclass(frozen=True)
class BotConfig:
    token: str
    todo_channel_id: int
    ai_listen_channel_id: int
    system_channel_id: int

    data_file: str

    # LLM routing
    llm_provider: str  # "ollama" or "openai" (OpenAI-compatible)
    prefer_small_models: bool
    preferred_ollama_models: List[str]
    preferred_openai_models: List[str]

    # Ollama
    ollama_url: str
    ollama_model: str
    ollama_timeout_s: float
    ollama_temperature: float
    ollama_context_messages: int

    # OpenAI-compatible
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_timeout_s: float

    # Bot behavior
    ai_cooldown_s: float
    context_limit: int
    forward_todos_from_other_channels: bool
    auto_capture_tasks_from_ai: bool

    taskify_lookback_s: int
    taskify_silence_gap_s: int
    taskify_min_messages: int
    taskify_min_authors: int
    taskify_target_max_messages: int

    todo_board_name: str
    todo_inbox_list_name: str

    components: List[str]


def load_config() -> BotConfig:
    token = os.getenv("DISCORD_TOKEN", "").strip()

    todo_channel_id = _env_int("TODO_CHANNEL_ID", 0)
    ai_listen_channel_id = _env_int("AI_LISTEN_CHANNEL_ID", 0)
    system_channel_id = _env_int("SYSTEM_CHANNEL_ID", todo_channel_id if todo_channel_id else 0)

    data_file = os.getenv("DATA_FILE", "disrello_ai_data.json").strip() or "disrello_ai_data.json"

    # Provider routing
    llm_provider = (os.getenv("LLM_PROVIDER", "ollama") or "openai").strip().lower()

    if llm_provider not in ("ollama", "openai"):
        llm_provider = "ollama"

    prefer_small_models = _env_bool("PREFER_SMALL_MODELS", True)
    preferred_ollama_models = _env_csv("PREFERRED_MODELS_OLLAMA")
    preferred_openai_models = _env_csv("PREFERRED_MODELS_OPENAI")

    # Ollama
    ollama_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    ollama_model = os.getenv("OLLAMA_MODEL", "phi3.5").strip() or "phi3.5"
    ollama_timeout_s = _env_float("OLLAMA_TIMEOUT_S", 45.0)
    ollama_temperature = _env_float("OLLAMA_TEMPERATURE", 0.6)
    ollama_context_messages = _env_int("OLLAMA_CONTEXT_MESSAGES", 20)

    # OpenAI-compatible (OpenAI, Groq, etc.)
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_base_url = (os.getenv("OPENAI_BASE_URL", "https://api.openai.com") or "https://api.openai.com").strip().rstrip("/")
    openai_model = (os.getenv("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini").strip()
    openai_timeout_s = _env_float("OPENAI_TIMEOUT_S", 45.0)

    # Behavior
    ai_cooldown_s = _env_float("AI_COOLDOWN_S", 2.5)
    context_limit = _env_int("CONTEXT_LIMIT", 80)
    forward = _env_bool("FORWARD_TODOS_FROM_OTHER_CHANNELS", True)
    auto_capture = _env_bool("AUTO_CAPTURE_TASKS_FROM_AI", True)

    taskify_lookback_s = _env_int("TASKIFY_LOOKBACK_S", 900)
    taskify_silence_gap_s = _env_int("TASKIFY_SILENCE_GAP_S", 75)
    taskify_min_messages = _env_int("TASKIFY_MIN_MESSAGES", 6)
    taskify_min_authors = _env_int("TASKIFY_MIN_AUTHORS", 2)
    taskify_target_max_messages = _env_int("TASKIFY_TARGET_MAX_MESSAGES", 40)

    todo_board_name = os.getenv("TODO_BOARD_NAME", "TODO").strip() or "TODO"
    todo_inbox_list_name = os.getenv("TODO_INBOX_LIST_NAME", "Inbox").strip() or "Inbox"

    comps_raw = os.getenv("COMPONENTS", "disrello_commands,todo_capture,ai_chat,summarise,search,settings").strip()
    components = [c.strip() for c in comps_raw.split(",") if c.strip()]

    if not todo_channel_id:
        raise RuntimeError("Missing TODO_CHANNEL_ID (set in .env)")
    if not token:
        raise RuntimeError("Missing DISCORD_TOKEN (set in .env)")

    return BotConfig(
        token=token,
        todo_channel_id=todo_channel_id,
        ai_listen_channel_id=ai_listen_channel_id,
        system_channel_id=system_channel_id or todo_channel_id,
        data_file=data_file,
        llm_provider=llm_provider,
        prefer_small_models=prefer_small_models,
        preferred_ollama_models=preferred_ollama_models,
        preferred_openai_models=preferred_openai_models,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
        ollama_timeout_s=ollama_timeout_s,
        ollama_temperature=ollama_temperature,
        ollama_context_messages=ollama_context_messages,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        openai_model=openai_model,
        openai_timeout_s=openai_timeout_s,
        ai_cooldown_s=ai_cooldown_s,
        context_limit=context_limit,
        forward_todos_from_other_channels=forward,
        auto_capture_tasks_from_ai=auto_capture,
        taskify_lookback_s=taskify_lookback_s,
        taskify_silence_gap_s=taskify_silence_gap_s,
        taskify_min_messages=taskify_min_messages,
        taskify_min_authors=taskify_min_authors,
        taskify_target_max_messages=taskify_target_max_messages,
        todo_board_name=todo_board_name,
        todo_inbox_list_name=todo_inbox_list_name,
        components=components,
    )

