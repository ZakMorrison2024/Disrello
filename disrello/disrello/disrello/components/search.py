from __future__ import annotations

import discord

from .base import Component
from ..model import guild_store
from ..storage import load_json
from ..ui.embeds import embed_search

SYSTEM_PREFIX = "!**"


def _strip_system_prefix(content: str) -> str:
    s = (content or "").strip()
    if not s.startswith(SYSTEM_PREFIX):
        return ""
    return s[len(SYSTEM_PREFIX):].lstrip()


class Search(Component):
    name = "search"

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        raw = (message.content or "").strip()
        if not raw.startswith(SYSTEM_PREFIX):
            return

        tail = _strip_system_prefix(raw)
        if not tail.lower().startswith("search"):
            return

        query_raw = tail[len("search") :].strip()
        if not query_raw:
            await message.channel.send("❌ Usage: `!** search <text>` (optional: `assigned:me`, `from:me`)")
            return

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)

        q = query_raw
        q_low = q.lower()

        assigned_me = "assigned:me" in q_low
        from_me = "from:me" in q_low

        # remove filters from query text
        q_clean = q.replace("assigned:me", "").replace("from:me", "").strip().lower()

        card_lines = []
        for b in (store.get("boards") or []):
            for lst in (b.get("lists") or []):
                for c in (lst.get("cards") or []):
                    title = (c.get("title") or "")
                    desc = (c.get("desc") or "")
                    hay = f"{title}\n{desc}".lower()

                    if q_clean and q_clean not in hay:
                        continue
                    if assigned_me and int(c.get("assigned_to") or 0) != int(message.author.id):
                        continue
                    if from_me and int(c.get("created_by") or 0) != int(message.author.id):
                        continue

                    card_lines.append(f'- `{c.get("id")}` **{title[:80]}** (board: {b.get("name")}, list: {lst.get("name")})')

        sum_lines = []
        for s in (store.get("summaries") or []):
            text = (s.get("summary") or "").lower()
            if q_clean and q_clean not in text:
                continue
            sum_lines.append(f'- `{s.get("id")}` (channel `{s.get("channel_id")}`) keywords: {", ".join(s.get("keywords") or [])[:120]}')

        await message.channel.send(embed=embed_search(query_raw, card_lines, sum_lines))

