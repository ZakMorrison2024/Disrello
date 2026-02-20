from __future__ import annotations

import discord

from .base import Component
from ..model import guild_store
from ..storage import load_json, save_json_atomic

SYSTEM_PREFIX = "!**"

SAFE_KEYS = {
    "auto_capture_tasks_from_ai",
    "forward_todos_from_other_channels",
    "ai_cooldown_s",
}


def _strip_system_prefix(content: str) -> str:
    s = (content or "").strip()
    if not s.startswith(SYSTEM_PREFIX):
        return ""
    return s[len(SYSTEM_PREFIX) :].lstrip()


def _to_bool(s: str):
    v = (s or "").strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return None


class Settings(Component):
    name = "settings"

    async def on_ready(self) -> None:
        # Hydrate in-memory channel overrides from JSON (per-guild)
        try:
            data = load_json(self.cfg.data_file)
            guilds = data.get("guilds") or {}
            for gid_str, gstore in guilds.items():
                try:
                    gid = int(gid_str)
                except Exception:
                    continue
                ov = gstore.get("channel_overrides") or {}
                if isinstance(ov, dict) and ov:
                    self.state.guild_channel_overrides[gid] = {
                        k: int(v) for k, v in ov.items() if k in ("todo", "ai", "sys")
                    }
        except Exception:
            return

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        raw = (message.content or "").strip()
        if not raw.startswith(SYSTEM_PREFIX):
            return

        tail = _strip_system_prefix(raw)
        if not tail:
            return

        # Channel override commands (debug/admin):
        # !** todo_channel #channel
        # !** ai_chat #channel
        # !** sys_channel #channel
        parts = tail.split()
        if parts:
            head = parts[0].lower()
            if head in ("todo_channel", "ai_chat", "sys_channel"):
                cid = None
                if message.channel_mentions:
                    cid = int(message.channel_mentions[0].id)
                elif len(parts) >= 2:
                    raw_id = parts[1].strip().lstrip("<#").rstrip(">")
                    try:
                        cid = int(raw_id)
                    except Exception:
                        cid = None

                if not cid:
                    await message.channel.send(f"❌ Usage: `!** {head} #channel`")
                    return

                data = load_json(self.cfg.data_file)
                store = guild_store(data, message.guild.id)
                ov = store.get("channel_overrides") or {}
                key_map = {"todo_channel": "todo", "ai_chat": "ai", "sys_channel": "sys"}
                ov[key_map[head]] = int(cid)
                store["channel_overrides"] = ov
                save_json_atomic(self.cfg.data_file, data)

                self.state.guild_channel_overrides[int(message.guild.id)] = {
                    k: int(v) for k, v in ov.items() if k in ("todo", "ai", "sys")
                }

                await message.channel.send(f"✅ Set `{head}` to <#{cid}>.")
                return

        # Settings commands:
        if not tail.lower().startswith("setting") and not tail.lower().startswith("settings"):
            return

        parts = tail.split()
        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)
        settings = store.get("settings") or {}
        store["settings"] = settings

        if len(parts) == 1:
            lines = ["**Guild settings (stored in JSON)**"]
            for k in sorted(SAFE_KEYS):
                lines.append(f"- `{k}` = `{settings.get(k, '(default)')}`")
            lines.append("")
            lines.append("Use: `!** setting set <key> <value>`")
            await message.channel.send("\n".join(lines))
            return

        if len(parts) >= 2 and parts[1].lower() == "set":
            if len(parts) < 4:
                await message.channel.send("❌ Usage: `!** setting set <key> <value>`")
                return
            key = parts[2].strip()
            if key not in SAFE_KEYS:
                await message.channel.send(f"❌ Key not allowed. Allowed: {', '.join(sorted(SAFE_KEYS))}")
                return
            value_raw = " ".join(parts[3:]).strip()

            if key in ("auto_capture_tasks_from_ai", "forward_todos_from_other_channels"):
                bv = _to_bool(value_raw)
                if bv is None:
                    await message.channel.send("❌ Value must be true/false.")
                    return
                settings[key] = bool(bv)
            elif key == "ai_cooldown_s":
                try:
                    settings[key] = float(value_raw)
                except Exception:
                    await message.channel.send("❌ ai_cooldown_s must be a number.")
                    return
            else:
                settings[key] = value_raw

            save_json_atomic(self.cfg.data_file, data)
            await message.channel.send(f"✅ Set `{key}` = `{settings[key]}`")
            return

        await message.channel.send("❌ Usage: `!** setting` or `!** setting set <key> <value>`")
