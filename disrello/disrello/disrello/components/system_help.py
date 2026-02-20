from __future__ import annotations

import discord

from .base import Component
from ..ui.embeds import embed_help_system


SYSTEM_PREFIX = "!**"


def _strip_system_prefix(content: str) -> str:
    s = (content or "").strip()
    if not s.startswith(SYSTEM_PREFIX):
        return ""
    return s[len(SYSTEM_PREFIX) :].lstrip()


class SystemHelp(Component):
    """Handles `!** help` so system commands have their own help page."""

    name = "system_help"

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        raw = (message.content or "").strip()
        if not raw.startswith(SYSTEM_PREFIX):
            return

        tail = _strip_system_prefix(raw)
        if not tail:
            return

        head = tail.split(maxsplit=1)[0].lower()
        if head in ("help", "h", "?"):
            # Try to read IDs from common places; fall back to 0 if not present
            ai_id = getattr(self, "ai_listen_channel_id", None)
            todo_id = getattr(self, "todo_channel_id", None)

            cfg = getattr(self, "cfg", None) or getattr(self, "config", None)
            if cfg:
                ai_id = ai_id or getattr(cfg, "AI_LISTEN_CHANNEL_ID", None) or getattr(cfg, "ai_listen_channel_id", None)
                todo_id = todo_id or getattr(cfg, "TODO_CHANNEL_ID", None) or getattr(cfg, "todo_channel_id", None)

            ai_id = int(ai_id or 0)
            todo_id = int(todo_id or 0)

            await message.channel.send(embed=embed_help_system(ai_id, todo_id))
            return

