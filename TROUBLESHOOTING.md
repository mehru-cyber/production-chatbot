\# Troubleshooting



Real errors hit getting this running from scratch (Windows + Supabase +

Groq), kept here as a record of the debugging rather than in the main

README. If `pip install`, `scripts/init\_postgres.py`, or `uvicorn` fail,

check here first — most of these are already fixed in this repo's current

`requirements.txt`/source, so if you hit one, you may be on an older copy.



| Error | Cause | Fix |

|---|---|---|

| `ModuleNotFoundError: No module named 'app'` running `python scripts/init\_postgres.py` | Python doesn't add the project root to its path when you run a script directly from a subfolder. | Already fixed — `init\_postgres.py` inserts the project root onto `sys.path` itself. If you still see this, confirm you're running the command from the project root, not from inside `scripts/`. |

| `ModuleNotFoundError: No module named 'psycopg2'` | SQLAlchemy defaults to the `psycopg2` driver on a bare `postgresql://` URL, but this project installs `psycopg` (v3) instead. | Already fixed — `app/db/session.py` rewrites the URL to `postgresql+psycopg://` internally. Your `.env` value stays a plain `postgresql://...`. |

| `connection to server at "127.0.0.1", port 5442 failed` | `DATABASE\_URL` in `.env` is still the local Docker value, but nothing's running there (e.g. you're using Supabase/Neon instead, or forgot `docker compose up -d postgres`). | Point `DATABASE\_URL` at wherever your Postgres actually is — see README section 4a. Verify with: `python -c "from app.config import settings; print(settings.database\_url)"` |

| `ImportError: email-validator is not installed` | Missing dependency for `pydantic`'s `EmailStr` used in registration. | `pip install email-validator` (already in `requirements.txt` — re-run `pip install -r requirements.txt` if you're on an older copy). |

| `ImportError: Could not import duckduckgo-search` | Missing dependency for the optional web-search tool. | `pip install duckduckgo-search` (also already in `requirements.txt`). The app skips this tool gracefully if it's missing rather than crashing — if it still crashes your whole app, you're on an older copy of `app/graph/tools.py`. |

| `AttributeError: module 'bcrypt' has no attribute '\_\_about\_\_'` / `password cannot be longer than 72 bytes` | `passlib` 1.7.4 is incompatible with `bcrypt` 4.1+. | `pip install "bcrypt==4.0.1"` (already pinned in `requirements.txt`). |

| `No matching distribution found for faiss-cpu==1.9.0` | That exact version has no wheel for newer Python releases (3.13+). | Already relaxed to `faiss-cpu>=1.9.0` in `requirements.txt`. |

| `OPTIONS /auth/register` repeatedly returns `400` | You opened `frontend/index.html` by double-clicking it. Browsers treat local files as origin `null`, which isn't in the CORS allowlist. | Serve the frontend over HTTP instead: `cd frontend \&\& python -m http.server 5500`, then visit `http://localhost:5500` (already covered by the default `CORS\_ALLOWED\_ORIGINS`). |

| `openai.AuthenticationError: Invalid API Key` / `insufficient\_quota` | `OPENAI\_API\_KEY` is still the `.env.example` placeholder, wrong, or the OpenAI account has no billing set up. | Check with `python -c "from app.config import settings; print(settings.openai\_api\_key\[:8])"`. For a free option with no billing at all, use Groq — see the README's keys table. |

| `This model does not support response format 'json\_schema'` | Some providers (including Groq's Llama models) don't support the newer structured-output mode LangChain defaults to. | Already fixed — `memory\_nodes.py` requests `method="function\_calling"` explicitly, which is broadly supported. |

| `.env` edits don't seem to take effect | Two common causes: (1) uvicorn only reads `.env` at startup — editing it while the server's running does nothing until you restart; (2) Notepad's "Save As" can silently create `.env.txt` instead of overwriting `.env`. | Always restart (`Ctrl+C`, then re-run `uvicorn`) after any `.env` change. Confirm the file is really named `.env` with `dir .env\*`. Sanity-check what's actually loaded: `python -c "from app.config import settings; print(settings.openai\_api\_key\[:8], settings.database\_url.split('@')\[-1])"` |

