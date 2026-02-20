from __future__ import annotations

import re
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

ContextBuffer = Dict[Tuple[int, int], List[Tuple[int, str, float]]]
KeywordMemory = Dict[Tuple[int, int], Counter]

_WORD_RE = re.compile(r"[a-zA-Z0-9_]{3,}")

_STOPWORDS = {
    "the","a","an","and","or","but","if","then","so","to","of","in","on","for","with","as","at","by","from","is","are","am","was","were",
    "be","been","being","it","this","that","these","those","i","you","we","they","he","she","me","my","your","our","their","them","him","her",
    "not","no","yes","ok","okay","lol","lmao","bro","mate","pls","please","yeah","yep","nah","idk","imo","im","dont","can't","cant","won't","wont"
}
CHANNEL_KEYWORD_LIMIT = 60


def push_context(buffers: ContextBuffer, guild_id: int, channel_id: int, author_id: int, content: str, limit: int) -> None:
    key = (guild_id, channel_id)
    buf = buffers.get(key, [])
    buf.append((author_id, content, time.time()))
    if len(buf) > limit:
        buf = buf[-limit:]
    buffers[key] = buf


def update_channel_keywords(mem: KeywordMemory, guild_id: int, channel_id: int, content: str) -> None:
    c = (content or "").lower()
    terms = [t for t in _WORD_RE.findall(c) if t not in _STOPWORDS and not t.isdigit()]
    if not terms:
        return
    key = (guild_id, channel_id)
    ctr = mem.get(key) or Counter()
    ctr.update(terms[:50])
    mem[key] = Counter(dict(ctr.most_common(CHANNEL_KEYWORD_LIMIT)))


def top_channel_keywords(mem: KeywordMemory, guild_id: int, channel_id: int, n: int = 8) -> List[str]:
    ctr = mem.get((guild_id, channel_id)) or Counter()
    return [k for (k, _) in ctr.most_common(max(1, n))]


def select_conversation_burst(
    buf: List[Tuple[int, str, float]],
    now_ts: float,
    lookback_s: int,
    silence_gap_s: int,
    min_messages: int,
    min_authors: int,
    target_max_messages: int,
) -> List[Tuple[int, str, float]]:
    if not buf:
        return []
    lo_ts = now_ts - float(max(30, lookback_s))
    recent = [x for x in buf if x[2] >= lo_ts]
    if not recent:
        return []

    picked_rev: List[Tuple[int, str, float]] = []
    last_ts: Optional[float] = None

    for author_id, content, ts in reversed(recent):
        if last_ts is None:
            picked_rev.append((author_id, content, ts))
            last_ts = ts
            continue

        if (last_ts - ts) > float(silence_gap_s):
            if len(picked_rev) >= int(min_messages):
                break

        picked_rev.append((author_id, content, ts))
        last_ts = ts

    picked = list(reversed(picked_rev))
    authors = {a for (a, _, _) in picked}

    if len(authors) < int(min_authors) and len(recent) > len(picked):
        for author_id, content, ts in reversed(recent[:-len(picked)]):
            picked.insert(0, (author_id, content, ts))
            authors.add(author_id)
            if len(authors) >= int(min_authors) and len(picked) >= int(min_messages):
                break

    if len(picked) > int(target_max_messages):
        picked = picked[-int(target_max_messages):]

    if len(picked) < int(min_messages):
        return []
    if len({a for (a, _, _) in picked}) < int(min_authors):
        return []
    return picked

