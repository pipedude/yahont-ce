# PROJECT KNOWLEDGE BASE

This file provides guidance to AI agents when working with code in this repository.

## KEY NOTES

- Reply to the user in the language the user writes in. If the user writes Russian, reply in Russian.
- Write code comments and docstrings in English. See `CONTRIBUTING.md`.
- Python deps live in a `uv`-managed virtualenv at `.venv` (repo root). If it doesn't exist yet, create it
  with `uv sync --frozen`, then `source .venv/bin/activate`.
- Test secrets (API keys etc.) are resolved by `backend/tests/utils/aws_secrets.py`, in order: process
  env vars → a gitignored `.vscode/.env` file with `KEY=value` lines (create it yourself) → AWS Secrets
  Manager (requires `aws sso login`, not available to most contributors). Tests declare what they need via
  `@pytest.mark.secrets(TestSecret.X)`. If a key you need still can't be resolved, ask the user rather than
  skipping tests.
- If using `playwright` to explore the frontend, log in with username `admin_user@example.com` and password
  `TestPassword123!` (the admin user created by the playwright global setup — see
  `web/tests/e2e/constants.ts`). If it doesn't exist yet, register it via the signup page; the first user
  registered automatically becomes admin. The app can be accessed at `http://localhost:3000`.
- Yahont CE runs in Docker. From `deployment/docker_compose` run `cp env.template .env` once and set
  `USER_AUTH_SECRET` in `.env` (for example `openssl rand -hex 32`; the API server does not start without
  it), then `docker compose up -d --build`. Always use `--build`: without it Docker pulls the published
  `yahontai/*` images instead of building this code. Run `docker compose ps` to check that the services are
  up. After you change backend or web code, run `docker compose up -d --build` again. See `README.md`.
- Service logs: run `docker compose logs <service>` from `deployment/docker_compose`. Services:
  `api_server`, `background`, `web_server`, `inference_model_server`, `indexing_model_server`,
  `relational_db`, `opensearch`, `nginx`, `cache`.
- The compose file does not publish the database ports. To connect to the Postgres database, run from
  `deployment/docker_compose`: `docker compose exec relational_db psql -U postgres -c "<SQL>"`
  (no `-it` — agent shells have no TTY).
- When making calls to the backend, always go through the frontend. E.g. make a call to `http://localhost:3000/api/persona` not `http://localhost:8080/api/persona`
- If `.agents-local.md` exists at the repo root and its rules are not already in your context,
  read and follow it. It carries developer-local agent guidance and is never committed.

## Project Overview

**Yahont CE** is the open Community Edition of Yahont, a Gen-AI and Enterprise Search platform that connects
to company documents, apps, and people. Yahont is a fork of **Onyx** (formerly Danswer). The code outside the
`ee` folders is MIT licensed.

Enterprise Edition code is not part of Yahont CE:

- `backend/ee` holds only an empty `__init__.py`. Features that need it are not available.
- `web/src/ee` and `web/src/app/ee` are unmodified copies from Onyx under the Onyx Enterprise License.
  Do not edit them: every release replaces them with the Onyx version.

### Technology Stack

- **Backend**: Python 3.13, FastAPI, SQLAlchemy, Alembic, Celery
- **Frontend**: Next.js 16, React 19, TypeScript, Tailwind CSS
- **Database**: PostgreSQL with Redis caching
- **Search**: OpenSearch-backed keyword and vector document index
- **Auth**: OAuth2, multi-provider support (SAML and SCIM are Enterprise Edition features)
- **AI/ML**: LangChain, LiteLLM, multiple embedding models

### Repository Layout & Sub-project Guides

Each sub-project has its own agents file with the standards for that area — read it before working
there:

- `backend/` — FastAPI app + Celery workers. `onyx/` is the Community Edition core, `ee/` is empty in
  Yahont CE, `alembic/` holds migrations, `tests/` the test suites. Standards (Celery, migrations,
  testing, error handling, LLM tracing): `backend/AGENTS.md`.
- `web/` — Next.js frontend. Standards: `web/AGENTS.md`.

`backend/AGENTS.md` and `web/AGENTS.md` come from Onyx. They mention things that Yahont CE does not
contain (`mobile/`, `desktop/`, `make`, `pre-commit`, the `.vscode` launch setup). Ignore those parts.

Explore the tree with `ls` rather than relying on docs for the full package list.

### Feature Map

`.agents/feature-map/` maps the product: every surface, what it does, the code behind
it, and how the parts connect. Use it before you change a product surface, when you
review a diff or PR, and when you need to know what a feature does or what a change
can break. The `feature-map` skill (`.agents/skills/feature-map/SKILL.md`) gives the
procedure.

- Look up a code path in `.agents/feature-map/PATHS.md` to find its component.
- The step-by-step review procedure is `.agents/feature-map/VERIFYING.md`.
- Onyx overloads words such as Persona, Tool, turn, and SearchDoc. Read
  `.agents/feature-map/GLOSSARY.md` before trusting a name.

If you change behaviour a component document describes, update that document in the
same pull request. Yahont CE has no pre-commit hook that checks this: keep the files
and paths the map cites valid by hand.

### Skills

Shared agent skills live in `.agents/skills/`. `.claude/skills`, `.cursor/skills` and
`.codex/skills` are symlinks to it, so add or edit skills only in `.agents/skills/`.

## Code Quality

Yahont CE has no `pre-commit` configuration. Run the checks by hand, as in `CONTRIBUTING.md`:

```bash
# Backend, from the repo root
uv run ruff check backend
uv run ruff format --check backend
uv run ty check

# Frontend, from web/
bun run format:check
bun run lint
bun run types:check
```

Claude Code and Codex run `.agents/hooks/pre_commit_on_stop.py` when you end a turn
(wired as `UserPromptSubmit` and `Stop` hooks in `.claude/settings.json` and
`.codex/hooks.json`). Without a `pre-commit` configuration the hook skips `pre-commit`.
It still names any feature-map component whose code the turn changed but whose document
the branch did not. Update the document if your change alters what it states. Codex runs
the hooks only after you trust the project `.codex/` layer.

NOTE: Always make sure everything is strictly typed (both in Python and Typescript).

NOTE: Keep code comments brief and focused on information that stays relevant long-term.

## Writing

These rules apply to all prose you write: docs, commit messages, PR descriptions, reports, and replies.

Follow ASD-STE100 Simplified Technical English for technical text:

- Use approved words only. Each word has one meaning.
- Use one word for one idea. Do not use two words for the same thing.
- Write short sentences. Use 20 words or less for instructions.
- Use active voice. Write "Turn the switch", not "The switch must be turned".
- Write short paragraphs. Keep one topic in each paragraph.
- Keep code comments focused on information that is relevant long-term or for future readers.

## Testing

There are 4 main types of tests: unit, external dependency unit, integration, and playwright e2e
(`web/tests/e2e`). Commands and guidance for all four live in `backend/AGENTS.md`; shared fixtures
and deeper detail in `backend/tests/README.md`. Prefer integration tests over the other types.

Unit tests need no running services. Run them from `backend/`:

```bash
cd backend
uv run pytest tests/unit
```

Frontend tests: `bun run test` in `web/`.

## Security Considerations

- Never commit API keys or secrets to the repository
- Use the encrypted credential storage for connector credentials
- Follow existing RBAC patterns for new features

## Creating a Plan

When creating a plan in the `plans` directory (gitignored — create it if it doesn't exist), make sure to
include at least these elements:

**Issues to Address**
What the change is meant to do.

**Important Notes**
Things you come across in your research that are important to the implementation.

**Implementation strategy**
How you are going to make the changes happen. High level approach.

**Tests**
What unit (use rarely), external dependency unit, integration, and playwright tests you plan to write to
verify the correct behavior. Don't overtest. Usually, a given change only needs one type of test.

Do NOT include these: _Timeline_, _Rollback plan_

This is a minimal list - feel free to include more. Do NOT write code as part of your plan.
Keep it high level. You can reference certain files or functions though.

Before writing your plan, make sure to do research. Explore the relevant sections in the codebase.

## Reuse Existing Standards

Before you add a helper, utility, pattern or convention, search the codebase for one that does
the same job, and use it. For example, use the existing rate limiting, caching, URL validation,
router and settings patterns. Do not invent a parallel mechanism. If the existing one does not
do enough, extend it so other callers get the change too. A new pattern needs a reason that the
existing ones cannot meet.

## Best Practices

In addition to the other content in this file, best practices for contributing
to the codebase can be found in the "Engineering Best Practices" section of
`CONTRIBUTING.md` (written in Russian). Understand its contents and follow them.
