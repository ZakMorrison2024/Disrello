Disrello

Disrello is a modular Discord productivity bot that combines:

-   Lightweight Trello-style boards, lists, and cards
-   AI chat with provider abstraction (Ollama / OpenAI-compatible)
-   Smart task extraction (“make that a task”)
-   Channel summarisation
-   Search across boards and summaries
-   Guild-level system controls

It is designed to be self-hostable, extensible, and safe by default.

------------------------------------------------------------------------

FEATURES

BOARDS, LISTS & CARDS - Create boards, lists, and cards via commands -
Personal inbox-style boards - Assign cards to users - Track progress
(0–100%) - Toggle done/undone - Delete safely with permission checks -
Render boards, lists, or cards with rich embeds

AI CHAT (MULTI-PROVIDER) Supports: - Ollama (local LLMs) -
OpenAI-compatible APIs (OpenAI, Groq, etc.)

Features: - RAM-based model gating (for local models) - Auto-select
small models if enabled - Channel “AI listen mode” - Per-guild provider
& model control

TASKIFY FLOW

Turn conversation into structured tasks:

!ai make that a task

-   Extracts only explicitly stated tasks
-   Allows selecting specific extracted tasks
-   Can convert to TODO cards instantly

SUMMARISE

!summarise

Outputs: Topic: Key points: Decisions: Open questions:

Summaries are stored and searchable.

SEARCH

System-level search:

!** search

Supports filters: - assigned:me - from:me

Searches: - Cards - Stored summaries

------------------------------------------------------------------------

ARCHITECTURE

disrello/ ├── ai/ # Provider abstraction (Ollama / OpenAI) ├──
components/ # Bot features (AI, search, settings, commands) ├── ui/ #
Embed rendering ├── model.py # Board/List/Card data model ├── storage.py
# JSON persistence ├── config.py # Bot configuration └── context.py #
Conversation buffering

Key Concepts: - Component system: Each feature is isolated -
Guild-scoped storage: All data stored per guild in JSON - Provider
abstraction layer: AI routing handled via router.py - Safe RAM gating:
Prevents loading oversized local models - System command namespace: !**
reserved for admin/system controls

------------------------------------------------------------------------

SETUP

1.  Install dependencies
2.  Configure environment variables (.env)
3.  Run the bot

Example providers: - LLM_PROVIDER=ollama - LLM_PROVIDER=openai

------------------------------------------------------------------------
