from sqlalchemy import text

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

from app.config import settings
from app.db.session import Base, engine
from app.observability.logging_config import get_logger

log = get_logger(__name__)

# Postgres supports `ADD COLUMN IF NOT EXISTS`, making this safe to re-run —
# needed because `create_all()` only creates missing *tables*, it never
# alters columns on a table that already exists (e.g. your live `users`
# table from before these security columns were added).
_USER_COLUMN_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR NULL",
]


def init_app_tables() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for statement in _USER_COLUMN_MIGRATIONS:
            conn.execute(text(statement))
    log.info("app_tables_ready")


def init_langgraph_tables() -> None:
    # PostgresSaver = short-term memory (checkpoints), PostgresStore = long-term memory
    with PostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        checkpointer.setup()
    with PostgresStore.from_conn_string(settings.database_url) as store:
        store.setup()
    log.info("langgraph_tables_ready")


def init_all() -> None:
    init_app_tables()
    init_langgraph_tables()
