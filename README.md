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
| RAG / document search | Stubbed. Wire up your own documents (see section 7).                 |
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
| `OPENAI_API_KEY`         | Yes       | platform.openai.com                                | Powers chat + memory extraction. |
| `DATABASE_URL`           | Yes       | Your Postgres instance                             | e.g. Supabase, Neon, RDS, or local docker-compose. |
| `JWT_SECRET_KEY`         | Yes       | Generate yourself: `openssl rand -hex 32`          | Never reuse across environments. |
| `FINNHUB_API_KEY`        | Recommended | finnhub.io/register (free tier)                  | Real stock prices. Without it, `get_stock_price` returns a clear "not configured" error instead of failing silently. |
| `ALPACA_API_KEY_ID`      | Optional  | alpaca.markets (free paper trading account)        | Enables real (paper) trade execution. Without it, `purchase_stock` returns a clearly labeled simulated response. |
| `ALPACA_API_SECRET_KEY`  | Optional  | same as above                                      | |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Optional | cloud.langfuse.com (free tier) | Tracing/observability. App runs fine without it. |

Copy `.env.example` to `.env` and fill these in. Never commit `.env`.

---

## 4. Local setup

```bash
cp .env.example .env        # fill in your keys
docker compose up -d postgres
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_postgres.py     # creates app tables + langgraph checkpoint/store tables
uvicorn app.main:app --reload
```

Open `frontend/index.html` in a browser (or serve it — see section 6),
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

## 5. Human-in-the-loop flow

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

## 6. Deploying it

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

## 7. Wiring up real RAG documents

`app/graph/tools.py::rag_search` is a stub that returns a "not configured"
message. To make it real:

1. Put your source documents in a `documents/` folder.
2. Write an ingestion script (chunk with `RecursiveCharacterTextSplitter`,
   embed with `OpenAIEmbeddings`, store in FAISS or pgvector).
3. Point `rag_search` at the resulting retriever.

This is intentionally left out of the base repo since "what documents" is
specific to your use case.

---

## 8. Known limitations (read before calling this "done")

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

## 9. If you ever want real (non-paper) trading

Do not wire a live brokerage API into `purchase_stock` without first
talking to a securities lawyer in your jurisdiction. At minimum you are
likely looking at: a licensed broker-dealer relationship (you almost
certainly cannot legally hold client funds or place real trades on
someone's behalf without one), KYC/AML procedures, and audited financial
controls. The paper-trading integration in this repo exists specifically
so you can build and demo the *mechanism* (HITL approval, order flow,
confirmation UI) without touching any of that.
