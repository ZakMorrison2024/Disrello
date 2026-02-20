from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Tuple, Optional

import discord

from .base import Component
from ..ai import router
from ..context import select_conversation_burst, top_channel_keywords
from ..model import (
    ensure_default_list,
    get_or_create_list,
    guild_store,
    resolve_board,
    resolve_list,
    store_channel_summary,
    uid,
)
from ..storage import load_json, save_json_atomic
from .. import parsing


# --- Tunables (env override) ---
# “Whole channel” scan limit (practical cap to avoid rate limit + huge prompts)
CHANNEL_SCAN_LIMIT = int(os.getenv("DISRELLO_SUMMARISE_CHANNEL_SCAN_LIMIT", "1200"))
# Ignore very short / noisy messages in history scan
MIN_CONTENT_CHARS = int(os.getenv("DISRELLO_SUMMARISE_MIN_CONTENT_CHARS", "2"))

SYSTEM_PREFIX = "!**"


def _is_commandish(txt: str) -> bool:
    t = (txt or "").strip()
    if not t:
        return True
    # treat bot/system commands as noise for summarise context
    if t.startswith("!"):
        return True
    return False


def _render_conversation(guild: discord.Guild, picked: List[Tuple[int, str, float]]) -> str:
    lines: List[str] = []
    for author_id, content, _ts in picked:
        m = guild.get_member(author_id)
        name = (getattr(m, "display_name", None) or str(author_id)) if m else str(author_id)
        c = (content or "").strip().replace("\n", " ")
        if c:
            lines.append(f"{name}: {c}")
    return "\n".join(lines)


_SECTION_RE = re.compile(r"^(Topic:|Key points:|Decisions:|Open questions:)\s*$", re.IGNORECASE)


def _parse_summary_to_sections(summary: str) -> Dict[str, List[str]]:
    """
    Expects router.summarise() strict format:
      Topic: ...
      Key points:
      - ...
      Decisions:
      - ...
      Open questions:
      - ...
    Returns dict with keys: topic, key_points, decisions, open_questions
    """
    out = {"topic": [], "key_points": [], "decisions": [], "open_questions": []}

    if not summary:
        return out

    lines = [l.rstrip() for l in summary.splitlines()]
    mode = None

    for line in lines:
        s = line.strip()
        if not s:
            continue

        low = s.lower()

        if low.startswith("topic:"):
            topic = s.split(":", 1)[1].strip()
            if topic:
                out["topic"] = [topic]
            mode = None
            continue

        if low == "key points:":
            mode = "key_points"
            continue
        if low == "decisions:":
            mode = "decisions"
            continue
        if low == "open questions:":
            mode = "open_questions"
            continue

        # bullets
        m = parsing.AI_BULLET_RE.match(s)
        if m and mode:
            item = (m.group(1) or "").strip()
            if item and item.lower() != "none":
                out[mode].append(item)
            continue

    return out


def _dedupe_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        k = x.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


class Summarise(Component):
    name = "summarise"

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        content = (message.content or "").strip()
        if not content.startswith("!summarise") and not content.startswith("!summarize"):
            return

        # Support !summarise(list) "Board" [List]
        parsed = parsing.parse_function_call(content) or parsing.parse_shortcut(content)
        if parsed and parsed.get("cmd") in ("summarise", "summarize") and parsed.get("action") == "list":
            await self._summarise_list(message, parsed)
            return

        # Default: smart summarise (burst -> fallback to whole channel scan)
        await self._summarise_channel_smart(message)

    def _get_provider_model(self, store: dict) -> tuple[str, str]:
        ai = store.get("ai") or {}
        provider, model = router.get_effective_provider_and_model(self.cfg, ai)
        return provider, model

    async def _summarise_list(self, message: discord.Message, parsed: dict) -> None:
        board_ref = parsed.get("board_ref")
        list_name = parsed.get("list_name")
        if not board_ref or not list_name:
            await message.channel.send('❌ Usage: `!summarise(list) "Board" [List]`')
            return

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)

        b = resolve_board(store, board_ref)
        if not b:
            await message.channel.send("❌ Board not found.")
            return
        lst = resolve_list(b, list_name)
        if not lst:
            await message.channel.send("❌ List not found.")
            return

        cards = lst.get("cards") or []
        if not cards:
            await message.channel.send("❌ That list has no cards.")
            return

        # Render list into a “conversation-like” block
        convo = []
        for c in cards[:80]:
            title = (c.get("title") or "").strip()
            desc = (c.get("desc") or "").strip()
            if desc:
                convo.append(f"- {title}: {desc}")
            else:
                convo.append(f"- {title}")

        conversation_text = "\n".join(convo)
        if not conversation_text.strip():
            await message.channel.send("❌ Nothing to summarise.")
            return

        provider, model = self._get_provider_model(store)
        keywords = top_channel_keywords(self.state.channel_keywords, message.guild.id, message.channel.id, n=8)

        try:
            summary = await router.summarise(self.cfg, conversation_text, keywords=keywords, provider=provider, model=model)
        except Exception as e:
            await message.channel.send(f"⚠️ AI error: {e}")
            return

        summary = (summary or "").strip()
        if not summary:
            await message.channel.send("❌ Nothing returned.")
            return

        sid = store_channel_summary(store, message.channel.id, message.author.id, summary, keywords)
        save_json_atomic(self.cfg.data_file, data)
        await message.channel.send(f"🧠 **Summary saved** (`{sid}`)\n\n{summary[:1800]}")

    async def _fetch_channel_history(
        self,
        channel: discord.abc.Messageable,
        *,
        limit: int,
        before: Optional[discord.Message] = None,
    ) -> List[Tuple[int, str, float]]:
        """
        Pull history and return [(author_id, content, ts)] oldest->newest.
        """
        msgs: List[Tuple[int, str, float]] = []
        try:
            hist = channel.history(limit=limit, before=before, oldest_first=True)  # type: ignore[attr-defined]
        except Exception:
            return msgs

        try:
            async for m in hist:
                if not getattr(m, "guild", None):
                    continue
                if m.author.bot:
                    continue
                txt = (m.content or "").strip()
                if len(txt) < MIN_CONTENT_CHARS:
                    continue
                # skip command noise, including the summarise call itself
                if _is_commandish(txt):
                    continue
                ts = float(getattr(m.created_at, "timestamp", lambda: time.time())())
                msgs.append((int(m.author.id), txt, ts))
        except Exception:
            return msgs

        return msgs

    def _pick_burst_from_buffer(self, message: discord.Message) -> List[Tuple[int, str, float]]:
        key = (message.guild.id, message.channel.id)
        buf = self.state.context_buffers.get(key, []) or []
        now_ts = time.time()

        lookback_s = int(getattr(self.cfg, "summarise_lookback_s", 3600))
        silence_gap_s = int(getattr(self.cfg, "summarise_silence_gap_s", 600))
        min_messages = int(getattr(self.cfg, "summarise_min_messages", 8))
        min_authors = int(getattr(self.cfg, "summarise_min_authors", 2))
        target_max_messages = int(getattr(self.cfg, "summarise_target_max_messages", 60))

        picked = select_conversation_burst(
            buf,
            now_ts=now_ts,
            lookback_s=lookback_s,
            silence_gap_s=silence_gap_s,
            min_messages=min_messages,
            min_authors=min_authors,
            target_max_messages=target_max_messages,
        )
        return picked

    def _burst_is_in_context(self, picked: List[Tuple[int, str, float]]) -> bool:
        """
        Your “is this in context?” gate.
        If not, we fall back to scanning channel history.
        """
        if not picked:
            return False

        # remove command-ish / empty content
        cleaned = [(a, c, t) for (a, c, t) in picked if c and not _is_commandish(c)]
        if len(cleaned) < 6:
            return False

        authors = {a for (a, _, _) in cleaned}
        if len(authors) < 2:
            return False

        # if it's mostly tiny fragments, treat as not real context
        avg_len = sum(len(c) for (_, c, _) in cleaned) / max(1, len(cleaned))
        if avg_len < 12:
            return False

        return True

    async def _summarise_channel_smart(self, message: discord.Message) -> None:
        # 1) Try fast RAM burst first
        picked = self._pick_burst_from_buffer(message)
        used_fallback = False

        # 2) If not “in context”, scan channel history (practical whole channel)
        if not self._burst_is_in_context(picked):
            used_fallback = True
            history = await self._fetch_channel_history(
                message.channel,
                limit=CHANNEL_SCAN_LIMIT,
                before=message,
            )
            # If still empty, nothing we can do
            if not history:
                await message.channel.send("❌ Nothing to summarise (no usable history found).")
                return
            # Use *all* fetched history (already capped), but keep last 250 lines max for prompt safety
            # (You can raise this if you’re on strong models.)
            picked = history[-250:]

        conversation_text = _render_conversation(message.guild, picked)
        if not conversation_text.strip():
            await message.channel.send("❌ Nothing to summarise.")
            return

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)
        provider, model = self._get_provider_model(store)
        keywords = top_channel_keywords(self.state.channel_keywords, message.guild.id, message.channel.id, n=8)

        try:
            summary = await router.summarise(self.cfg, conversation_text, keywords=keywords, provider=provider, model=model)
        except Exception as e:
            await message.channel.send(f"⚠️ AI error: {e}")
            return

        summary = (summary or "").strip()
        if not summary:
            await message.channel.send("❌ Nothing returned.")
            return

        # Save summary entry
        sid = store_channel_summary(store, message.channel.id, message.author.id, summary, keywords)

        # --- Build a “board” from the summary (lists + cards) ---
        sections = _parse_summary_to_sections(summary)
        topic = (sections.get("topic") or ["Channel Summary"])[0].strip()[:120]

        board_name = f"#{getattr(message.channel, 'name', 'channel')} — {topic}"
        b = resolve_board(store, board_name)
        if not b:
            b = {"id": uid("board"), "name": board_name[:200], "lists": []}
            ensure_default_list(b)
            store.setdefault("boards", []).append(b)

        # Lists
        lst_key = get_or_create_list(b, "Key points")
        lst_dec = get_or_create_list(b, "Decisions")
        lst_qs = get_or_create_list(b, "Open questions")
        lst_act = get_or_create_list(b, "Action items")

        # Cards from sections
        def add_cards(lst: dict, items: List[str], *, prefix: str) -> int:
            items = _dedupe_keep_order(items)
            if not items:
                return 0
            lst.setdefault("cards", [])
            n = 0
            for it in items[:40]:
                title = it.strip()[:200]
                desc = f"{prefix}\nSource summary: {sid}\nChannel: <#{message.channel.id}>"
                lst["cards"].append(
                    {
                        "id": uid("card"),
                        "title": title,
                        "desc": desc[:2000],
                        "done": False,
                        "progress": 0,
                        "assigned_to": message.author.id,
                        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "created_by": message.author.id,
                    }
                )
                n += 1
            return n

        created = 0
        created += add_cards(lst_key, sections.get("key_points", []), prefix="Key point")
        created += add_cards(lst_dec, sections.get("decisions", []), prefix="Decision")
        created += add_cards(lst_qs, sections.get("open_questions", []), prefix="Open question")

        # Optional: derive action items from summary bullets (simple heuristic: use task extractor if available)
        actions = []
        try:
            # if you already have this helper (used elsewhere), it’s a nice “free win”
            actions = parsing.extract_tasks_from_ai_reply(summary)  # type: ignore[attr-defined]
        except Exception:
            actions = []

        created += add_cards(lst_act, actions or [], prefix="Action item")

        save_json_atomic(self.cfg.data_file, data)

        fallback_note = " (used channel scan fallback)" if used_fallback else ""
        await message.channel.send(
            f"🧠 **Summary saved** (`{sid}`){fallback_note}\n"
            f"📋 Built board **{b.get('name')}** with **{created}** card(s).\n\n"
            f"{summary[:1600]}"
        )
