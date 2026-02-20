from __future__ import annotations

import discord
from discord.ext import commands
from dotenv import load_dotenv

from .config import load_config
from .components.base import BotState
from .components.disrello_commands import DisrelloCommands
from .components.todo_capture import TodoCapture
from .components.ai_chat import AIChat
from .components.summarise import Summarise
from .components.search import Search
from .components.settings import Settings
from .components.system_help import SystemHelp


_COMPONENTS = {
    "disrello_commands": DisrelloCommands,
    "todo_capture": TodoCapture,
    "ai_chat": AIChat,
    "summarise": Summarise,
    "search": Search,
    "settings": Settings,
    # NEW: handles !** help
    "system_help": SystemHelp,
}


def build_bot():
    load_dotenv()
    cfg = load_config()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.messages = True
    intents.reactions = True
    intents.guilds = True
    intents.members = True

    bot = commands.Bot(command_prefix="!", intents=intents)

    state = BotState(
        context_buffers={},
        channel_keywords={},
        todo_posts={},
        last_ai_reply_ts={},
        pending_task_confirms={},
        last_taskify_draft={},
        guild_channel_overrides={},
    )

    components = []
    for name in cfg.components:
        cls = _COMPONENTS.get(name)
        if not cls:
            raise RuntimeError(f"Unknown component in COMPONENTS: {name}")
        components.append(cls(bot, cfg, state))

    bot._disrello_components = components

    @bot.event
    async def on_ready():
        print(f"✅ Logged in as {bot.user}")
        for c in components:
            await c.on_ready()

    @bot.event
    async def on_message(message: discord.Message):
        for c in components:
            await c.on_message(message)

    @bot.event
    async def on_reaction_add(reaction: discord.Reaction, user: discord.abc.User):
        for c in components:
            await c.on_reaction_add(reaction, user)

    return bot, cfg


def main():
    bot, cfg = build_bot()
    bot.run(cfg.token)


if __name__ == "__main__":
    main()

