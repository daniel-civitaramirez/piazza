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

# Migrations (ENCRYPTION_KEY must be set — migration 009 encrypts existing data)
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "..."
```

## Deployment

Production runs via `docker-compose.prod.yml` with 7 services: `redis`, `ollama`, `evolution-postgres`, `evolution-api`, `app`, `worker`, `caddy`. Caddy handles auto-TLS and reverse-proxies to `app:8000`.

### Required env vars

- `SUPABASE_DB_URL` — asyncpg-prefixed Supavisor transaction-mode URL (port 6543, `?ssl=require`)
- `ANTHROPIC_API_KEY`, `ENCRYPTION_KEY` (base64 32 bytes), `WEBHOOK_SECRET`, `REDIS_PASSWORD`
- `EVO_API_KEY`, `EVO_DB_PASSWORD`, `EVO_INSTANCE_NAME`, `BOT_JID`, `DOMAIN`
- Optional: `ADMIN_JID` (empty ⇒ auto-approve all groups), `SENTRY_DSN`, `OPENEXCHANGERATES_KEY`, `OLLAMA_MODEL` (override default `qwen3.5:4b`)

### Env vars set by compose (do NOT put in `.env`)

`EVO_API_URL`, `OLLAMA_URL`, `REDIS_URL`, `INJECTION_PATTERNS_PATH` — overridden to container hostnames by `docker-compose.prod.yml`.

### Supabase / asyncpg constraint

Connections go through Supavisor transaction mode (port 6543), which does not support prepared statements. `engine.py` sets `statement_cache_size=0` and `prepared_statement_cache_size=0` in `connect_args`. Do not use port 5432 or remove these flags.

### Files not in git

- `config/injection_patterns.json` — L1/L2 regex patterns, deployed out-of-band (scp). Both `app` and `worker` containers mount it read-only.
- `docs/mvp/piazza_config.md` — deployment secrets and infra references.

### Group approval

`Group.approval_status` is `pending` | `approved`. When `ADMIN_JID` is unset, new groups auto-approve. Otherwise approvals are flipped manually via SQL in Supabase.

### Sentry

`main.py` auto-initializes `sentry_sdk` when `SENTRY_DSN` is set. A `before_send` hook scrubs PII (message text, phone numbers, display names) from error reports.

### Health endpoint

`GET /health` reports per-service status (DB, Redis, Ollama, Evolution API, WhatsApp auth). WhatsApp `not authenticated` is expected until the Evolution API instance is linked via QR.

### Deploying code and/or DB changes to the VPS

Image layout: `./src` is bind-mounted into `app` and `worker` (compose), but `alembic/`, `pyproject.toml`, and `uv.lock` are COPYed at build time. This dictates which deploys need a rebuild.

Match the procedure to the change:

**1. Source-only change (no schema, no deps)** — fastest path, no rebuild:

```bash
ssh -i ~/.ssh/piazza_hetzner deploy@<vps-ip> && cd /opt/piazza
git pull origin main
docker compose -f docker-compose.prod.yml restart app worker
```

**2. Dependency change (`pyproject.toml` / `uv.lock`)** — rebuild required:

```bash
git pull origin main
docker compose -f docker-compose.prod.yml build app worker
docker compose -f docker-compose.prod.yml up -d app worker
```

**3. DB migration (with or without source changes)** — rebuild required so the new migration file lands in the image, then migrate **before** swapping containers to keep zero downtime:

```bash
git pull origin main
docker compose -f docker-compose.prod.yml build app worker

# One-shot container from the freshly built image; --rm auto-deletes.
# Uses the same Supavisor URL the app uses — alembic/env.py sets the
# statement_cache_size flags that make this work over port 6543.
docker compose -f docker-compose.prod.yml run --rm app uv run alembic current
docker compose -f docker-compose.prod.yml run --rm app uv run alembic upgrade head

# Only after migration succeeds, swap containers:
docker compose -f docker-compose.prod.yml up -d app worker
```

For migrations that backfill existing rows (e.g. defaulting a new column to a non-empty value for active groups), put the backfill in `upgrade()` — Alembic wraps the transaction. Verify with a `SELECT` in Supabase before swapping containers.

**4. `.env` change** — recreate (not restart) so compose re-reads the file:

```bash
docker compose -f docker-compose.prod.yml up -d app worker
```

**Things to never do**

- Don't `docker compose down` — it stops Caddy + Evolution API and breaks the WhatsApp session (requires QR re-link).
- Don't run alembic against a host-installed `uv`/Python — host may not have them; always go through the container.
- Don't override `SUPABASE_DB_URL` to the session-mode endpoint — `alembic/env.py` already handles Supavisor transaction mode.
- Don't swap containers before running the migration when adding a new schema-dependent column — the new code will crash on the missing column until the migration completes.

**After any deploy**, smoke test:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs app worker --tail 50
curl -fsS https://<DOMAIN>/health | jq
```

Other VPS-specific commands (SSH key, paths, Supabase project ID, Evolution API tunnel) live in the gitignored `docs/mvp/piazza_config.md`.

## Architecture

**WhatsApp group productivity agent** — expense tracking, reminders, itinerary, notes, and group status via WhatsApp.

### Message Flow

```
WhatsApp → Evolution API → /webhook (HMAC verify) → parse_webhook()
  → arq queue (Redis) → process_message_job
  → per-group rate limit (Redis) → per-group lock (Redis)
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
- **Disable Ollama tier entirely**: set `OPENSOURCE_AGENT_ENABLED=false` to skip straight to Claude (useful when Ollama is unavailable or unreliable on a given host). Default is `true`.

### Tool Pattern

Tools follow a consistent layered pattern:
- **handler.py**: Entry point — takes `(session, group_id, member_id, entities)` → returns `dict`
- **service.py**: Business logic, returns model objects or raises exceptions
- **registry.py**: Maps tool names to handlers, defines tool schemas in Anthropic format. `execute_tool` JSON-serializes handler dicts for the LLM.
- **schemas.py**: `Entities` Pydantic model with optional fields matching tool input schemas

### Structured Responses (Language-Agnostic)

Handlers return structured dicts (not English strings). The LLM receives JSON tool results and generates natural-language responses in the user's language. No formatters — the LLM handles all i18n.

Every handler dict has a `status` key: `"ok"`, `"empty"`, `"not_found"`, `"ambiguous"`, `"error"`, or `"list"`.

Services return model objects; handlers convert to dicts. Services raise `NotFoundError(entity, number=, query=)` for missing items — handlers catch and build `{"status": "not_found", ...}` dicts.

### Expense Splits

Expenses use a unified `participants: [{name, amount}]` format for both even and custom splits. The LLM always computes per-person amounts.

- **`add_expense` / `update_expense`**: `participants` is `[{name: str, amount: number}]` — each person who owes the payer and how much. Payer is never in participants.
- **`settle_expense`**: `participants` stays `list[str]` (single payee name). Unaffected.
- **Payer share**: computed by handler as `total - sum(participant_amounts)`. Must be >= 0.
- **"everyone"**: handler expands to all active members except payer, splits evenly.
- **Amount-only updates**: don't touch shares. The LLM asks a clarifying question for ambiguous redistributions.

### Item Identification

Mutation tools (delete, update, cancel) identify entries two ways:
- **`item_number`**: Position from the tool's `list_*`/`show_*` output (1-indexed). Always unambiguous.
- **`description`**: Substring match (Python-side, post-decryption). Returns disambiguation (bullets, no numbers) if >1 match.

Handlers branch: `item_number` first → `description` fallback → error if neither.
`*_by_number` service functions reuse the same repo query + ordering as the list function.

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

### Encryption at Rest

All user-generated content is encrypted at the application level before storage using AES-256-GCM (`core/encryption.py`). Supabase sees only opaque bytes.

**Encrypted columns**: `Expense.description`, `Reminder.message`, `ItineraryItem.title/location/notes`, `Note.content/tag`, `MessageLog.content`, `Member.display_name`, `Member.wa_id_encrypted`, `Group.name_encrypted`

**Repository pattern**: Repos encrypt on write, decrypt on read. Callers (services, handlers) always work with plaintext strings. Text search uses fetch-all + Python substring match (no ILIKE on ciphertext).

**Key helpers** in `core/encryption.py`: `encrypt`, `decrypt` (idempotent — safe for SQLAlchemy identity map reuse), `encrypt_nullable`, `decrypt_nullable`, `set_decrypted` (sets value without marking dirty in SQLAlchemy), `validate_key`.

**Message log retention**: After each message, entries beyond `conversation_context_limit * message_log_retention_multiplier` (default 10 * 2 = 20) are pruned per group. Configurable in settings.

### Rate Limiting

Per-group rate limiting via Redis sorted set in `process_message_job`. Default: `group_rate_limit_per_minute = 5`. Checked before the per-group lock — rate-limited messages return a static response without calling the LLM, so no cost is incurred. Configurable in settings.

### Security Pipeline

- **L1** (`workers/security/sanitizer.py`): Regex patterns for XSS, SQL injection, command injection
- **L2** (`workers/security/guard.py`): ML/heuristic screening via llm-guard with risk scoring
- Blocked messages logged via structured logging (no DB table — PII-free)

## Adding a New Tool

New tools must follow the existing patterns across all layers:

### File structure
Create `tools/<name>/` with: `handler.py`, `service.py`, `handler_test.py`, `service_test.py`. Add the repository in `db/repositories/<name>.py` with co-located `<name>_test.py`.

### Model → Repository → Service → Handler

1. **Model** (`db/models/`): Any user-content column must be `LargeBinary` (encrypted at rest). Non-content columns (IDs, timestamps, status flags, numeric amounts) stay as their native types.
2. **Repository** (`db/repositories/`): Encrypt user-content fields on write using `encrypt`/`encrypt_nullable` from `core/encryption.py`. Decrypt on read using `decrypt`/`decrypt_nullable` + `set_decrypted` (avoids SQLAlchemy dirty tracking). Text search replaces ILIKE with fetch-all + Python substring match. Repos accept and return plaintext strings — encryption is internal.
3. **Service** (`tools/*/service.py`): Business logic only. Receives/returns plaintext via repos. Raises `NotFoundError(entity, number=, query=)` for missing items. Must not import `settings` or `encrypt` directly — if a service mutates an encrypted column on a model object, it must go through the repo or encrypt inline.
4. **Handler** (`tools/*/handler.py`): Entry point with signature `(session, group_id, member_id, entities) → dict`. Catches `NotFoundError` and builds structured response dicts. Uses `item_number` first, `description` fallback for mutations.

### Registry
Add the tool to `tools/registry.py`: map tool name → handler function, define the schema in Anthropic tool format. The `Entities` model in `tools/schemas.py` must include any new input fields.

### Responses
Use builders from `tools/responses.py`: `ok_response`, `list_response`, `empty_response`, `not_found_response`, `ambiguous_response`, `error_response`. Every handler dict must have a `status` key.

### Logging
Log operational fields only (event name, counts, durations, action types). Never log PII: no JIDs, phone numbers, display names, message content, or user-generated text. Use `group_id` (UUID) for correlation where available.

### Testing
Co-located `*_test.py` files. All tests async. Use `db_session` and `sample_group` fixtures from `conftest.py`. Tests that create members directly must encrypt `display_name` with `TEST_ENCRYPTION_KEY`. Repository tests verify round-trip encryption (write → read → assert plaintext). Handler tests go through the full stack (no DB mocking).

### Migration
Add an alembic migration for any schema changes. Encrypted columns require a data migration that reads plaintext, encrypts with `core/encryption.py`, and writes back. `ENCRYPTION_KEY` must be set when running migrations.

## Conventions

- **Test files**: `*_test.py` co-located with source (e.g., `handler_test.py` next to `handler.py`)
- **Test fixtures** in `src/piazza/conftest.py`: `db_session` (in-memory SQLite), `sample_group` (Alice/Bob/Charlie), `redis_client` (fakeredis)
- **All tests are async** (`pytest-asyncio` with `asyncio_mode="auto"`)
- **Private helpers** at top of files, **public API** at bottom
- **Ruff**: line-length 100, target Python 3.12
- **Singletons** for agents (`agent/__init__.py`) and WhatsApp client (`messaging/whatsapp/__init__.py`)
- **Domain verbs** for repo functions: `cancel_`, `snooze_`, `deactivate_` (not just CRUD)
