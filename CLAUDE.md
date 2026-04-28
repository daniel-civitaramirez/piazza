# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
export PATH="$HOME/.local/bin:$PATH"    # required before uv commands

# Tests (pytest-asyncio in auto mode, files named *_test.py co-located with source)
uv run pytest src/ -v                                                # all tests
uv run pytest src/piazza/tools/expenses/handler_test.py -v           # single file
uv run pytest src/ -k "test_name" -v                                 # by name
uv run pytest src/ --cov=src/piazza                                  # with coverage

# Lint & type check
uv run ruff check src/                  # line-length 100, target Python 3.12
uv run mypy src/piazza/

# Run the API locally (matches Dockerfile CMD)
uv run uvicorn piazza.main:app --host 0.0.0.0 --port 8000 --reload

# Local services (requires Docker)
docker compose up -d                                       # redis + ollama only
docker compose -f docker-compose.prod.yml up -d            # full stack with evolution-api + caddy

# Migrations (ENCRYPTION_KEY must be set; some past migrations encrypt existing rows)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "..."
```

Tests do not require `ENCRYPTION_KEY` in the env — `src/piazza/conftest.py` monkeypatches `settings.encryption_key` to a fixed all-zero key (`TEST_ENCRYPTION_KEY_B64`) for every test session. If you create members directly in a test, encrypt their `display_name` and `wa_id_encrypted` with `TEST_ENCRYPTION_KEY` (the raw 32-byte form) — see `conftest.py:126-127` for the pattern.

## Architecture

WhatsApp group productivity agent: expense tracking, reminders, itinerary, notes, checklists, search, and group status, all driven from natural-language messages.

### Message flow

```
WhatsApp → Evolution API → /webhook (HMAC verify) → parse_webhook()
  → arq queue (Redis) → process_message_job
  → per-group rate limit (Redis) → per-group lock (Redis)
  → L1 regex sanitizer → L2 ML guard (llm-guard)
  → _run_agent(): OpenSourceAgent (Ollama) → ClaudeAgent (fallback)
  → tool execution → WhatsApp response
```

### Two-tier LLM agents

Both tiers are full agents with tool use, not classifiers. They share `BaseAgent._execute()` for the tool loop and differ only in the LLM API call.

- **OpenSourceAgent**: Ollama (default `qwen2.5:0.5b`, override via `OLLAMA_MODEL`), OpenAI-compatible format, 10s timeout.
- **ClaudeAgent**: Anthropic (haiku-4-5), native format, 15s timeout.
- **Fallback logic** lives in `workers/process_message.py:_run_agent()`, not in agent classes.
- **Circuit breaker**: 3 Ollama failures in 120s trip a 600s cooldown.
- **Disable Ollama tier entirely**: set `OPENSOURCE_AGENT_ENABLED=false` to skip straight to Claude (default `true`). Useful when Ollama is unavailable on a given host.

### Tool pattern (every tool follows this layering)

- `db/models/<name>.py` — SQLAlchemy model. User-content columns are `LargeBinary` (encrypted at rest).
- `db/repositories/<name>.py` — data access. Encrypts on write, decrypts on read. Callers always see plaintext. Text search is fetch-all + Python substring match (no ILIKE on ciphertext).
- `tools/<name>/service.py` — business logic. Returns model objects or raises `NotFoundError(entity, number=, query=)`. Must not import `settings` or `encrypt` directly; if mutating an encrypted column, go through the repo.
- `tools/<name>/handler.py` — entry point `(session, group_id, member_id, entities) → dict`. Catches `NotFoundError` and builds structured response dicts.
- `tools/registry.py` — maps tool name → handler, defines schema in Anthropic tool format. `execute_tool` JSON-serializes handler dicts for the LLM.
- `tools/schemas.py` — `Entities` Pydantic model with optional fields matching tool input schemas.

Existing tools: `expenses/`, `reminders/`, `itinerary/`, `notes/`, `checklist/`, `search/`, `status.py`.

### Structured, language-agnostic responses

Handlers return structured dicts, never English strings. The LLM receives JSON tool results and generates the natural-language reply in the user's language. No formatters, no i18n in code.

Every handler dict has a `status` key: `"ok"` | `"empty"` | `"not_found"` | `"ambiguous"` | `"error"` | `"list"`. Use the builders in `tools/responses.py` (`ok_response`, `list_response`, etc.) — don't hand-roll.

### Item identification (mutation tools)

Delete/update/cancel handlers identify the target two ways:
- `item_number` — 1-indexed position from the tool's `list_*`/`show_*` output. Always unambiguous.
- `description` — substring match (Python-side, post-decryption). Returns disambiguation bullets if more than one matches.

Handlers branch `item_number` first, `description` fallback, error if neither. `*_by_number` service functions reuse the same repo query + ordering as the corresponding list function.

### Expense splits

`add_expense` / `update_expense` use a unified `participants: [{name, amount}]` shape for both even and custom splits — the LLM always computes per-person amounts. Payer is never in `participants`. The handler computes payer share as `total - sum(participant_amounts)` and rejects if negative. `"everyone"` expands to all active members except payer, split evenly. Amount-only updates don't touch shares; the LLM asks a clarifying question for ambiguous redistributions. `settle_expense` keeps `participants: list[str]` (single payee).

### Encryption at rest

All user-generated content is encrypted at the application layer using AES-256-GCM (`core/encryption.py`) before hitting Postgres. Supabase only ever sees opaque bytes.

Encrypted columns: `Expense.description`, `Reminder.message`, `ItineraryItem.title/location/notes`, `Note.content/tag`, `MessageLog.content`, `Member.display_name`, `Member.wa_id_encrypted`, `Group.name_encrypted`. Add a new encrypted column? It must be `LargeBinary` and the repo must encrypt on write / decrypt on read.

Helpers in `core/encryption.py`: `encrypt`, `decrypt` (idempotent — safe for SQLAlchemy identity-map reuse), `encrypt_nullable`, `decrypt_nullable`, `set_decrypted` (sets value without marking the row dirty), `validate_key`.

Message-log retention: after each message, entries beyond `conversation_context_limit * message_log_retention_multiplier` (default 10 × 2 = 20) are pruned per group.

### Security pipeline

- L1 (`workers/security/sanitizer.py`): regex patterns for XSS, SQL injection, command injection.
- L2 (`workers/security/guard.py`): ML/heuristic screening via llm-guard with risk scoring.
- Blocked messages logged via structured logging only — no DB table, no PII.

### Rate limiting

Per-group sorted set in Redis, checked in `process_message_job` before the per-group lock. Default `group_rate_limit_per_minute = 5`. Rate-limited messages return a static response without invoking the LLM, so no token cost.

### Layer separation (don't cross these)

```
db/models/         → SQLAlchemy models
db/repositories/   → data access (get_, create_, delete_, find_, get_or_create_; domain verbs cancel_, snooze_, deactivate_)
tools/*/service    → business logic
tools/*/handler    → tool entry points
messaging/         → WhatsApp transport (webhook, parser, client, group_sync)
workers/           → arq jobs, security pipeline, message processing
agent/             → LLM agent implementations
admin/             → operational notifications (admin/notify.py)
```

## Deployment

Production runs `docker-compose.prod.yml` with 7 services: `redis`, `ollama`, `evolution-postgres`, `evolution-api`, `app`, `worker`, `caddy`. Caddy handles auto-TLS and reverse-proxies to `app:8000`. Image layout: `./src` is bind-mounted into `app` and `worker`, but `alembic/`, `pyproject.toml`, and `uv.lock` are COPYed at build time — that dictates which deploys need a rebuild.

VPS-specific runbook (SSH key, paths, Supabase project ID, the four deploy procedures by change type, post-deploy smoke tests, things to never do) lives in the gitignored `docs/mvp/piazza_config.md`. Read it before deploying.

### The two constraints that bite

- **Supavisor transaction mode (port 6543) does not support prepared statements.** `engine.py` and `alembic/env.py` both set `statement_cache_size=0` and `prepared_statement_cache_size=0` in `connect_args`. Don't use port 5432, don't remove these flags.
- **Never `docker compose down` on prod** — it stops Caddy and Evolution API, which kills the WhatsApp session and forces a QR re-link. Use `restart` or `up -d` to swap, never `down`.

### Required env vars

- `SUPABASE_DB_URL` — asyncpg-prefixed Supavisor transaction-mode URL (port 6543, `?ssl=require`)
- `ANTHROPIC_API_KEY`, `ENCRYPTION_KEY` (base64 32 bytes), `WEBHOOK_SECRET`, `REDIS_PASSWORD`
- `EVO_API_KEY`, `EVO_DB_PASSWORD`, `EVO_INSTANCE_NAME`, `BOT_JID`, `DOMAIN`
- Optional: `ADMIN_JID` (empty ⇒ auto-approve all groups), `SENTRY_DSN`, `OPENEXCHANGERATES_KEY`, `OLLAMA_MODEL` (override `qwen2.5:0.5b`), `OPENSOURCE_AGENT_ENABLED` (`false` to skip Ollama tier)

`EVO_API_URL`, `OLLAMA_URL`, `REDIS_URL`, `INJECTION_PATTERNS_PATH` are set by compose to container hostnames — do NOT put them in `.env`.

Files not in git that the running app needs: `config/injection_patterns.json` (L1/L2 regex patterns, scp'd out-of-band, mounted read-only into both `app` and `worker`); `docs/mvp/piazza_config.md` (deployment secrets and infra references).

### Group approval & health

`Group.approval_status` is `pending` | `approved`. When `ADMIN_JID` is unset, new groups auto-approve; otherwise flip them manually via SQL in Supabase.

`GET /health` reports per-service status (DB, Redis, Ollama, Evolution API, WhatsApp auth). WhatsApp `not authenticated` is expected until Evolution API is QR-linked.

`main.py` auto-initializes `sentry_sdk` when `SENTRY_DSN` is set. The `before_send` hook scrubs PII (message text, phone numbers, display names) from error reports.

## Adding a new tool

1. **Model** (`db/models/`) — user-content columns must be `LargeBinary`. IDs/timestamps/enums/numbers stay native.
2. **Repository** (`db/repositories/`) with co-located `*_test.py`. Encrypt on write via `encrypt`/`encrypt_nullable`. Decrypt on read via `decrypt`/`decrypt_nullable` + `set_decrypted` (avoids dirty tracking). Round-trip encryption tests required.
3. **Service** (`tools/<name>/service.py`) — business logic only. Plaintext in/out via repos. Raise `NotFoundError(entity, number=, query=)` for missing items. Add a `*_by_number` variant that reuses the list query + ordering.
4. **Handler** (`tools/<name>/handler.py`) — `(session, group_id, member_id, entities) → dict`. Catch `NotFoundError`, build via `tools/responses.py` builders. `item_number` first, `description` fallback for mutations.
5. **Registry** — add to `tools/registry.py` (handler map + Anthropic tool schema). Add new fields to `Entities` in `tools/schemas.py`.
6. **Migration** — alembic revision for any schema change. Encrypted columns require a data migration that reads plaintext, encrypts with `core/encryption.py`, and writes back. `ENCRYPTION_KEY` must be set when running migrations. Backfills go in `upgrade()` (Alembic wraps the txn); verify with `SELECT` before swapping containers.
7. **Tests** — handler tests go through the full stack (no DB mocking); use `db_session` and `sample_group` fixtures from `conftest.py` (Alice/Bob/Charlie). All tests async.
8. **Logging** — operational fields only (event name, counts, durations, action types). Never log JIDs, phone numbers, display names, message content, or any user-generated text. Use `group_id` (UUID) for correlation.

## Conventions

- Test files: `*_test.py` co-located with source. All tests async (`pytest-asyncio` `asyncio_mode="auto"`).
- Test fixtures in `src/piazza/conftest.py`: `db_session` (in-memory SQLite), `sample_group` (Alice/Bob/Charlie), `redis_client` (fakeredis).
- Private helpers at top of file, public API at bottom.
- Singletons: agents (`agent/__init__.py`), WhatsApp client (`messaging/whatsapp/__init__.py`).
- Repo function verbs: `get_`, `create_`, `delete_`, `find_`, `get_or_create_`, plus domain verbs `cancel_`, `snooze_`, `deactivate_`.
