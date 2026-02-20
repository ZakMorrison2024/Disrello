from __future__ import annotations

import re
import time
from typing import List, Tuple, Optional

import discord

from .base import Component
from ..ai import router
from ..context import select_conversation_burst
from ..model import delete_card, guild_store, resolve_board
from ..storage import load_json, save_json_atomic
from .. import parsing
from ..ai.ram_limits import (
    normalize_ram_gb,
    model_fits_ram,
    estimate_ram_gb,
    DEFAULT_RAM_GB,
    MAX_RAM_GB,
)

# --- Prefix rules ---
SYSTEM_PREFIX = "!**"   # system/admin controls only
AI_PREFIX = "!ai"       # normal AI chat & flows


MAKE_TASK_RE = re.compile(r"\bmake\s+(?:that|this|it)\s+(?:into\s+)?a\s+task\b", re.IGNORECASE)
MAKE_CARD_RE = re.compile(r"\bmake\s+(?:that|this|it)\s+(?:into\s+)?a\s+card\b", re.IGNORECASE)
PICK_TASK_RE = re.compile(r"^\s*(?:pick\s+)?(\d{1,2})\s*$", re.IGNORECASE)


def _cooldown_ok(state, cfg, guild_id: int, channel_id: int, settings: dict) -> bool:
    key = (guild_id, channel_id)
    last_ts = state.last_ai_reply_ts.get(key, 0.0)
    cooldown = float(settings.get("ai_cooldown_s", cfg.ai_cooldown_s))
    return (time.time() - last_ts) >= cooldown


def _render_conversation(guild: discord.Guild, msgs) -> str:
    lines: List[str] = []
    for author_id, content, _ts in msgs:
        m = guild.get_member(author_id) if guild else None
        name = (getattr(m, "display_name", None) or str(author_id)) if m else str(author_id)
        c = (content or "").strip().replace("\n", " ").strip()
        if c:
            lines.append(f"{name}: {c}")
    return "\n".join(lines)


def _strip_system_prefix(content: str) -> str:
    s = (content or "").strip()
    if not s.startswith(SYSTEM_PREFIX):
        return ""
    return s[len(SYSTEM_PREFIX):].lstrip()


class AIChat(Component):
    """
    Behavior:
      - System/admin controls ONLY via: !** ai ...
      - Normal AI via:
           * AI listen channel (unless message starts with ! or !**)
           * !ai <prompt>
           * @mention
      - Taskify/cardify flows remain under normal AI prompts (MAKE_TASK_RE etc).
    """
    name = "ai_chat"

    async def _should_respond(self, message: discord.Message) -> Tuple[bool, str]:
        """
        Normal AI trigger (NOT system controls).
        Returns (should, prompt_for_ai).
        """
        txt = (message.content or "").strip()
        if not message.guild:
            return False, ""

        # Never treat system prefix as normal AI prompt
        if txt.startswith(SYSTEM_PREFIX):
            return False, ""

        # AI listen channel: reply to normal text (ignore commands)
        if self.cfg.ai_listen_channel_id and message.channel.id == self.effective_ai_listen_channel_id(message.guild.id):
            if txt.startswith("!"):  # includes !ai and any other command
                return False, ""
            return True, txt

        # Explicit !ai
        if txt.lower().startswith(AI_PREFIX):
            return True, txt[len(AI_PREFIX):].strip()

        # Mention
        if self.bot.user and self.bot.user.mentioned_in(message):
            cleaned = txt.replace(f"<@{self.bot.user.id}>", "").replace(f"<@!{self.bot.user.id}>", "").strip()
            return True, cleaned

        return False, ""

    def _get_guild_ai(self, store: dict) -> dict:
        ai = store.get("ai") or {}
        store["ai"] = ai
        return ai

    def _save_store(self, data: dict, store: dict, guild_id: int) -> None:
        data.setdefault("guilds", {})
        data["guilds"][str(guild_id)] = store
        save_json_atomic(self.cfg.data_file, data)

    async def _handle_system_controls(self, message: discord.Message) -> bool:
        """
        Handle ONLY system controls under '!** ai ...'
        Returns True if consumed.
        """
        raw = (message.content or "").strip()
        if not raw.startswith(SYSTEM_PREFIX):
            return False

        tail = _strip_system_prefix(raw)
        if not tail:
            return True  # consumed but empty

        # Expect "ai ..." namespace
        low = tail.lower().strip()
        if not (low == "ai" or low.startswith("ai ")):
            return False  # not ours, allow other components to use !**

        # Strip leading "ai"
        rest = tail.strip()
        rest = rest[2:].strip() if rest.lower().startswith("ai") else rest
        tokens = rest.split() if rest else []
        head = tokens[0].lower() if tokens else "help"

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)
        ai = self._get_guild_ai(store)

        # Ensure ram_gb is always defined before any usage
        ram_gb = normalize_ram_gb(ai.get("ram_gb", DEFAULT_RAM_GB))
        ai["ram_gb"] = ram_gb

        provider, model = router.get_effective_provider_and_model(self.cfg, ai)

        if head in ("help", "?"):
            await message.channel.send(
                "**System AI controls (`!** ai ...`)**\n"
                "• `!** ai status`\n"
                "• `!** ai providers`\n"
                "• `!** ai provider set <ollama|openai>`\n"
                "• `!** ai model` / `!** ai model set <name>` / `!** ai model auto`\n"
                "• `!** ai models`\n"
                "• `!** ai ram` / `!** ai ram 4` / `!** ai ram 8`\n"
                "\n"
                "**Normal AI** remains: `!ai ...` (and AI listen channel)."
            )
            return True

        if head in ("current", "status"):
            await message.channel.send(
                "**AI status**\n"
                f"• Provider: `{provider}`\n"
                f"• Model: `{model}`\n"
                f"• RAM cap: `{ram_gb}GB` (max `{MAX_RAM_GB}GB`)\n"
                "• Normal chat: `!ai ...` / AI listen channel\n"
                "• System controls: `!** ai ...`"
            )
            return True

        # provider / providers
        if head in ("providers", "provider"):
            if head == "providers" or len(tokens) == 0:
                await message.channel.send(
                    f"**LLM provider**: `{provider}`\n"
                    f"Supported: {', '.join(router.SUPPORTED_PROVIDERS)}\n"
                    f"Set: `!** ai provider set <{'|'.join(router.SUPPORTED_PROVIDERS)}>`"
                )
                return True

            if len(tokens) >= 3 and tokens[1].lower() == "set":
                newp = tokens[2].strip().lower()
                if newp not in router.SUPPORTED_PROVIDERS:
                    await message.channel.send(f"❌ Unknown provider. Supported: {', '.join(router.SUPPORTED_PROVIDERS)}")
                    return True
                ai["provider"] = newp
                ai.pop("model", None)  # clear to allow default selection
                self._save_store(data, store, message.guild.id)
                await message.channel.send(f"✅ Provider set to `{newp}` (model cleared; use `!** ai models`).")
                return True

            await message.channel.send(f"❌ Usage: `!** ai provider set <{'|'.join(router.SUPPORTED_PROVIDERS)}>`")
            return True

        # model / models
        if head in ("model", "models"):
            if head == "model" and len(tokens) == 1:
                await message.channel.send(
                    f"**Provider:** `{provider}`\n"
                    f"**Model:** `{model}`\n"
                    "Set: `!** ai model set <name>`"
                )
                return True

            if head == "model" and len(tokens) >= 3 and tokens[1].lower() == "set":
                newm = " ".join(tokens[2:]).strip()
                if not newm:
                    await message.channel.send("❌ Usage: `!** ai model set <model_name>`")
                    return True

                # Only enforce RAM fit for local models (ollama)
                if provider == "ollama":
                    if not model_fits_ram(newm, ram_gb):
                        est = estimate_ram_gb(newm)
                        est_txt = f"~{est}GB" if est is not None else "unknown size"
                        await message.channel.send(
                            f"❌ `{newm}` is not allowed under the current RAM cap (`{ram_gb}GB`).\n"
                            f"Estimated: {est_txt}\n"
                            "Use: `!** ai ram 8` (max) or pick a smaller model."
                        )
                        return True

                ai["model"] = newm
                self._save_store(data, store, message.guild.id)
                await message.channel.send(f"✅ Model set to `{newm}` for provider `{provider}`.")
                return True

            if head == "model" and len(tokens) == 2 and tokens[1].lower() in ("auto", "small"):
                ai.pop("model", None)
                self._save_store(data, store, message.guild.id)
                await message.channel.send("✅ Model cleared. Run `!** ai models` to auto-pick a small one.")
                return True

            # list available models
            try:
                models = await router.list_models(self.cfg, provider)
            except Exception as e:
                await message.channel.send(f"⚠️ Model list error ({provider}): {e}")
                return True

            if not models:
                await message.channel.send(f"❌ No models found for `{provider}`.")
                return True

            # auto-pick small if none set
            if not (ai.get("model") or "").strip():
                picked = await router.choose_small_model_if_possible(self.cfg, provider, models, ram_gb=ram_gb)
                if picked:
                    ai["model"] = picked
                    self._save_store(data, store, message.guild.id)
                    provider, model = router.get_effective_provider_and_model(self.cfg, ai)

            show = models[:25]
            lines = [f"**Provider:** `{provider}`", f"**Current model:** `{model}`", "", "**Available (top 25):**"]
            lines += [f"- `{m}`" for m in show]
            if len(models) > 25:
                lines.append(f"… +{len(models)-25} more")
            lines.append("")
            lines.append("Set: `!** ai model set <name>` | Auto-pick: `!** ai model auto`")
            await message.channel.send("\n".join(lines)[:1900])
            return True

        # ram
        if head == "ram":
            if len(tokens) == 1:
                await message.channel.send(
                    "**Local model RAM limit**\n"
                    f"• Current: `{ram_gb}GB`\n"
                    "• Set: `!** ai ram 2` or `!** ai ram 4` or `!** ai ram 8`\n"
                    f"• Max: `{MAX_RAM_GB}GB`"
                )
                return True

            try:
                wanted = int(tokens[1])
            except Exception:
                await message.channel.send("❌ Usage: `!** ai ram 2` or `!** ai ram 4` or `!** ai ram 8`")
                return True

            if wanted not in (4, 8):
                await message.channel.send("❌ RAM must be 2, 4, or 8 (no higher).")
                return True

            ai["ram_gb"] = normalize_ram_gb(wanted)
            ai.pop("model", None)  # force re-pick under new cap
            self._save_store(data, store, message.guild.id)
            await message.channel.send(f"✅ RAM limit set to `{wanted}GB`. Run `!** ai models` to pick a model.")
            return True

        await message.channel.send("❌ Unknown system command. Try `!** ai help`.")
        return True

    async def _handle_taskify_flow(self, message: discord.Message, prompt: str, provider: str, model: str) -> bool:
        if not message.guild:
            return True

        if MAKE_TASK_RE.search(prompt or ""):
            key = (message.guild.id, message.channel.id)
            buf = self.state.context_buffers.get(key, [])
            now_ts = time.time()

            picked = select_conversation_burst(
                buf=buf,
                now_ts=now_ts,
                lookback_s=self.cfg.taskify_lookback_s,
                silence_gap_s=self.cfg.taskify_silence_gap_s,
                min_messages=max(4, self.cfg.taskify_min_messages),
                min_authors=max(1, min(self.cfg.taskify_min_authors, 2)),
                target_max_messages=self.cfg.taskify_target_max_messages,
            )
            if not picked:
                await message.channel.send("❌ Not enough recent chat to taskify (yet).")
                return True

            conv = _render_conversation(message.guild, picked)
            if not conv.strip():
                await message.channel.send("❌ Nothing to taskify.")
                return True

            try:
                task_text = await router.taskify(self.cfg, conv, provider=provider, model=model)
            except Exception as e:
                await message.channel.send(f"⚠️ AI error: {e}")
                return True

            tasks = parsing.extract_tasks_from_ai_reply(task_text)
            if not tasks:
                await message.channel.send("❌ No clear tasks found.")
                return True

            ts0, ts1 = picked[0][2], picked[-1][2]
            span_s = max(0, int(ts1 - ts0))
            source = f"Taskified from <#{message.channel.id}> (~{len(picked)} msgs / {span_s}s) by {message.author.display_name}"

            ukey = (message.guild.id, message.channel.id, message.author.id)
            self.state.last_taskify_draft[ukey] = {"tasks": tasks[:20], "ts": time.time(), "source": source}

            show = tasks[:10]
            desc_lines = [f"**{i+1})** {t}" for i, t in enumerate(show)]
            e = discord.Embed(title="📝 Draft tasks from recent chat", description="\n".join(desc_lines), color=0xF2C94C)
            e.set_footer(text="Use `!ai 1` to pick one, or `!ai make it a card` to create TODO card(s).")
            await message.channel.send(embed=e)

            self.state.last_ai_reply_ts[(message.guild.id, message.channel.id)] = time.time()
            return True

        m = PICK_TASK_RE.match((prompt or "").strip())
        if m:
            idx = int(m.group(1))
            ukey = (message.guild.id, message.channel.id, message.author.id)
            draft = self.state.last_taskify_draft.get(ukey)
            tasks = (draft or {}).get("tasks") or []
            if not tasks:
                return False  # let normal chat handle it
            if idx < 1 or idx > len(tasks):
                await message.channel.send(f"❌ Pick 1-{len(tasks)}.")
                return True
            chosen = tasks[idx - 1].strip()
            self.state.last_taskify_draft[ukey]["tasks"] = [chosen]
            await message.channel.send(f"✅ Selected:\n1) {chosen}\nNow run `!ai make it a card`.")
            return True

        if MAKE_CARD_RE.search(prompt or ""):
            ukey = (message.guild.id, message.channel.id, message.author.id)
            draft = self.state.last_taskify_draft.get(ukey)
            tasks = (draft or {}).get("tasks") or []
            if not tasks:
                await message.channel.send("❌ No draft tasks. Use `!ai make that a task` first.")
                return True

            source = (draft or {}).get("source") or f"<#{message.channel.id}> / {message.author.display_name}"

            from .todo_capture import TodoCapture  # local import to avoid cycles
            todo_comp = None
            for c in getattr(self.bot, "_disrello_components", []):
                if isinstance(c, TodoCapture):
                    todo_comp = c
                    break
            if not todo_comp:
                await message.channel.send("❌ TodoCapture component is not enabled.")
                return True

            await todo_comp._post_todo_cards(message.guild, message.author, tasks[:20], source=source)
            self.state.last_taskify_draft.pop(ukey, None)
            await message.channel.send(f"✅ Created **{min(len(tasks), 20)}** card(s) in <#{self.cfg.todo_channel_id}>.")
            return True

        return False

    async def _maybe_fast_delete(self, message: discord.Message, prompt: str) -> bool:
        m = parsing.AI_DELETE_RE.search(prompt or "")
        if not m:
            return False
        card_id = m.group(1)

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)
        todo_board = resolve_board(store, self.cfg.todo_board_name)
        if not todo_board:
            await message.channel.send("❌ TODO board not found.")
            return True
        ok = delete_card(todo_board, card_id)
        save_json_atomic(self.cfg.data_file, data)
        await message.channel.send("🗑️ Deleted." if ok else "❌ Card not found.")
        return True

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        # 1) System controls: !** ai ...
        if await self._handle_system_controls(message):
            return

        # 2) Normal AI flows
        should, prompt = await self._should_respond(message)
        if not should:
            return

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)
        settings = store.get("settings") or {}
        ai = self._get_guild_ai(store)

        ram_gb = normalize_ram_gb(ai.get("ram_gb", DEFAULT_RAM_GB))
        ai["ram_gb"] = ram_gb

        if not _cooldown_ok(self.state, self.cfg, message.guild.id, message.channel.id, settings):
            return

        provider, model = router.get_effective_provider_and_model(self.cfg, ai)

        # If no explicit model stored, attempt to pick a small one once.
        if not (ai.get("model") or "").strip() and self.cfg.prefer_small_models:
            try:
                avail = await router.list_models(self.cfg, provider)
                picked = await router.choose_small_model_if_possible(self.cfg, provider, avail, ram_gb=ram_gb)
                if picked:
                    ai["model"] = picked
                    self._save_store(data, store, message.guild.id)
                    provider, model = router.get_effective_provider_and_model(self.cfg, ai)
            except Exception:
                pass

        # Taskify flow
        if await self._handle_taskify_flow(message, prompt, provider=provider, model=model):
            return

        # Quick delete
        if await self._maybe_fast_delete(message, prompt):
            return

        # Context
        key = (message.guild.id, message.channel.id)
        buf = self.state.context_buffers.get(key, [])
        recent = buf[-self.cfg.ollama_context_messages :] if buf else []
        context_lines = [c for (_a, c, _t) in recent]

        # Redirect admin-ish normal commands to system prefix
        p0 = (prompt or "").strip().split()
        if p0:
            head = p0[0].lower()
            if head in ("ram", "status", "current", "providers", "provider", "model", "models"):
                await message.channel.send("ℹ️ System controls moved to `!** ai ...` (example: `!** ai status`).")
                return

        try:
            reply = await router.chat(self.cfg, prompt, context_lines, provider=provider, model=model)
        except Exception as e:
            await message.channel.send(f"⚠️ AI error: {e}")
            self.state.last_ai_reply_ts[key] = time.time()
            return

        reply = (reply or "").strip()
        if reply:
            await message.channel.send(reply[:1900])
        self.state.last_ai_reply_ts[key] = time.time()

        # Auto capture tasks from AI reply
        auto_capture = bool(settings.get("auto_capture_tasks_from_ai", self.cfg.auto_capture_tasks_from_ai))
        if auto_capture:
            tasks = parsing.extract_tasks_from_ai_reply(reply)
            if tasks:
                from .todo_capture import TodoCapture
                todo_comp = None
                for c in getattr(self.bot, "_disrello_components", []):
                    if isinstance(c, TodoCapture):
                        todo_comp = c
                        break
                if todo_comp:
                    source = f"AI in <#{message.channel.id}> / {message.author.display_name}"
                    await todo_comp._offer_confirm(message, tasks[:8], source=source)

