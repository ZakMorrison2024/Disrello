from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import discord


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def uid(prefix: str) -> str:
    return f"{prefix}_{os.urandom(3).hex()}"


def norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def guild_store(data: Dict[str, Any], guild_id: int) -> Dict[str, Any]:
    gid = str(guild_id)
    if gid not in data["guilds"]:
        data["guilds"][gid] = {"members": {}, "boards": [], "summaries": [], "settings": {}}
    store = data["guilds"][gid]
    store.setdefault("members", {})
    store.setdefault("boards", [])
    store.setdefault("summaries", [])
    store.setdefault("settings", {})
    return store


def upsert_member(store: Dict[str, Any], member: discord.abc.User) -> None:
    uid_str = str(member.id)
    members = store.get("members") or {}
    entry = members.get(uid_str, {})
    entry["name"] = getattr(member, "display_name", None) or getattr(member, "name", None) or entry.get("name") or uid_str
    entry.setdefault("joined_ts", _now_iso())
    entry["last_seen_ts"] = _now_iso()
    members[uid_str] = entry
    store["members"] = members




def get_or_create_personal_board(store: Dict[str, Any], member: discord.abc.User) -> Dict[str, Any]:
    """Return the member's default/personal board (create if missing).

    Stored at: store["members"][<user_id>]["default_board_id"]
    """
    upsert_member(store, member)
    uid_str = str(member.id)
    members = store.get("members") or {}
    entry = members.get(uid_str) or {}

    bid = entry.get("default_board_id")
    if bid:
        b = resolve_board(store, str(bid))
        if b:
            ensure_default_list(b)
            return b

    display = entry.get("name") or getattr(member, "display_name", None) or getattr(member, "name", None) or uid_str
    base_name = f"{display} — Inbox"
    name = base_name
    n = 2
    while any(norm(b.get("name", "")) == norm(name) for b in (store.get("boards") or [])):
        name = f"{base_name} ({n})"
        n += 1

    b = {"id": uid("board"), "name": name, "lists": []}
    ensure_default_list(b)
    store.setdefault("boards", []).append(b)

    entry["default_board_id"] = b["id"]
    members[uid_str] = entry
    store["members"] = members
    return b

def resolve_board(store: Dict[str, Any], ref: str) -> Optional[Dict[str, Any]]:
    r = norm(ref)
    for b in store["boards"]:
        if norm(b["id"]) == r:
            return b
    for b in store["boards"]:
        if norm(b["name"]) == r:
            return b
    return None


def ensure_default_list(board: Dict[str, Any]) -> Dict[str, Any]:
    for lst in board["lists"]:
        if norm(lst["name"]) == "default":
            return lst
    d = {"id": uid("list"), "name": "default", "cards": []}
    board["lists"].append(d)
    return d


def resolve_list(board: Dict[str, Any], ref_or_name: str) -> Optional[Dict[str, Any]]:
    r = norm(ref_or_name)
    for lst in board["lists"]:
        if norm(lst["id"]) == r:
            return lst
    for lst in board["lists"]:
        if norm(lst["name"]) == r:
            return lst
    return None


def get_or_create_list(board: Dict[str, Any], list_name: Optional[str]) -> Dict[str, Any]:
    if not list_name or norm(list_name) == "default":
        return ensure_default_list(board)
    existing = resolve_list(board, list_name)
    if existing:
        return existing
    new_lst = {"id": uid("list"), "name": list_name.strip(), "cards": []}
    board["lists"].append(new_lst)
    return new_lst


def find_card(board: Dict[str, Any], card_id: str) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    r = norm(card_id)
    for lst in board["lists"]:
        for c in lst["cards"]:
            if norm(c["id"]) == r:
                return lst, c
    return None


def delete_card(board: Dict[str, Any], card_id: str) -> bool:
    r = norm(card_id)
    for lst in board["lists"]:
        before = len(lst["cards"])
        lst["cards"] = [c for c in lst["cards"] if norm(c.get("id")) != r]
        if len(lst["cards"]) != before:
            return True
    return False


def clamp_int(n: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, n))


def parse_bool(s: str) -> Optional[bool]:
    v = norm(s)
    if v in ("true", "yes", "y", "1", "on"):
        return True
    if v in ("false", "no", "n", "0", "off"):
        return False
    return None


def get_or_create_todo_board(store: Dict[str, Any], todo_board_name: str, todo_inbox_list_name: str) -> Dict[str, Any]:
    b = resolve_board(store, todo_board_name)
    if b:
        ensure_default_list(b)
        get_or_create_list(b, todo_inbox_list_name)
        return b
    b = {"id": uid("board"), "name": todo_board_name, "lists": []}
    ensure_default_list(b)
    get_or_create_list(b, todo_inbox_list_name)
    store["boards"].append(b)
    return b


def add_cards_to_todo_inbox(
    store: Dict[str, Any],
    todo_board_name: str,
    todo_inbox_list_name: str,
    author_id: int,
    items: List[str],
    source: str,
) -> List[str]:
    b = get_or_create_todo_board(store, todo_board_name, todo_inbox_list_name)
    inbox = get_or_create_list(b, todo_inbox_list_name)

    card_ids: List[str] = []
    for it in items:
        c = {
            "id": uid("card"),
            "title": it.strip()[:200],
            "desc": f"Captured from: {source}".strip(),
            "done": False,
            "progress": 0,
            "assigned_to": author_id,
            "created": _now_iso(),
            "created_by": author_id,
        }
        inbox["cards"].append(c)
        card_ids.append(c["id"])
    return card_ids


def store_channel_summary(store: Dict[str, Any], channel_id: int, author_id: int, summary_text: str, keywords: List[str]) -> str:
    sid = uid("sum")
    entry = {
        "id": sid,
        "channel_id": int(channel_id),
        "author_id": int(author_id),
        "created": _now_iso(),
        "keywords": keywords[:20],
        "summary": (summary_text or "").strip()[:8000],
    }
    arr = store.get("summaries") or []
    arr.append(entry)
    if len(arr) > 300:
        arr = arr[-300:]
    store["summaries"] = arr
    return sid

