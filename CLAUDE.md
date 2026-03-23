# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
export PATH="$HOME/.local/bin:$PATH"    # required before uv commands

# Tests
uv run pytest src/ -v                   # all tests
uv run pytest src/piazza/tools/expenses/handler_test.py -v  # single file
uv run pytest src/ -k "test_name" -v    # single test by name
uv run pytest src/ --cov=src/piazza     # with coverage

# Lint & type check
uv run ruff check src/
uv run mypy src/piazza/

# Local services (requires Docker)
docker compose up -d                    # redis + ollama
docker compose -f docker-compose.prod.yml up -d  # full stack with evolution-api
```

## Architecture

**WhatsApp group productivity agent** — expense tracking, reminders, itinerary, notes, and group status via WhatsApp.

### Message Flow

```
WhatsApp → Evolution API → /webhook (HMAC verify) → parse_webhook()
  → arq queue (Redis) → process_message_job
  → L1 regex sanitizer → L2 ML guard (llm-guard)
  → _run_agent(): OpenSourceAgent (Ollama) → ClaudeAgent (fallback)
  → tool execution → WhatsApp response
```

### Two-Tier LLM Agents

Both tiers are full agents with tool use (not classifiers). They share `BaseAgent._execute()` for the tool loop and differ only in LLM API calls.

- **OpenSourceAgent**: Ollama (qwen3.5:4b), OpenAI-compatible format, 10s timeout
- **ClaudeAgent**: Anthropic (haiku-4-5), native format, 15s timeout
- **Fallback logic** lives in `workers/process_message.py:_run_agent()`, not in agent classes
- **Circuit breaker**: 3 failures in 120s → 600s cooldown on Ollama

### Tool Pattern

Tools follow a consistent layered pattern:
- **handler.py**: Entry point — takes `(session, group_id, member_id, entities)` → returns response text
- **service.py**: Business logic, calls repositories
- **formatter.py**: Formats data for WhatsApp messages
- **registry.py**: Maps tool names to handlers, defines tool schemas in Anthropic format
- **schemas.py**: `Entities` Pydantic model with optional fields matching tool input schemas

### Layer Separation

```
db/models/       → SQLAlchemy models
db/repositories/  → Data access (get_, create_, delete_, find_, get_or_create_)
tools/*/service   → Business logic
tools/*/handler   → Tool entry points
messaging/        → WhatsApp transport (webhook, parser, client)
workers/          → arq jobs, message processing pipeline
agent/            → LLM agent implementations
```

### Security Pipeline

- **L1** (`workers/security/sanitizer.py`): Regex patterns for XSS, SQL injection, command injection
- **L2** (`workers/security/guard.py`): ML/heuristic screening via llm-guard with risk scoring
- Blocked messages logged to `injection_log` table

## Conventions

- **Test files**: `*_test.py` co-located with source (e.g., `handler_test.py` next to `handler.py`)
- **Test fixtures** in `src/piazza/conftest.py`: `db_session` (in-memory SQLite), `sample_group` (Alice/Bob/Charlie), `redis_client` (fakeredis)
- **All tests are async** (`pytest-asyncio` with `asyncio_mode="auto"`)
- **Private helpers** at top of files, **public API** at bottom
- **Ruff**: line-length 100, target Python 3.12
- **Singletons** for agents (`agent/__init__.py`) and WhatsApp client (`messaging/whatsapp/__init__.py`)
- **Domain verbs** for repo functions: `cancel_`, `snooze_`, `deactivate_` (not just CRUD)
