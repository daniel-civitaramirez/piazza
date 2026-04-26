# Contributing

## License notice

Piazza is released under [PolyForm Noncommercial 1.0.0](LICENSE). Contributions are welcome for non-commercial use. By submitting a PR you agree your contribution is licensed under the same terms. For commercial use or relicensing, contact the author.

## Local setup

Prerequisites: Python 3.12, Docker, [`uv`](https://github.com/astral-sh/uv).

```bash
export PATH="$HOME/.local/bin:$PATH"

git clone https://github.com/<you>/piazza.git
cd piazza
uv sync --extra dev

cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, ENCRYPTION_KEY, SUPABASE_DB_URL,
#         WEBHOOK_SECRET, EVO_API_KEY, EVO_DB_PASSWORD,
#         EVO_INSTANCE_NAME, BOT_JID, DOMAIN

docker compose up -d              # Redis + Ollama
uv run alembic upgrade head       # ENCRYPTION_KEY must be set
```

Generate an `ENCRYPTION_KEY`:

```bash
python -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

## Running tests

```bash
uv run pytest src/ -v                                          # all tests
uv run pytest src/piazza/tools/expenses/handler_test.py -v     # one file
uv run pytest src/ -k "test_name" -v                           # by name
uv run pytest src/ --cov=src/piazza                            # with coverage
```

Tests run against in-memory SQLite (`db_session` fixture) and `fakeredis`. No external services required.

## Lint and type check

```bash
uv run ruff check src/
uv run mypy src/piazza/
```

Ruff line-length is 100, target Python 3.12.

## Adding a tool

A tool is one folder under `src/piazza/tools/<name>/` with `handler.py`, `service.py`, plus co-located `*_test.py` files. The full pattern:

1. **Model** in `db/models/`. Any user-content column must be `LargeBinary` (encrypted at rest).
2. **Repository** in `db/repositories/`. Encrypt on write, decrypt on read using helpers from `core/encryption.py`. Repos always accept and return plaintext.
3. **Service** in `tools/<name>/service.py`. Business logic. Raises `NotFoundError(entity, number=, query=)` for missing items.
4. **Handler** in `tools/<name>/handler.py`. Signature `(session, group_id, member_id, entities) → dict`. Catches `NotFoundError`, builds a structured response dict using helpers from `tools/responses.py`. Every dict has a `status` key.
5. **Registry**. Register the handler and define the Anthropic-format tool schema in `tools/registry.py`. Add any new input fields to the `Entities` model in `tools/schemas.py`.
6. **Migration**. `uv run alembic revision --autogenerate -m "..."`. Encrypted columns require a data migration that reads plaintext, encrypts, writes back.

## Logging rules

Operational fields only: event name, counts, durations, action types, `group_id` (UUID).
Never log: JIDs, phone numbers, display names, message content, user-generated text.

## Production deploy

Production runs on a single VPS via `docker-compose.prod.yml`. Caddy handles TLS and reverse-proxies to `app:8000`.

Match the procedure to the change:

**Source-only change (no schema, no deps).** No rebuild.

```bash
git pull origin main
docker compose -f docker-compose.prod.yml restart app worker
```

**Dependency change (`pyproject.toml` / `uv.lock`).** Rebuild required.

```bash
git pull origin main
docker compose -f docker-compose.prod.yml build app worker
docker compose -f docker-compose.prod.yml up -d app worker
```

**DB migration.** Rebuild, then migrate *before* swapping containers (zero-downtime).

```bash
git pull origin main
docker compose -f docker-compose.prod.yml build app worker
docker compose -f docker-compose.prod.yml run --rm app uv run alembic upgrade head
docker compose -f docker-compose.prod.yml up -d app worker
```

**`.env` change.** Recreate, don't restart.

```bash
docker compose -f docker-compose.prod.yml up -d app worker
```

**Things to never do:**

- Don't `docker compose down`. It stops Caddy and Evolution API and breaks the WhatsApp session (requires QR re-link).
- Don't run alembic against a host-installed Python. Always go through the container.
- Don't override `SUPABASE_DB_URL` to the session-mode endpoint. Supavisor transaction mode (port 6543) is required, and `alembic/env.py` sets the correct flags.

After any deploy, smoke test:

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs app worker --tail 50
curl -fsS https://<DOMAIN>/health | jq
```

`GET /health` reports per-service status (DB, Redis, Ollama, Evolution API, WhatsApp auth). WhatsApp `not authenticated` is expected until the Evolution API instance is linked via QR.

## Conventions

- `*_test.py` co-located with source.
- All tests async (`pytest-asyncio` with `asyncio_mode="auto"`).
- Private helpers at top of file, public API at bottom.
- Repository function names use domain verbs where they read better than CRUD: `cancel_reminder`, `snooze_reminder`, `deactivate_member`.
- Handler dicts always have a `status` key; use builders from `tools/responses.py`.
