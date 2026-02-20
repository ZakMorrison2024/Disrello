from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Function-call form: !cmd(action) ...
OP_RE = re.compile(r"^\!(\w+)\((\w+)\)\s*(.*)$")
BRACKET_RE = re.compile(r"\[([^\[\]]+)\]")
QUOTE_RE = re.compile(r'"([^"]*)"')

TODO_CHECKBOX_RE = re.compile(r"^\s*-\s*\[\s*\]\s+(.+?)\s*$", re.IGNORECASE)
TODO_COLON_RE = re.compile(r"\bTODO:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

AI_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")
AI_DELETE_RE = re.compile(r"\bdelete\s+(?:task|todo|card)\s+(card_[0-9a-f]+)\b", re.IGNORECASE)

TASK_AFTER_RE = re.compile(r"\b(?:add|create|make|log|track|capture)\b\s+(?:a\s+)?(?:task|todo|card)\b\s*[:\-–]?\s*(.+)$", re.IGNORECASE)
REMIND_ME_RE = re.compile(r"\bremind\s+me\s+to\s+(.+)$", re.IGNORECASE)
I_NEED_TO_RE = re.compile(r"\b(?:i\s+need\s+to|i\s+have\s+to|i\s+should)\s+(.+)$", re.IGNORECASE)

YES_RE = re.compile(r"^\s*!?(?:yes|y|yeah|yep|ok|okay|confirm|do\s+it)\s*$", re.IGNORECASE)
NO_RE = re.compile(r"^\s*!?(?:no|n|nah|nope|cancel|stop)\s*$", re.IGNORECASE)


def extract_bracket_list(text: str) -> Tuple[Optional[str], str]:
    """Extract a single [List Name] bracket from text."""
    if not text:
        return None, ""
    m = BRACKET_RE.search(text)
    if not m:
        return None, text.strip()
    list_name = m.group(1).strip()
    remaining = (text[: m.start()] + text[m.end() :]).strip()
    return list_name, remaining


def extract_quoted_args(text: str) -> List[str]:
    """Extract "quoted" args (supports multiple quoted segments)."""
    if not text:
        return []
    return [q.strip() for q in QUOTE_RE.findall(text)]


def parse_function_call(raw: str) -> Optional[Dict[str, Any]]:
    """Parse !cmd(action) style calls."""
    m = OP_RE.match((raw or "").strip())
    if not m:
        return None
    cmd = m.group(1).lower()
    action = m.group(2).lower()
    rest = m.group(3).strip()
    list_name, rest_wo_list = extract_bracket_list(rest)
    quoted = extract_quoted_args(rest_wo_list)
    board_ref = quoted[0] if quoted else None
    args = quoted[1:] if quoted else []
    return {
        "cmd": cmd,
        "action": action,
        "board_ref": board_ref,
        "list_name": list_name,
        "args": args,
        "raw_rest": rest,
        "raw_rest_wo_list": rest_wo_list,
    }


def parse_shortcut(raw: str) -> Optional[Dict[str, Any]]:
    """Parse !cmd ... shortcuts.

    Supported forms:
    - Legacy fused: !cardscreate / !listscreate / !boardscreate
    - Action token: !card create ... / !list create ... / !board create ...
    - Optional [List] bracket anywhere after the command/action.
    - Names with spaces must be in "quotes".
    """
    raw = (raw or "").strip()
    if not raw.startswith("!"):
        return None

    first = raw.split(maxsplit=1)[0]
    cmd_raw = first[1:].lower()
    rest = raw[len(first):].strip() if len(raw) > len(first) else ""

    fused_map = {
        "cardscreate": ("card", "create"),
        "listscreate": ("list", "create"),
        "boardscreate": ("board", "create"),
    }
    if cmd_raw in fused_map:
        cmd, action = fused_map[cmd_raw]
    else:
        cmd, action = cmd_raw, "shortcut"

    allowed = {
        "board","list","card","boards","lists","cards","render","delete","help",
        "ai","summarise","summarize","search","setting","settings",
        "create","add","view","done",
    }
    if cmd not in allowed:
        return None

    if action == "shortcut" and cmd in ("board", "list", "card"):
        tok = _first_token_outside_quotes(rest)
        if tok and tok.lower() in ("create", "view", "list", "done"):
            action = tok.lower()
            rest = rest[len(tok):].lstrip()

    list_name, rest_wo_list = extract_bracket_list(rest)
    quoted = extract_quoted_args(rest_wo_list)

    board_ref = quoted[0] if quoted else None
    args = quoted[1:] if quoted else []

    if action == "create" and board_ref is None:
        tok = _first_token_outside_quotes(rest_wo_list)
        if tok:
            board_ref = tok

    return {
        "cmd": cmd,
        "action": action,
        "board_ref": board_ref,
        "list_name": list_name,
        "args": args,
        "raw_rest": rest,
        "raw_rest_wo_list": rest_wo_list,
    }


def extract_todos(text: str) -> List[str]:
    items: List[str] = []
    if not text:
        return items
    for line in (text or "").splitlines():
        m = TODO_CHECKBOX_RE.match(line)
        if m:
            it = (m.group(1) or "").strip()
            if it:
                items.append(it)
    m2 = TODO_COLON_RE.findall(text or "")
    for it in m2:
        it = (it or "").strip()
        if it:
            items.append(it)
    # de-dupe, keep order
    out: List[str] = []
    seen = set()
    for it in items:
        k = it.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def extract_tasks_from_ai_reply(text: str) -> List[str]:
    """Parse AI taskify output into a list of tasks."""
    if not text:
        return []
    out: List[str] = []
    for line in (text or "").splitlines():
        m = AI_BULLET_RE.match(line)
        if not m:
            continue
        t = (m.group(1) or "").strip()
        if not t or t.lower() == "no clear tasks":
            continue
        out.append(t[:200])
    # keep top 20
    return out[:20]


def extract_task_intent_items(text: str) -> List[str]:
    """Light intent detection for casual talk -> tasks."""
    if not text:
        return []
    c = (text or "").strip()
    m = TASK_AFTER_RE.search(c)
    if m:
        it = (m.group(1) or "").strip()
        if it:
            return [it[:200]]
    m = REMIND_ME_RE.search(c)
    if m:
        it = (m.group(1) or "").strip()
        if it:
            return [it[:200]]
    m = I_NEED_TO_RE.search(c)
    if m:
        it = (m.group(1) or "").strip()
        if it:
            return [it[:200]]
    return []


def _first_token_outside_quotes(text: str) -> Optional[str]:
    """Return first whitespace-delimited token, ignoring anything inside double quotes."""
    if not text:
        return None
    i = 0
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    if i >= n:
        return None
    if text[i] == '"':
        return None
    j = i
    while j < n and (not text[j].isspace()) and text[j] != '"':
        j += 1
    tok = text[i:j].strip()
    return tok or None

