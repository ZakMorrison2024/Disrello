from __future__ import annotations

import datetime

import discord

from .base import Component
from .. import parsing
from ..model import (
    clamp_int,
    delete_card,
    ensure_default_list,
    find_card,
    get_or_create_list,
    get_or_create_personal_board,
    guild_store,
    parse_bool,
    resolve_board,
    resolve_list,
    uid,
    upsert_member,
)
from ..storage import load_json, save_json_atomic
from ..ui.embeds import (
    embed_board,
    embed_card,
    embed_help_ai,
    embed_help_system,
    embed_list,
    embed_render,
    embed_board,
)

SYSTEM_PREFIX = "!**"


class DisrelloCommands(Component):
    name = "disrello_commands"

    async def _get_todo_channel(self, guild: discord.Guild):
        todo_id = self.effective_todo_channel_id(guild.id)
        todo_chan = guild.get_channel(todo_id)
        if todo_chan is None:
            try:
                todo_chan = await guild.fetch_channel(todo_id)  # type: ignore[attr-defined]
            except Exception:
                try:
                    todo_chan = await self.bot.fetch_channel(todo_id)
                except Exception:
                    todo_chan = None
        if not isinstance(todo_chan, (discord.TextChannel, discord.Thread)):
            return None
        return todo_chan

    async def _post_to_todo(
        self,
        message: discord.Message,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ):
        todo_id = self.effective_todo_channel_id(message.guild.id)
        if int(message.channel.id) == int(todo_id):
            if embed is not None:
                await message.channel.send(embed=embed)
            else:
                await message.channel.send(content or "")
            return

        todo_chan = await self._get_todo_channel(message.guild)
        if todo_chan is None:
            await message.channel.send("❌ TODO channel not found/configured.")
            return

        if embed is not None:
            await todo_chan.send(embed=embed)
        else:
            await todo_chan.send(content or "")

        await message.channel.send(f"✅ Posted in <#{todo_id}>.")

    def _is_admin(self, member: discord.Member) -> bool:
        perms = getattr(member, "guild_permissions", None)
        return bool(perms and (perms.administrator or perms.manage_guild))

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return

        content = (message.content or "").strip()

        # System prefix is reserved for admin/system controls. We only provide system help here.
        if content.startswith(SYSTEM_PREFIX):
            c_low = content.lower().replace(" ", "")
            if c_low == "!**help":
                await message.channel.send(
                    embed=embed_help_system(self.cfg.ai_listen_channel_id, self.cfg.todo_channel_id)
                )
            return

        if not content.startswith("!"):
            return

        parsed = parsing.parse_function_call(content) or parsing.parse_shortcut(content)
        if not parsed:
            cl = content.lower().strip()
            if cl.startswith("!cardscreate"):
                await message.channel.send(
                    '❌ Usage: `!cardscreate <BoardNameOrId> [List] "Card name" "Description"`'
                )
                return
            if cl.startswith("!listscreate"):
                await message.channel.send('❌ Usage: `!listscreate <BoardNameOrId> "List name"`')
                return
            if cl.startswith("!boardscreate"):
                await message.channel.send('❌ Usage: `!boardscreate "Board name"`')
                return
            if cl.startswith("!delete"):
                await message.channel.send(
                    '❌ Usage: `!delete card <CardNameOrId>` or `!delete list <ListNameOrId>` or `!delete board <BoardNameOrId>` or `!delete all`'
                )
                return
            if cl.startswith("!render"):
                await message.channel.send('❌ Usage: `!render "BoardRef"` or `!render boards|lists|cards`')
                return
            return

        cmd = parsed["cmd"]
        action = parsed["action"]
        board_ref = parsed.get("board_ref")
        list_name = parsed.get("list_name")
        args = parsed.get("args", [])
        raw_rest = parsed.get("raw_rest", "")

        if cmd == "help":
            await message.channel.send(
                embed=embed_help_ai(self.cfg.ai_listen_channel_id, self.cfg.todo_channel_id)
            )
            return

        # delegated commands (still normal ! commands)
        if cmd in ("ai", "summarise", "summarize", "search", "setting", "settings"):
            return

        data = load_json(self.cfg.data_file)
        store = guild_store(data, message.guild.id)

        # --- Plural listing commands ---
        if cmd == "boards":
            boards = store.get("boards") or []
            if boards:
                lines = ["**Boards:**"]
                for b in boards:
                    lines.append(f'- `{b.get("id")}` → **{b.get("name")}**')
                await message.channel.send("\n".join(lines)[:1900])
            else:
                await message.channel.send("(No boards yet.)")
            return

        if cmd == "lists":
            boards = store.get("boards") or []
            if not boards:
                await message.channel.send("(No boards yet.)")
                return
            lines = ["**Lists (all boards):**"]
            for b in boards:
                ensure_default_list(b)
                for lst in b.get("lists") or []:
                    lines.append(
                        f'- **{b.get("name")}** → `{lst.get("id")}` **{lst.get("name")}** ({len(lst.get("cards") or [])} cards)'
                    )
            save_json_atomic(self.cfg.data_file, data)
            await message.channel.send("\n".join(lines)[:1900])
            return

        if cmd == "cards":
            target_id = message.author.id
            if message.mentions:
                target_id = message.mentions[0].id

            lines = [f"**Cards assigned to <@{target_id}>:**"]
            found = False
            for b in store.get("boards") or []:
                ensure_default_list(b)
                for lst in b.get("lists") or []:
                    for c in lst.get("cards") or []:
                        if int(c.get("assigned_to") or 0) != int(target_id):
                            continue
                        found = True
                        title = (c.get("title") or "")[:80]
                        lines.append(
                            f'- `{c.get("id")}` **{title}** (board: **{b.get("name")}**, list: **{lst.get("name")}**)'
                        )

            save_json_atomic(self.cfg.data_file, data)
            if not found:
                await message.channel.send("(No assigned cards.)")
                return
            await message.channel.send("\n".join(lines)[:1900])
            return

        # --- Render command ---
        if cmd == "render":
            tail = (raw_rest or "").strip()

            # !render "BoardRef"
            if action == "shortcut" and board_ref and not args and not list_name:
                b = resolve_board(store, board_ref)
                if not b:
                    await message.channel.send("❌ Board not found.")
                    return
                ensure_default_list(b)
                save_json_atomic(self.cfg.data_file, data)
                for e in embed_render(b):
                    await message.channel.send(embed=e)
                return

            t_low = tail.lower().strip()
            if t_low in ("boards", "board"):
                if not store.get("boards"):
                    await message.channel.send("(No boards yet.)")
                    return
                for b in store.get("boards") or []:
                    ensure_default_list(b)
                    await message.channel.send(embed=embed_board(b))
                save_json_atomic(self.cfg.data_file, data)
                return

            if t_low in ("lists", "list"):
                if not store.get("boards"):
                    await message.channel.send("(No boards yet.)")
                    return
                for b in store.get("boards") or []:
                    ensure_default_list(b)
                    for lst in b.get("lists") or []:
                        await message.channel.send(embed=embed_list(b, lst))
                save_json_atomic(self.cfg.data_file, data)
                return

            if t_low in ("cards", "card"):
                if not store.get("boards"):
                    await message.channel.send("(No boards yet.)")
                    return
                for b in store.get("boards") or []:
                    ensure_default_list(b)
                    for lst in b.get("lists") or []:
                        for c in lst.get("cards") or []:
                            await message.channel.send(embed=embed_card(b, lst, c))
                save_json_atomic(self.cfg.data_file, data)
                return

            await message.channel.send('❌ Usage: `!render "BoardRef"` or `!render boards|lists|cards`')
            return

        # --- Delete command ---
        if cmd == "delete":
            tail = (raw_rest or "").strip()
            if tail.lower().strip() == "all":
                removed = 0
                for b in store.get("boards") or []:
                    ensure_default_list(b)
                    for lst in b.get("lists") or []:
                        cards = lst.get("cards") or []
                        keep = []
                        for c in cards:
                            if int(c.get("assigned_to") or 0) == int(message.author.id):
                                removed += 1
                            else:
                                keep.append(c)
                        lst["cards"] = keep
                save_json_atomic(self.cfg.data_file, data)
                await message.channel.send(f"🗑️ Deleted {removed} card(s) assigned to you.")
                return

            parts = tail.split(maxsplit=1)
            if len(parts) < 2:
                await message.channel.send('❌ Usage: `!delete card <CardNameOrId>` or `!delete all`')
                return
            kind = parts[0].lower().strip()
            ref_raw = parts[1].strip()

            quoted = parsing.extract_quoted_args(ref_raw)
            ref = (quoted[0] if quoted else ref_raw).strip().strip('"')
            if not ref:
                await message.channel.send('❌ Usage: `!delete card <CardNameOrId>` or `!delete all`')
                return

            if kind == "card":
                for b in store.get("boards") or []:
                    ensure_default_list(b)
                    for lst in b.get("lists") or []:
                        cards = lst.get("cards") or []
                        for i, c in enumerate(list(cards)):
                            cid = (c.get("id") or "").strip()
                            title = (c.get("title") or "").strip()
                            if cid.lower() == ref.lower() or title.lower() == ref.lower():
                                is_owner = (
                                    int(c.get("assigned_to") or 0) == int(message.author.id)
                                    or int(c.get("created_by") or 0) == int(message.author.id)
                                )
                                if not is_owner and not self._is_admin(message.author):
                                    await message.channel.send("❌ You can only delete your own cards.")
                                    return
                                del cards[i]
                                save_json_atomic(self.cfg.data_file, data)
                                await message.channel.send("🗑️ Card deleted.")
                                return
                await message.channel.send("❌ Card not found.")
                return

            if kind == "list":
                for b in store.get("boards") or []:
                    ensure_default_list(b)
                    lists = b.get("lists") or []
                    for i, lst in enumerate(list(lists)):
                        lid = (lst.get("id") or "").strip()
                        lname = (lst.get("name") or "").strip()
                        if lid.lower() == ref.lower() or lname.lower() == ref.lower():
                            creator_ok = int(lst.get("created_by") or 0) == int(message.author.id)
                            if not creator_ok and not self._is_admin(message.author):
                                await message.channel.send("❌ Only admins (or the list creator) can delete lists.")
                                return
                            del lists[i]
                            save_json_atomic(self.cfg.data_file, data)
                            await message.channel.send("🗑️ List deleted.")
                            return
                await message.channel.send("❌ List not found.")
                return

            if kind == "board":
                boards = store.get("boards") or []
                for i, b in enumerate(list(boards)):
                    bid = (b.get("id") or "").strip()
                    bname = (b.get("name") or "").strip()
                    if bid.lower() == ref.lower() or bname.lower() == ref.lower():
                        creator_ok = int(b.get("created_by") or 0) == int(message.author.id)
                        if not creator_ok and not self._is_admin(message.author):
                            await message.channel.send("❌ Only admins (or the board creator) can delete boards.")
                            return
                        del boards[i]
                        store["boards"] = boards
                        save_json_atomic(self.cfg.data_file, data)
                        await message.channel.send("🗑️ Board deleted.")
                        return
                await message.channel.send("❌ Board not found.")
                return

            await message.channel.send('❌ Usage: `!delete card <CardNameOrId>` or `!delete all`')
            return

        # --- Board command ---
        if cmd == "board":
            if action == "shortcut":
                if not board_ref and not raw_rest:
                    if store.get("boards"):
                        lines = ["**Boards:**"]
                        for b in store.get("boards") or []:
                            lines.append(f'- `{b.get("id")}` → **{b.get("name")}**')
                        await message.channel.send("\n".join(lines)[:1900])
                    else:
                        await message.channel.send("(No boards yet.)")
                    return

                if not board_ref:
                    await message.channel.send('❌ Usage: `!board "NameOrId"`')
                    return

                b = resolve_board(store, board_ref)
                if not b:
                    b = {"id": uid("board"), "name": board_ref.strip(), "lists": [], "created_by": message.author.id}
                    ensure_default_list(b)
                    (store.get("boards") or []).append(b)
                    store["boards"] = store.get("boards") or [b]
                    save_json_atomic(self.cfg.data_file, data)
                    await self._post_to_todo(message, content=f'📋 Board created: **{b["name"]}** (`{b["id"]}`)')
                    return

                ensure_default_list(b)
                save_json_atomic(self.cfg.data_file, data)
                await message.channel.send(embed=embed_board(b))
                return

            if action == "create":
                if not board_ref:
                    await message.channel.send(
                        '❌ Usage: `!boardscreate "Board name"` (or legacy: `!board(create) "Name"`)'
                    )
                    return
                if resolve_board(store, board_ref):
                    await message.channel.send("❌ Board already exists.")
                    return
                b = {"id": uid("board"), "name": board_ref.strip(), "lists": [], "created_by": message.author.id}
                ensure_default_list(b)
                store.setdefault("boards", []).append(b)
                save_json_atomic(self.cfg.data_file, data)
                await self._post_to_todo(message, content=f'📋 Board created: **{b["name"]}** (`{b["id"]}`)')
                return

            if action == "view":
                if not board_ref:
                    await message.channel.send('❌ Usage: `!board(view) "NameOrId"`')
                    return
                b = resolve_board(store, board_ref)
                if not b:
                    await message.channel.send("❌ Board not found.")
                    return
                ensure_default_list(b)
                save_json_atomic(self.cfg.data_file, data)
                await message.channel.send(embed=embed_board(b))
                return

            if action == "list":
                if not board_ref:
                    if not store.get("boards"):
                        await message.channel.send("No boards yet.")
                        return
                    lines = ["**Boards:**"]
                    for b in store.get("boards") or []:
                        lines.append(f'- `{b.get("id")}` → **{b.get("name")}**')
                    await message.channel.send("\n".join(lines)[:1900])
                    return

                b = resolve_board(store, board_ref)
                if not b:
                    await message.channel.send("❌ Board not found.")
                    return
                ensure_default_list(b)

                if list_name:
                    lst = get_or_create_list(b, list_name)
                    save_json_atomic(self.cfg.data_file, data)
                    await message.channel.send(embed=embed_list(b, lst))
                    return

                lines = [f'**Lists in {b.get("name")}:**']
                for lst in b.get("lists") or []:
                    lines.append(
                        f'- `{lst.get("id")}` → **{lst.get("name")}** ({len(lst.get("cards") or [])} cards)'
                    )
                await message.channel.send("\n".join(lines)[:1900])
                return

            await message.channel.send("❌ Unknown board action.")
            return

        # --- List command ---
        if cmd == "list":
            usage = (
                '!list create "Board" "List name"  OR  !list "List name"  '
                '(also supports: `!listscreate <BoardNameOrId> "List name"` and legacy: `!list(create) "Board" [List]`)'
            )

            if action not in ("create", "shortcut"):
                await message.channel.send(f"❌ Usage: `{usage}`")
                return

            # Shorthand: !list "List name" -> personal inbox board
            if board_ref and not args and not list_name:
                list_title = board_ref
                board_ref = None
            else:
                if not board_ref:
                    await message.channel.send(f"❌ Usage: `{usage}`")
                    return
                list_title = list_name or (args[0] if args else None)
                if not list_title:
                    await message.channel.send(f"❌ Usage: `{usage}`")
                    return

            if board_ref:
                b = resolve_board(store, board_ref)
                if not b:
                    b = {"id": uid("board"), "name": str(board_ref).strip()[:200], "lists": []}
                    ensure_default_list(b)
                    store.setdefault("boards", []).append(b)
            else:
                b = get_or_create_personal_board(store, message.author)

            ensure_default_list(b)
            lst = get_or_create_list(b, str(list_title).strip()[:200])
            lst.setdefault("created_by", message.author.id)
            save_json_atomic(self.cfg.data_file, data)
            await self._post_to_todo(message, embed=embed_list(b, lst))
            return

        # --- Card command ---

        if cmd == "card":
            if action == "create":
                usage = (
                    '!card create "Board" "List" "Title" ("Desc")  '
                    'OR  !card create "Title"  '
                    '(also supports: `!cardscreate <BoardNameOrId> [List] "Title" "Desc"` '
                    'and legacy: `!card(create) "Board" [List] "Title" ("Desc")`)'
                )

                # Shorthand: !card create "Title"  -> personal inbox board + default list
                if board_ref and not args and not list_name:
                    title = board_ref
                    desc = ""
                    board_ref = None
                else:
                    if not board_ref:
                        await message.channel.send(f"❌ Usage: `{usage}`")
                        return
                    if not args or not (args[0] or "").strip():
                        await message.channel.send(f"❌ Usage: `{usage}`")
                        return

                    # Form: !card create "Board" "List" "Title" ("Desc")
                    if (not list_name) and len(args) >= 2:
                        list_name = args[0]
                        title = args[1]
                        desc = args[2] if len(args) > 2 else ""
                    else:
                        title = args[0]
                        desc = args[1] if len(args) > 1 else ""

                # Resolve board (auto-create if missing); if no board_ref -> personal inbox
                if board_ref:
                    b = resolve_board(store, board_ref)
                    if not b:
                        b = {"id": uid("board"), "name": str(board_ref).strip()[:200], "lists": []}
                        ensure_default_list(b)
                        store.setdefault("boards", []).append(b)
                else:
                    b = get_or_create_personal_board(store, message.author)

                ensure_default_list(b)

                if list_name:
                    lst = get_or_create_list(b, list_name)
                    lst.setdefault("created_by", message.author.id)
                else:
                    lst = ensure_default_list(b)

                c = {
                    "id": uid("card"),
                    "title": (title or "").strip()[:200],
                    "desc": (desc or "").strip()[:2000],
                    "done": False,
                    "progress": 0,
                    "assigned_to": message.author.id,
                    "created": datetime.datetime.utcnow().isoformat(),
                    "created_by": message.author.id,
                }
                lst.setdefault("cards", []).append(c)
                save_json_atomic(self.cfg.data_file, data)
                await self._post_to_todo(message, embed=embed_card(b, lst, c))
                return
                if not args or not (args[0] or "").strip():
                    await message.channel.send(f"❌ Usage: `{usage}`")
                    return

                title = args[0]
                desc = args[1] if len(args) > 1 else ""

                b = resolve_board(store, board_ref)
                if not b:
                    await message.channel.send("❌ Board not found.")
                    return
                ensure_default_list(b)

                if list_name:
                    lst = get_or_create_list(b, list_name)
                    lst.setdefault("created_by", message.author.id)
                else:
                    lst = ensure_default_list(b)

                c = {
                    "id": uid("card"),
                    "title": title.strip()[:200],
                    "desc": (desc or "").strip()[:2000],
                    "done": False,
                    "progress": 0,
                    "assigned_to": message.author.id,
                    "created": datetime.datetime.utcnow().isoformat(),
                    "created_by": message.author.id,
                }
                lst.setdefault("cards", []).append(c)
                save_json_atomic(self.cfg.data_file, data)
                await self._post_to_todo(message, embed=embed_card(b, lst, c))
                return

            if action == "list":
                if not board_ref:
                    await message.channel.send('❌ Usage: `!card(list) "BoardRef"` (optional [List])')
                    return
                b = resolve_board(store, board_ref)
                if not b:
                    await message.channel.send("❌ Board not found.")
                    return
                ensure_default_list(b)
                if list_name:
                    lst = get_or_create_list(b, list_name)
                    save_json_atomic(self.cfg.data_file, data)
                    await message.channel.send(embed=embed_list(b, lst))
                    return
                for lst in b.get("lists") or []:
                    await message.channel.send(embed=embed_list(b, lst))
                return

            if action in ("done", "toggle", "progress", "delete"):
                if not board_ref:
                    await message.channel.send(
                        '❌ Usage: `!card(done|toggle|progress|delete) "BoardRef" card_xxxxxx ...`'
                    )
                    return
                b = resolve_board(store, board_ref)
                if not b:
                    await message.channel.send("❌ Board not found.")
                    return

                card_id = args[0] if args else None
                if not card_id:
                    tokens = content.strip().split()
                    card_id = tokens[-1] if tokens else ""
                if not str(card_id).startswith("card_"):
                    await message.channel.send("❌ Missing card id.")
                    return

                if action == "delete":
                    ok = delete_card(b, str(card_id))
                    save_json_atomic(self.cfg.data_file, data)
                    await message.channel.send("🗑️ Deleted." if ok else "❌ Card not found.")
                    return

                found = find_card(b, str(card_id))
                if not found:
                    await message.channel.send("❌ Card not found in that board.")
                    return
                lst, c = found

                if action == "done":
                    if len(args) < 2:
                        await message.channel.send('❌ Usage: `!card(done) "Board" card_xxxxxx true|false`')
                        return
                    bv = parse_bool(args[1])
                    if bv is None:
                        await message.channel.send("❌ Value must be true/false.")
                        return
                    c["done"] = bool(bv)
                    if c["done"]:
                        c["progress"] = max(int(c.get("progress", 0)), 100)
                    save_json_atomic(self.cfg.data_file, data)
                    await message.channel.send(embed=embed_card(b, lst, c))
                    return

                if action == "toggle":
                    c["done"] = not bool(c.get("done"))
                    if c["done"]:
                        c["progress"] = max(int(c.get("progress", 0)), 100)
                    save_json_atomic(self.cfg.data_file, data)
                    await message.channel.send(embed=embed_card(b, lst, c))
                    return

                if action == "progress":
                    if len(args) < 2:
                        await message.channel.send('❌ Usage: `!card(progress) "Board" card_xxxxxx 0-100`')
                        return
                    try:
                        p = int(args[1])
                    except Exception:
                        await message.channel.send("❌ Progress must be an integer 0-100.")
                        return
                    p = clamp_int(p, 0, 100)
                    c["progress"] = p
                    if p >= 100:
                        c["done"] = True
                    save_json_atomic(self.cfg.data_file, data)
                    await message.channel.send(embed=embed_card(b, lst, c))
                    return

            await message.channel.send("❌ Unknown card action.")
            return
