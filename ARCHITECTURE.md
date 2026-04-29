# Architecture

Piazza is a WhatsApp-native productivity agent. This document covers the design choices behind it: how a message flows through the system, how the LLM provider is selected, how data stays private, and how we defend against prompt injection.

## Message flow

```
WhatsApp
   │
   ▼
Evolution API ───► POST /webhook (HMAC-verified)
                       │
                       ▼
                  parse_webhook()
                       │
                       ▼
                  arq queue (Redis)
                       │
                       ▼
                  process_message_job
                       │
                       ├── per-group rate limit (Redis sorted set)
                       ├── per-group lock (Redis)
                       ├── L1 regex sanitizer
                       ├── L2 ML guard (llm-guard)
                       │
                       ▼
                  _run_agent()
                       │
                       ▼
                  get_agent()  ── dispatches on LLM_PROVIDER
                       │
                       ├── ClaudeAgent (Anthropic native, 15s timeout)
                       └── FireworksAgent (OpenAI-compatible, 15s timeout)
                              │
                              ▼
                       tool execution
                              │
                              ▼
                       WhatsApp reply (Evolution API)
```

The webhook handler does almost nothing. It verifies the HMAC, parses the payload, and enqueues an arq job. All real work happens in the worker.

## Single-provider LLM agent

One provider is selected at deploy time via the `LLM_PROVIDER` env var. Both implementations share `BaseAgent._execute()` for the tool loop and only differ in their LLM API call.

| | ClaudeAgent | FireworksAgent |
|---|---|---|
| `LLM_PROVIDER` value | `claude` (default) | `fireworks` |
| Model (default) | Anthropic Claude Haiku 4.5 | Qwen3-30B-A3B (Fireworks-hosted, MoE, 3B active) |
| API format | Anthropic native | OpenAI-compatible (chat completions) |
| Auth | `ANTHROPIC_API_KEY` | `Authorization: Bearer ${FIREWORKS_API_KEY}` |
| Timeout | `LLM_TIMEOUT` (15s) | `LLM_TIMEOUT` (15s) |
| Cost (rough) | ~$1/M in, $5/M out | ~$0.20/M in & out |

**No fallback, no circuit breaker.** A provider failure becomes `GENERIC_ERROR_RESPONSE`. The previous two-tier design (local Ollama → Claude with a Redis-backed circuit breaker) was retired in favor of this simpler shape: cheaper hosted open-source models removed the cost case for running a local LLM, and the breaker only existed to manage tier-switching.

**Dispatch** lives in `agent/__init__.py::get_agent()`. The worker calls `get_agent()` once per message; provider selection is fixed for the lifetime of the process.

**Why a timeout at all.** `process_message` holds a per-group Redis lock around the agent call. Without a bounded timeout, a stalled upstream blocks every subsequent message from that group until the lock TTL expires. 15s is enough headroom for hosted 70B+ models while still failing fast.

## Tool pattern

Every tool follows the same four-layer shape:

```
handler.py    Entry point: (session, group_id, member_id, entities) → dict
service.py    Business logic, returns model objects or raises NotFoundError
repository    Data access, encrypts on write, decrypts on read
model         SQLAlchemy ORM
```

`tools/registry.py` maps tool names to handlers and defines the schemas in Anthropic tool format. The agent calls tools through this registry.

### Structured, language-agnostic responses

Handlers return dicts, not English strings. Every dict has a `status` key: `ok`, `empty`, `not_found`, `ambiguous`, `error`, or `list`. The LLM receives JSON tool results and writes the natural-language reply in whatever language the group speaks.

There are no formatters. No string templates. No i18n files. The LLM does it.

### Item identification

Mutation tools (`delete_*`, `update_*`, `cancel_*`) accept two ways to identify an entry:

- `item_number`: 1-indexed position from the most recent `list_*` / `show_*` output. Always unambiguous.
- `description`: substring match, post-decryption, in Python. Returns disambiguation bullets if more than one match.

Handlers branch: `item_number` first, `description` fallback, error if neither.

## Encryption at rest

All user-generated content is encrypted at the application layer with AES-256-GCM before hitting the database. Supabase sees opaque bytes.

**Encrypted columns:**
- `Expense.description`
- `Reminder.message`
- `ItineraryItem.title`, `location`, `notes`
- `Note.content`, `tag`
- `MessageLog.content`
- `Member.display_name`, `wa_id_encrypted`
- `Group.name_encrypted`
- `ChecklistItem.content`, `list_name`

**Repository pattern.** Repos encrypt on write, decrypt on read. Services and handlers always work with plaintext. Text search replaces `ILIKE` with fetch-all + Python substring match (you can't `ILIKE` ciphertext).

**Key helpers** in `core/encryption.py`:
- `encrypt`, `decrypt` (idempotent, safe for SQLAlchemy identity-map reuse)
- `encrypt_nullable`, `decrypt_nullable`
- `set_decrypted` (sets a value without marking the row dirty)
- `validate_key` (run on startup)

The `ENCRYPTION_KEY` is a 32-byte base64 secret. Lose it and the data is gone. There is no recovery path by design.

**Message log retention.** After every message, entries beyond `conversation_context_limit * message_log_retention_multiplier` (default 20 × 2 = 40) are pruned per group. The bot only ever holds a short rolling window of recent messages.

## Security pipeline

Every inbound message passes through two screening layers before reaching the LLM.

**L1: regex sanitizer** (`workers/security/sanitizer.py`)
Patterns for XSS, SQL injection, command injection, and known prompt-injection shapes. Patterns live in `config/injection_patterns.json`, deployed out of band so they can be updated without a code release.

**L2: ML guard** (`workers/security/guard.py`)
`llm-guard` runs heuristic + ML scoring against the message. Above the risk threshold, the message is dropped with a static refusal. No LLM call, no DB write of the content.

Blocked messages are logged via structured logging with operational fields only. The blocked content itself is never persisted.

## Rate limiting and locking

Both per-group, both Redis-backed.

**Rate limit.** Redis sorted set of timestamps per group. Default: 5 messages per 60 seconds. Checked *before* the per-group lock, so rate-limited messages return a static response with zero LLM cost.

**Lock.** Per-group Redis lock around `_run_agent()`. Prevents the same group from racing two messages through the agent at once, which would corrupt the rolling message log context.

## Group approval

`Group.approval_status` is `pending` or `approved`. When `ADMIN_JID` is unset, new groups auto-approve on first message. When `ADMIN_JID` is set, new groups land in `pending` and an admin flips them to `approved` via SQL. Direct (non-group) messages get a static "unauthorized" reply, never reach the LLM.

A one-time onboarding message is sent on the first inbound message from an approved group, then a `welcome_sent` flag stops it from sending again.

## Sentry integration

`main.py` initializes `sentry_sdk` when `SENTRY_DSN` is set. A `before_send` hook scrubs PII before the event is shipped: message text, phone numbers, display names. The error reports we look at in production contain no user content.

## Layer separation

```
db/models/       SQLAlchemy ORM models
db/repositories/ Data access (get_, create_, delete_, find_, get_or_create_)
tools/*/service  Business logic
tools/*/handler  Tool entry points
messaging/       WhatsApp transport (webhook, parser, client)
workers/         arq jobs, message pipeline, security (L1 + L2)
agent/           LLM agent implementations
core/            Cross-cutting: encryption, exceptions
```

Repository functions use domain verbs where it reads better than CRUD: `cancel_reminder`, `snooze_reminder`, `deactivate_member`. Private helpers sit at the top of each file, the public API at the bottom.

## Production topology

Single VPS, Docker Compose, 6 services:

| Service | Role |
|---|---|
| `caddy` | TLS termination, auto-HTTPS, reverse proxy to `app:8000` |
| `app` | FastAPI webhook handler |
| `worker` | arq worker (message processing, agent calls, tool execution) |
| `redis` | Queue, rate limiter, lock, group cache |
| `evolution-api` | WhatsApp gateway (Baileys-based) |
| `evolution-postgres` | Evolution API's own DB |

The LLM is hosted (Anthropic or Fireworks.ai). No local model service runs in the stack.

The application database is **Supabase** (managed Postgres), not the local Compose stack. Connections go through Supavisor in transaction mode (port 6543), which doesn't support prepared statements, so `engine.py` sets `statement_cache_size=0` and `prepared_statement_cache_size=0`.

`./src` is bind-mounted into `app` and `worker`. `alembic/`, `pyproject.toml`, and `uv.lock` are COPYed at build time. Source-only changes need only a container restart; dependency or migration changes need a rebuild.

## Tradeoffs and design choices

**Why structured dicts instead of i18n templates?** The LLM is already in the loop. Asking it to write the user-facing reply in the user's language costs nothing extra and removes hundreds of lines of templating per language.

**Why a single LLM provider instead of two tiers with fallback?** The previous design ran a local Ollama model as the primary path with Claude as fallback, gated by a Redis circuit breaker. Hosted open-source models on Fireworks.ai are now cheap enough (~9× cheaper than Claude Haiku for the Qwen3-30B-A3B baseline) that the operational cost of running and monitoring a local GPU outweighs the per-token savings. One provider, one code path, one set of failure modes — provider choice moves to a single deploy-time env var.

**Why encrypt at the application layer instead of using Supabase's column encryption?** Defense in depth. Even with a leaked DB credential or a Supabase compromise, the data is unreadable without the application's `ENCRYPTION_KEY`. The tradeoff is that text search can't use Postgres indexes; we accept fetch-all + Python substring match for the search volumes a single group produces.

**Why Evolution API instead of WhatsApp Cloud API?** Cloud API requires a registered business phone number and per-message fees. Evolution API runs Baileys against a regular WhatsApp account, which is the right tradeoff for an alpha-stage personal-use product. Migrating to Cloud API would touch only `messaging/whatsapp/`.

**Why arq instead of Celery?** arq is async-native, has a simpler footprint, and integrates cleanly with the FastAPI / SQLAlchemy async stack. Celery would have meant either a sync bridge or a more complex worker.
