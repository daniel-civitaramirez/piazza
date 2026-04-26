# Piazza

A WhatsApp group productivity agent. Track expenses, set reminders, plan trips, save notes, run shared checklists, all by chatting naturally in your group.

No app to install. No accounts to create. The bot lives in WhatsApp where the group already is.

<!-- TODO: add demo.gif -->

## What it does

Add the bot to a WhatsApp group and talk to it like a person:

- **Expenses** — `Alice paid 80 for dinner, split with Bob and Charlie` → tracks the debt, computes balances, handles settlements.
- **Reminders** — `remind us to leave at 9am tomorrow` or `every Monday at 8`. Recurring reminders use RRULE under the hood.
- **Itinerary** — `add Louvre at 2pm Friday` → group trip plan, ordered by time.
- **Notes** — `save the wifi password is hunter2` → searchable later by content or tag.
- **Checklists** — `add milk to the shopping list` → check items off as you go.
- **Group search** — find anything anyone has saved across all of the above.

Everything is in the user's language. The agent generates responses in whatever language the group speaks.

## How it's built

- **Two-tier LLM agent.** A local Ollama model (Qwen 3.5 4B) handles the easy 80%; Claude Haiku takes the rest as fallback. A circuit breaker trips Ollama out for 10 minutes after 3 failures in 2 minutes.
- **Tool-using agent, not a classifier.** Both tiers run a real tool loop and call 25 typed tools across 6 domains.
- **Encryption at rest.** All user content (messages, expenses, notes, reminders, names) is encrypted with AES-256-GCM at the application layer before hitting Postgres. Supabase sees opaque bytes.
- **Two-layer prompt-injection defense.** L1 regex sanitizer for known attack shapes, L2 ML screening via `llm-guard`.
- **Per-group rate limit and lock.** Redis-backed. Rate-limited messages return a static reply with zero LLM cost.

[Architecture deep-dive →](ARCHITECTURE.md)

## Stack

| Layer | Choice |
|------|------|
| API | FastAPI + uvicorn |
| Queue | arq (Redis-backed) |
| DB | Postgres (Supabase) via SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic |
| LLM | Ollama (Qwen 3.5 4B) → Anthropic Claude Haiku 4.5 |
| Security | `llm-guard`, AES-256-GCM, HMAC webhook verification |
| WhatsApp | Evolution API (Baileys-based) |
| Hosting | Single VPS, Docker Compose, Caddy auto-TLS |
| Errors | Sentry with PII-scrubbing `before_send` |

## Quickstart (local dev)

```bash
# 1. Install uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 2. Clone + install deps
git clone https://github.com/<you>/piazza.git
cd piazza
uv sync --extra dev

# 3. Start Redis and Ollama
docker compose up -d

# 4. Configure
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, ENCRYPTION_KEY (32-byte base64), SUPABASE_DB_URL

# 5. Migrate
uv run alembic upgrade head

# 6. Test
uv run pytest src/ -v
```

For a production deploy (Caddy + Evolution API + worker), see [CONTRIBUTING.md](CONTRIBUTING.md#production-deploy).

## Project layout

```
src/piazza/
  agent/         LLM agents (Ollama + Claude), shared tool loop
  config/        Settings, constants
  core/          Encryption, exceptions
  db/            SQLAlchemy models, repositories
  messaging/     WhatsApp transport (webhook, parser, client)
  tools/         Business logic, one folder per domain
    expenses/  reminders/  itinerary/  notes/  checklist/  search/  status/
    registry.py    Tool schemas + dispatch
  workers/       arq jobs, message processing pipeline, security (L1+L2)
  main.py        FastAPI entrypoint
alembic/         Migrations
```

Tests are co-located as `*_test.py` next to source. Total: ~12.7k LOC.

## Status

Alpha. Running in a single production deployment. Not yet packaged for multi-tenant use.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Source-available, free for non-commercial use (learning, evaluation, personal projects). Commercial use requires written permission from the author.

For commercial licensing, contact: dani.civitaramirez@gmail.com
