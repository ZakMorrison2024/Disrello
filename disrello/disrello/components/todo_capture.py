from __future__ import annotations

import os
import time
from typing import List, Optional

import discord

from .base import Component
from .. import parsing
from ..context import push_context, update_channel_keywords
from ..model import add_cards_to_todo_inbox, guild_store, upsert_member
from ..storage import load_json, save_json_atomic
import discord

try:
    # Preferred (if your embeds.py provides them)
    from ..ui.embeds import embed_task_confirm, embed_todo_capture  # type: ignore
except Exception:
    # Fallbacks so the bot can boot even if embeds.py is missing these helpers
    def embed_task_confirm(*, author: str, content: str, suggested_title: str | None = None):
        e = discord.Embed(title="Confirm task?", description=content)
        e.add_field(name="Author", value=author or "Unknown", inline=True)
        if suggested_title:
            e.add_field(name="Suggested title", value=suggested_title, inline=False)
        e.set_footer(text="Reply with: !yes to confirm, !no to cancel")
        return e

    def embed_todo_capture(*, author: str, content: str, detected: str | None = None):
        e = discord.Embed(title="TODO capture", description=content)
        e.add_field(name="Author", value=author or "Unknown", inline=True)
        if detected:
            e.add_field(name="Detected intent", value=detected, inline=False)
        e.set_footer(text="Use !ai make this a task (or !yes / !no if prompted)")
        return e



class TodoCapture(Component):
    name = "todo_capture"

    def __init__(self, bot, cfg, state):
        super().__init__(bot, cfg, state)
        self.pending_ttl_s = float(os.getenv("PENDING_TASK_TTL_S", "120"))

    async def _get_todo_channel(self, guild: discord.Guild) -> Optional[discord.abc.Messageable]:
        todo_chan = guild.get_channel(self.effective_todo_channel_id(guild.id))
        if todo_chan is None:
            try:
                todo_chan = await self.bot.fetch_channel(self.effective_todo_channel_id(guild.id))
            except discord.HTTPException:
                todo_chan = None
        if not isinstance(todo_chan, (discord.TextChannel, discord.Thread)):
            return None
        return todo_chan

    async def _post_todo_cards(self, guild: discord.Guild, author: discord.abc.User, items: List[str], source: str) -> Optional[discord.Message]:
        if not items:
            return None
        todo_chan = await self._get_todo_channel(guild)
        if todo_chan is None:
            return None

        data = load_json(self.cfg.data_file)
        store = guild_store(data, guild.id)
        upsert_member(store, author)

        card_ids = add_cards_to_todo_inbox(
            store,
            todo_board_name=self.cfg.todo_board_name,
            todo_inbox_list_name=self.cfg.todo_inbox_list_name,
            author_id=author.id,
            items=items,
            source=source,
        )
        save_json_atomic(self.cfg.data_file, data)

        e = embed_todo_capture(items, card_ids, source, author.id, self.cfg.todo_board_name, self.cfg.todo_inbox_list_name)
        msg = await todo_chan.send(embed=e)
        try:
            await msg.add_reaction("✅")
        except discord.HTTPException:
            pass

        self.state.todo_posts[msg.id] = {"card_ids": card_ids, "done": False, "source": source, "created_ts": time.time(), "guild_id": guild.id}
        return msg

    async def _offer_confirm(self, message: discord.Message, items: List[str], source: str) -> None:
        key = (message.guild.id, message.channel.id, message.author.id)
        self.state.pending_task_confirms[key] = {"items": items, "ts": time.time(), "source": source}
        await message.channel.send(embed=embed_task_confirm(items))

    async def _try_consume_confirm(self, message: discord.Message) -> bool:
        if not message.guild:
            return False
        key = (message.guild.id, message.channel.id, message.author.id)
        pending = self.state.pending_task_confirms.get(key)
        if not pending:
            return False
        if (time.time() - float(pending.get("ts", 0))) > self.pending_ttl_s:
            self.state.pending_task_confirms.pop(key, None)
            return False

        txt = (message.content or "").strip()
        if parsing.YES_RE.match(txt):
            self.state.pending_task_confirms.pop(key, None)
            items = pending.get("items") or []
            source = pending.get("source") or f"<#{message.channel.id}> / {message.author.display_name}"
            await self._post_todo_cards(message.guild, message.author, items, source=source)
            await message.channel.send("✅ Added to TODO.")
            return True

        if parsing.NO_RE.match(txt):
            self.state.pending_task_confirms.pop(key, None)
            await message.channel.send("🛑 Cancelled.")
            return True

        return False

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        # Confirmation replies
        if await self._try_consume_confirm(message):
            return

        # Always record context + keywords (all channels)
        push_context(self.state.context_buffers, message.guild.id, message.channel.id, message.author.id, message.content or "", self.cfg.context_limit)
        update_channel_keywords(self.state.channel_keywords, message.guild.id, message.channel.id, message.content or "")

        # Checkbox TODO capture
        items = parsing.extract_todos(message.content or "")
        if items:
            source = f"<#{message.channel.id}> / {message.author.display_name}"
            await self._post_todo_cards(message.guild, message.author, items, source=source)
            return

        # Casual intent detection (asks confirm)
        intent_items = parsing.extract_task_intent_items(message.content or "")
        if intent_items:
            source = f"<#{message.channel.id}> / {message.author.display_name}"
            await self._offer_confirm(message, intent_items, source=source)
            return

    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.abc.User) -> None:
        if user.bot:
            return
        msg = reaction.message
        if not msg.guild:
            return
        if str(reaction.emoji) != "✅":
            return
        post = self.state.todo_posts.get(msg.id)
        if not post or post.get("done"):
            return

        data = load_json(self.cfg.data_file)
        store = guild_store(data, msg.guild.id)

        todo_board = None
        for b in store.get("boards") or []:
            if (b.get("name") or "").strip().lower() == self.cfg.todo_board_name.strip().lower():
                todo_board = b
                break
        if not todo_board:
            return

        card_ids = post.get("card_ids") or []
        for lst in todo_board.get("lists") or []:
            for c in lst.get("cards") or []:
                if c.get("id") in card_ids:
                    c["done"] = True
                    c["progress"] = 100

        save_json_atomic(self.cfg.data_file, data)
        post["done"] = True

        try:
            await msg.reply("✅ Marked all linked TODO cards done.")
        except discord.HTTPException:
            pass

