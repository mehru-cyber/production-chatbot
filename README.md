# Production LangGraph Chatbot

A LangGraph chatbot with short-term memory (Postgres checkpoints), long-term
memory (Postgres semantic store), tool calling, a human-in-the-loop approval
gate for trades, authentication, rate limiting, cost caps, and basic
observability — built to actually be deployed, not just demoed.

---

## 1. What's real vs simulated

Be upfront with your users about this table. Nothing here lies about its
own capabilities.

| Feature              | Status in this repo                                                  |
|-----------------------|----------------------------------------------------------------------|
| Chat + memory         | Real. Postgres-backed STM + LTM, survives restarts.                 |
| Stock price lookup    | Real. Uses Finnhub's free tier (60 req/min) with a 30s cache.        |
| Stock purchase        | **Paper trading only**, via Alpaca's free paper API. No real money.  |
| Human approval (HITL) | Real. Graph genuinely pauses via `interrupt()` until you respond.    |
| Auth                  | Real. JWT-based, passwords hashed with bcrypt.                       |
| Rate limiting         | Real, but in-memory — resets on restart, not shared across instances.|
| Cost caps             | Real. Daily per-user token cap enforced in Postgres.                 |
| RAG / document search | Stubbed. Wire up your own documents (see section 8).                 |
| Live brokerage trading| **Not implemented.** See section 9 before you even consider this.    |

If you want real (non-paper) trading, that is a regulatory undertaking
(broker-dealer relationships, KYC/AML, securities law) far outside what any
codebase can solve for you. This repo deliberately stops at paper trading.

---

## 2. Architecture

```
frontend/            static HTML/JS chat client (swap for React/Streamlit/etc. later)
app/
  main.py            FastAPI app, middleware wiring, startup hooks
  config.py          all environment variables, one place
  auth/               registration, login, JWT issuing/verification
  db/                 SQLAlchemy engine + app tables (users, usage_log)
  graph/              the LangGraph chatbot itself
    state.py          ChatState schema
    memory_nodes.py   remember_node (LTM write), manage_history_node (STM trim/summarize)
    chat_node.py      main LLM + tools node
    tools.py          get_stock_price, purchase_stock, web_search, rag_search
    cache.py          TTL cache for the stock price tool
    graph.py          builds and compiles the graph with Postgres checkpointer + store
  middleware/         rate limiting, per-user daily cost cap
  observability/      structured logging setup
  routes/             /auth, /chat, /health HTTP endpoints
scripts/
  init_postgres.py    one-time DB setup (run once per environment)
tests/                starter tests
```

---

## 3. API keys and accounts you need

| Variable                | Required? | Where to get it                                  | Notes |
|--------------------------|-----------|---------------------------------------------------|-------|
| `OPENAI_API_KEY`         | Yes       | platform.openai.com                                | Powers chat + memory extraction. Requires billing set up (even $5 unlocks usage). |
| `LLM_BASE_URL` / `CHAT_MODEL` | Optional | —                                             | Leave unset to use OpenAI directly. **For a free alternative with no billing required**, use [Groq](https://console.groq.com) instead: put your Groq key in `OPENAI_API_KEY`, set `LLM_BASE_URL=https://api.groq.com/openai/v1` and `CHAT_MODEL=llama-3.3-70b-versatile`. Any OpenAI-API-compatible provider works the same way. |
| `DATABASE_URL`           | Yes       | Your Postgres instance                             | Value depends on how you run the app — see section 4a below. |
| `JWT_SECRET_KEY`         | Yes       | Generate yourself: `openssl rand -hex 32`          | Never reuse across environments. |
| `FINNHUB_API_KEY`        | Recommended | finnhub.io/register (free tier)                  | Real stock prices. Without it, `get_stock_price` returns a clear "not configured" error instead of failing silently. |
| `ALPACA_API_KEY_ID`      | Optional  | alpaca.markets (free paper trading account)        | Enables real (paper) trade execution. Without it, `purchase_stock` returns a clearly labeled simulated response. |
| `ALPACA_API_SECRET_KEY`  | Optional  | same as above                                      | |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Optional | cloud.langfuse.com (free tier) | Tracing/observability. App runs fine without it. |

Copy `.env.example` to `.env` and fill these in. Never commit `.env`.

---

## 4. Local setup

**macOS/Linux:**
```bash
cp .env.example .env        # fill in your keys
docker compose up -d postgres
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_postgres.py     # creates app tables + langgraph checkpoint/store tables
uvicorn app.main:app --reload
```

**Windows (cmd):**
```cmd
copy .env.example .env
docker compose up -d postgres
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts\init_postgres.py
uvicorn app.main:app --reload
```

If you're not running the local Docker Postgres (e.g. you're using a managed
provider like Supabase instead), skip the `docker compose up -d postgres`
line entirely — just make sure `DATABASE_URL` in `.env` points at your real
database first.

### 4a. Which `DATABASE_URL` to use

This trips people up, so to be explicit — there are two different correct
values depending on how the app itself is running:

| How you run the app                                              | `DATABASE_URL` should be                                          |
|--------------------------------------------------------------------|---------------------------------------------------------------------|
| `uvicorn app.main:app --reload` directly on your machine, Postgres in Docker (the commands above) | `postgresql://postgres:postgres@localhost:5442/postgres` — reaches Postgres through the port Docker mapped to your host. This is the default in `.env.example`. |
| `docker compose up` (the whole stack, app included, as containers)  | `postgresql://postgres:postgres@postgres:5432/postgres` — inside a container, `localhost` means *that container*, not the Postgres one. Containers reach each other by service name (`postgres`) on the internal port (`5432`), not the host-mapped one (`5442`). |

You don't have to remember this yourself: `docker-compose.yml` already
overrides `DATABASE_URL` for the `app` service to the correct internal
value, so `.env`'s value only matters when you're running `uvicorn`
yourself. If you deploy to a managed Postgres (Supabase/Neon/RDS), use
whatever connection string that provider gives you instead of either of
the above.

Open `frontend/index.html` in a browser (or serve it over HTTP to avoid CORS issues — see the troubleshooting table above),
register a user, log in, and start chatting.

Quick smoke test without a browser:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"a-real-password"}'

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=you@example.com&password=a-real-password" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"What is the price of AAPL?","thread_id":"demo-1"}'
```

---

## 5. Troubleshooting — errors you may hit on first setup

These are real issues encountered getting this running from scratch. If
`pip install`, `init_postgres.py`, or `uvicorn` fail, check here first.

| Error | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` running `python scripts/init_postgres.py` | Python doesn't add the project root to its path when you run a script directly from a subfolder. | Already fixed in this repo — `init_postgres.py` inserts the project root onto `sys.path` itself. If you still see this, confirm you're running the command from the project root, not from inside `scripts/`. |
| `ModuleNotFoundError: No module named 'psycopg2'` | SQLAlchemy defaults to the `psycopg2` driver on a bare `postgresql://` URL, but this project installs `psycopg` (v3) instead. | Already fixed — `app/db/session.py` rewrites the URL to `postgresql+psycopg://` internally. Your `.env` value stays a plain `postgresql://...`. |
| `connection to server at "127.0.0.1", port 5442 failed` | `DATABASE_URL` in `.env` is still the local Docker value, but nothing's running there (e.g. you're using Supabase/Neon instead, or forgot `docker compose up -d postgres`). | Point `DATABASE_URL` at wherever your Postgres actually is. See section 4a. Verify with: `python -c "from app.config import settings; print(settings.database_url)"` |
| `ImportError: email-validator is not installed` | Missing dependency for `pydantic`'s `EmailStr` used in registration. | `pip install email-validator` (already added to `requirements.txt` — re-run `pip install -r requirements.txt` if you're on an older copy). |
| `ImportError: Could not import duckduckgo-search` | Missing dependency for the optional web-search tool. | `pip install duckduckgo-search` (also already in `requirements.txt`). The app is designed to skip this tool gracefully if it's missing rather than crash — if it still crashes your whole app, you're on an older copy of `app/graph/tools.py`. |
| `AttributeError: module 'bcrypt' has no attribute '__about__'` / `password cannot be longer than 72 bytes` | `passlib` 1.7.4 is incompatible with `bcrypt` 4.1+. | `pip install "bcrypt==4.0.1"` (already pinned in `requirements.txt`). |
| `No matching distribution found for faiss-cpu==1.9.0` | That exact version has no wheel for newer Python releases (3.13+). | Already relaxed to `faiss-cpu>=1.9.0` in `requirements.txt`. |
| `OPTIONS /auth/register` repeatedly returns `400` | You opened `frontend/index.html` by double-clicking it. Browsers treat local files as origin `null`, which isn't in the CORS allowlist. | Serve the frontend over HTTP instead: `cd frontend && python -m http.server 5500`, then visit `http://localhost:5500` (already covered by the default `CORS_ALLOWED_ORIGINS`). |
| `openai.AuthenticationError: Invalid API Key` / `insufficient_quota` | `OPENAI_API_KEY` is still the `.env.example` placeholder, wrong, or the OpenAI account has no billing set up. | Double-check with `python -c "from app.config import settings; print(settings.openai_api_key[:8])"`. For a free option with no billing at all, use Groq — see the keys table above. |
| `This model does not support response format 'json_schema'` | Some providers (including Groq's Llama models) don't support the newer structured-output mode LangChain defaults to. | Already fixed — `memory_nodes.py` requests `method="function_calling"` explicitly, which is broadly supported. |
| **`.env` edits don't seem to take effect** | Two common causes: (1) uvicorn only reads `.env` at startup — editing it while the server's running does nothing until you restart; (2) Notepad's "Save As" can silently create `.env.txt` instead of overwriting `.env`. | Always restart (`Ctrl+C`, then re-run `uvicorn`) after any `.env` change. Confirm the file is really named `.env` with `dir .env*`. To sanity-check what the app is actually reading: `python -c "from app.config import settings; print(settings.openai_api_key[:8], settings.database_url.split('@')[-1])"` |

---

## 6. Human-in-the-loop flow

`purchase_stock` calls `interrupt()`. When that happens, `/chat` returns:

```json
{"status": "pending_approval", "prompt": "Approve buying 5 shares of AAPL? (yes/no)", "thread_id": "demo-1"}
```

The client then calls:

```bash
curl -X POST http://localhost:8000/chat/resume \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"thread_id":"demo-1","decision":"yes"}'
```

and gets the final assistant message back. The frontend's chat UI wires
this into a yes/no prompt automatically.

---

## 7. Deploying it

**Database**: use a managed Postgres (Supabase, Neon, or RDS) instead of the
docker-compose container. Enable automatic backups and point-in-time
recovery — you are storing user accounts and personal memory data.

**App server**: containerize with the included `Dockerfile` and run it on
any container platform (Fly.io, Render, ECS, Cloud Run). Put it behind
HTTPS — either the platform's built-in TLS or a reverse proxy (Caddy
handles Let's Encrypt automatically with about 3 lines of config).

**Environment variables**: set them in your platform's secrets manager, not
in a checked-in `.env`.

**Scaling beyond one instance**: the in-memory rate limiter and cost guard
in this repo are per-process. If you run more than one instance behind a
load balancer, replace `app/middleware/rate_limit.py`'s in-memory store
with Redis (the interface is small — swap the dict for `redis-py` calls).

**Observability**: set the `LANGFUSE_*` env vars to get full tracing of
every graph run — which node ran, what the LLM was prompted with, tool
call latency, and interrupt/approval rates. Without them, you still get
structured JSON logs to stdout, which is enough for basic debugging.

---

## 8. Wiring up real RAG documents

`app/graph/tools.py::rag_search` is a stub that returns a "not configured"
message. To make it real:

1. Put your source documents in a `documents/` folder.
2. Write an ingestion script (chunk with `RecursiveCharacterTextSplitter`,
   embed with `OpenAIEmbeddings`, store in FAISS or pgvector).
3. Point `rag_search` at the resulting retriever.

This is intentionally left out of the base repo since "what documents" is
specific to your use case.

---

## 9. Known limitations (read before calling this "done")

- **Rate limiting and cost caps are single-instance.** Fine for one server;
  needs Redis for a real multi-instance deployment.
- **No email verification or password reset flow.** Registration is
  immediate; add these before real public signup.
- **No refresh tokens.** JWTs are short-lived (30 min default) with no
  silent renewal — users will need to log in again after expiry. Add a
  refresh-token flow if that's too disruptive for your UX.
- **RAG is a stub**, not populated with any documents.
- **The in-memory rate limiter resets on every restart/deploy.**
- **`remember_node` writes memory without human review.** A bad extraction
  becomes durable. Consider surfacing "here's what I'm remembering about
  you" in the UI with an undo option.
- **No abuse/content moderation layer.** Consider adding OpenAI's
  moderation endpoint in front of the chat node if this goes public.

---

## 10. If you ever want real (non-paper) trading

Do not wire a live brokerage API into `purchase_stock` without first
talking to a securities lawyer in your jurisdiction. At minimum you are
likely looking at: a licensed broker-dealer relationship (you almost
certainly cannot legally hold client funds or place real trades on
someone's behalf without one), KYC/AML procedures, and audited financial
controls. The paper-trading integration in this repo exists specifically
so you can build and demo the *mechanism* (HITL approval, order flow,
confirmation UI) without touching any of that.
