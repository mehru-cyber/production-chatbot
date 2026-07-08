\# Troubleshooting



Real errors hit getting this running from scratch (Windows + Supabase +

Groq), kept here as a record of the debugging rather than in the main

README. 




| Error | Cause | Fix |

|---|---|---|

| `connection to server at "127.0.0.1", port 5442 failed` | `DATABASE\_URL` in `.env` is still the local Docker value, but nothing's running there (e.g. you're using Supabase/Neon instead, or forgot `docker compose up -d postgres`). | Point `DATABASE\_URL` at wherever your Postgres actually is — see README section 4a. Verify with: `python -c "from app.config import settings; print(settings.database\_url)"` |

| `AttributeError: module 'bcrypt' has no attribute '\_\_about\_\_'` / `password cannot be longer than 72 bytes` | `passlib` 1.7.4 is incompatible with `bcrypt` 4.1+. | `pip install "bcrypt==4.0.1"` (already pinned in `requirements.txt`). |

| `No matching distribution found for faiss-cpu==1.9.0` | That exact version has no wheel for newer Python releases (3.13+). | Already relaxed to `faiss-cpu>=1.9.0` in `requirements.txt`. |

| `This model does not support response format 'json\_schema'` | Some providers (including Groq's Llama models) don't support the newer structured-output mode LangChain defaults to. | Already fixed — `memory\_nodes.py` requests `method="function\_calling"` explicitly, which is broadly supported. |



