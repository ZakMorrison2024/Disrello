from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any

import discord
from discord.ext import commands

from ..config import BotConfig


@dataclass
class BotState:
    context_buffers: Dict[Any, Any]
    channel_keywords: Dict[Any, Any]
    todo_posts: Dict[Any, Any]
    last_ai_reply_ts: Dict[Any, Any]
    pending_task_confirms: Dict[Any, Any]
    last_taskify_draft: Dict[Any, Any]
    guild_channel_overrides: Dict[int, Dict[str, int]]


class Component:
    name: str = "component"

    def __init__(self, bot: commands.Bot, cfg: BotConfig, state: BotState):
        self.bot = bot
        self.cfg = cfg
        self.state = state

    def _channel_overrides(self, guild_id: int) -> Dict[str, int]:
        return self.state.guild_channel_overrides.get(int(guild_id)) or {}

    def effective_todo_channel_id(self, guild_id: int) -> int:
        ov = self._channel_overrides(guild_id)
        return int(ov.get("todo") or self.cfg.todo_channel_id)

    def effective_ai_listen_channel_id(self, guild_id: int) -> int:
        ov = self._channel_overrides(guild_id)
        return int(ov.get("ai") or self.cfg.ai_listen_channel_id)

    def effective_system_channel_id(self, guild_id: int) -> int:
        ov = self._channel_overrides(guild_id)
        return int(ov.get("sys") or getattr(self.cfg, "system_channel_id", 0))

    async def on_ready(self) -> None:
        return

    async def on_message(self, message: discord.Message) -> None:
        return

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.abc.User) -> None:
        return
