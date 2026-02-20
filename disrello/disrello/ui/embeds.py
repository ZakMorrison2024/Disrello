from __future__ import annotations

from typing import Any, Dict, List, Optional

import discord

from ..model import ensure_default_list

COLOR_PRIMARY = 0x5865F2
COLOR_INFO = 0x2F80ED
COLOR_WARN = 0xF2C94C
COLOR_SUMMARY = 0x8E44AD
COLOR_SEARCH = 0x2ECC71


def help_text(ai_listen_channel_id: int, todo_channel_id: int) -> str:
    # Legacy plaintext help (kept for backwards compatibility)
    return (
        "**Disrello — Command Reference**\n"
        "Use quotes for names with spaces.\n\n"

        "**AI**\n"
        f"• Always-on chat: <#{ai_listen_channel_id}>\n"
        "• Other channels: `!ai <message>` or @mention the bot\n"

        "• Current AI: `!ai model` (or `!ai current` if enabled)\n"
        "• Providers: `!ai providers` / `!ai provider set <ollama|openai>`\n"
        "• Models: `!ai models` / `!ai model set <name>` / `!ai model auto`\n"
        "• RAM cap (ollama): `!ai ram` / `!ai ram 4` / `!ai ram 8`\n"

        "• Taskify: `!ai make that a task` → `!ai 1` (optional) → `!ai make it a card`\n\n"

        "**TODO capture (any channel)**\n"
        f"• Feed channel: <#{todo_channel_id}>\n"
        "• Checkbox TODO: `- [ ] something` or `TODO: something`\n"
        "• Intent capture (asks confirm): `remind me to ...`, `I need to ...`, `add a task: ...`\n\n"

        "**Boards / Lists / Cards**\n"
        '• Boards: `!board` / `!board "Name"` / `!board(create) "Name"` / `!board(list)`\n'
        '• Lists: `!list create "Board" [List]`\n'
        '• Cards: `!card create "Board" [List] "Title" ("Desc")`\n'
        '• Render: `!render "Board"`\n'
        '• Card updates: `!card(done)` / `!card(toggle)` / `!card(progress)` / `!card(delete)`\n\n'

        "**Summaries & Search**\n"
        "• Summarise: `!summarise` / `!summarise(save)`\n"
        "• Search: `!search <text>` (filters: `assigned:me`, `from:me`)\n\n"

        "**Settings**\n"
        "• View: `!setting`\n"
        "• Set: `!setting set <key> <value>`\n"
    )


def embed_help_ai(ai_listen_channel_id: int, todo_channel_id: int) -> discord.Embed:
    """AI-facing help (normal !help)."""
    e = discord.Embed(
        title="Disrello — AI Commands",
        description="Use quotes for names with spaces. Use `!**help` for system/admin controls.",
        color=COLOR_PRIMARY,
    )
    e.add_field(
        name="AI chat",
        value=(
            f"• Always-on chat: <#{ai_listen_channel_id}>\n"
            "• Other channels: `!ai <message>` or @mention the bot\n"
            "• Summarise: `!summarise` / `!summarise(save)`\n"
            "• Search: `!search <query>` (filters: `assigned:me`, `from:me`)"
        ),
        inline=False,
    )
    # IMPORTANT: use single-quoted python strings so we can show double-quotes in examples safely.
    e.add_field(
        name="Boards / lists / cards",
        value=(
            '• Help: `!help`  (system/admin: `!** help`)\n'
            '• Render: `!render` / `!render boards` / `!render lists` / `!render cards`\n'
            '• Boards: `!board` / `!board create "Name"` / `!board(view) "NameOrId"` / `!boardscreate "Name"`\n'
            '• Lists (view): `!board list "Board"` or `!board(list) "Board" [List]`\n'
            '• Create list: `!list create "Board" "List"`  OR  shorthand: `!list "List"` (your personal inbox)\n'
            '• Create card: `!card create "Board" "List" "Title" ("Desc")`\n'
            '  - also: `!card(create) "Board" [List] "Title" ("Desc")`\n'
            '  - shorthand: `!card create "Title"` (your personal inbox)\n'
            '• Mark done: `!card done "Board" card_id` (or legacy: `!card(done) "Board" card_id`)\n'
            '• Delete: `!delete card <CardNameOrId>` / `!delete list <ListNameOrId>` / `!delete board <BoardNameOrId>`'

        ),
        inline=False,
    )
    e.add_field(
        name="Tips",
        value=f"• TODO channel: <#{todo_channel_id}>\n• Use IDs when names collide.",
        inline=False,
    )
    return e


def embed_help_system(ai_listen_channel_id: int, todo_channel_id: int) -> discord.Embed:
    """System/admin help (!**help)."""
    e = discord.Embed(
        title="Disrello — System Commands",
        description="These are admin/system controls (prefix `!**`).",
        color=COLOR_WARN,
    )
    e.add_field(
        name="AI system controls",
        value=(
            "• `!** ai status`\n"
            "• `!** ai providers`\n"
            "• `!** ai provider set <ollama|openai|...>`\n"
            "• `!** ai models`\n"
            "• `!** ai model` / `!** ai model set <name>` / `!** ai model auto`\n"
            "• `!** ai ram` / `!** ai ram 4` / `!** ai ram 8`"
        ),
        inline=False,
    )
    e.add_field(
        name="Channels",
        value=(f"• AI listen channel: <#{ai_listen_channel_id}>\n• TODO channel: <#{todo_channel_id}>"),
        inline=False,
    )
    
    e.add_field(
        name="Channel overrides",
        value=(
            "• `!** todo_channel #channel` (set TODO destination)\n"
            "• `!** ai_chat #channel` (set AI listen channel)\n"
            "• `!** sys_channel #channel` (set system/admin channel, if used)"
        ),
        inline=False,
    )
    e.set_footer(text="If a system command isn't listed, it may be disabled by COMPONENTS or not installed.")
    return e


def embed_board(board: Dict[str, Any]) -> discord.Embed:
    ensure_default_list(board)
    lists = board.get("lists") or []
    e = discord.Embed(
        title=f"📋 {board.get('name','(unnamed)')}",
        description=f"Board ID: `{board.get('id','')}`\nLists: **{len(lists)}**",
        color=COLOR_PRIMARY,
    )
    if lists:
        lines = []
        for lst in lists[:20]:
            lines.append(
                f"• **{lst.get('name','(unnamed)')}** (`{lst.get('id','')}`) — {len(lst.get('cards') or [])} cards"
            )
        e.add_field(name="Lists", value="\n".join(lines)[:1024], inline=False)
    return e


def embed_list(board: Dict[str, Any], lst: Dict[str, Any]) -> discord.Embed:
    cards = lst.get("cards") or []
    e = discord.Embed(
        title=f"🗂️ {lst.get('name','(unnamed)')}",
        description=f'Board: **{board.get("name","")}** (`{board.get("id","")}`)\n'
        f'List ID: `{lst.get("id","")}`\nCards: **{len(cards)}**',
        color=COLOR_INFO,
    )

    if cards:
        lines = []
        for c in cards[:15]:
            done = "✅" if c.get("done") else "⏳"
            prog = int(c.get("progress", 0) or 0)
            lines.append(f"{done} `{c.get('id','')}` — **{c.get('title','(untitled)')}** ({prog}%)")
        e.add_field(name="Cards", value="\n".join(lines)[:1024], inline=False)
    else:
        e.add_field(name="Cards", value="*None*", inline=False)
    return e


def embed_card(board: Dict[str, Any], lst: Dict[str, Any], card: Dict[str, Any]) -> discord.Embed:
    prog = int(card.get("progress", 0) or 0)
    e = discord.Embed(
        title=card.get("title", "(untitled)"),
        description=card.get("desc") or "*No description*",
        color=COLOR_WARN,
    )
    e.add_field(name="Board", value=f"{board.get('name','')} (`{board.get('id','')}`)", inline=False)
    e.add_field(name="List", value=f"{lst.get('name','')} (`{lst.get('id','')}`)", inline=False)
    e.add_field(name="Status", value="✅ Done" if card.get("done") else "⏳ Open", inline=True)
    e.add_field(name="Progress", value=f"{prog}%", inline=True)
    assignee = card.get("assigned_to")
    if assignee:
        e.add_field(name="Assigned", value=f"<@{assignee}>", inline=True)
    e.set_footer(text=f"Card ID: {card.get('id','')}")
    return e


def embed_render(board: Dict[str, Any]) -> List[discord.Embed]:
    """Returns multiple embeds: header + one per list."""
    ensure_default_list(board)
    embeds: List[discord.Embed] = []
    header = discord.Embed(
        title=f"🧾 Render: {board.get('name','(unnamed)')}",
        description=f"Board ID: `{board.get('id','')}`",
        color=COLOR_PRIMARY,
    )
    embeds.append(header)
    for lst in board.get("lists") or []:
        embeds.append(embed_list(board, lst))
    return embeds


def embed_task_confirm(items: List[str]) -> discord.Embed:
    preview = "\n".join([f"• {it}" for it in items])[:900]
    return discord.Embed(
        title="Create TODO card(s)?",
        description=f"I think you meant to create these task(s):\n{preview}\n\nReply **yes** to confirm or **no** to cancel.",
        color=COLOR_WARN,
    )


def embed_todo_capture(
    items: List[str],
    card_ids: List[str],
    source: str,
    author_id: int,
    todo_board_name: str,
    todo_inbox_list_name: str,
) -> discord.Embed:
    e = discord.Embed(
        title="🧠→🗂️ Captured tasks",
        description=f"Source: {source}\nAssignee: <@{author_id}>\nReact ✅ to mark **all** done.",
        color=COLOR_WARN,
    )
    lines = [f"⏳ **{it}**\n`{cid}`" for it, cid in zip(items, card_ids)]
    e.add_field(name="Cards", value="\n\n".join(lines)[:1024] or "*None*", inline=False)
    e.set_footer(text=f'TODO Board: "{todo_board_name}" → "{todo_inbox_list_name}"')
    return e


def embed_summary(summary: str, keywords: List[str], saved_id: Optional[str] = None) -> discord.Embed:
    e = discord.Embed(
        title="🧠 Channel summary",
        description=(summary[:3800] + ("\n…(trimmed)" if len(summary) > 3800 else "")),
        color=COLOR_SUMMARY,
    )
    if keywords:
        e.add_field(name="Topic keywords", value=", ".join(keywords[:12])[:1024], inline=False)
    if saved_id:
        e.set_footer(text=f"Saved as {saved_id} (searchable)")
    return e


def embed_search(query_raw: str, card_lines: List[str], summary_lines: List[str]) -> discord.Embed:
    """Used by disrello/components/search.py"""
    e = discord.Embed(
        title="🔎 Search results",
        description=f"Query: `{query_raw}`",
        color=COLOR_SEARCH,
    )

    cards_body = "\n".join(card_lines)[:1024] if card_lines else "*No matching cards*"
    sums_body = "\n".join(summary_lines)[:1024] if summary_lines else "*No matching summaries*"

    e.add_field(name=f"Cards ({len(card_lines)})", value=cards_body, inline=False)
    e.add_field(name=f"Summaries ({len(summary_lines)})", value=sums_body, inline=False)
    return e


# Backwards/alternate helper (kept for convenience)
def embed_search_results(title: str, lines: List[str]) -> discord.Embed:
    body = "\n".join(lines)[:3800] if lines else "*No matches*"
    return discord.Embed(title=title, description=body, color=COLOR_SEARCH)

