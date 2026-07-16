from sqlalchemy import text

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

from app.config import settings
from app.db.session import Base, engine
from app.observability.logging_config import get_logger

log = get_logger(__name__)

_USER_COLUMN_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP NULL",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR NULL",
    "ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS title VARCHAR NULL",
    "ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE chat_threads ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW()",
]


def init_app_tables() -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for statement in _USER_COLUMN_MIGRATIONS:
            conn.execute(text(statement))
    log.info("app_tables_ready")


def init_langgraph_tables() -> None:
    with PostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        checkpointer.setup()
    with PostgresStore.from_conn_string(settings.database_url) as store:
        store.setup()
    log.info("langgraph_tables_ready")


def init_all() -> None:
    init_app_tables()
    init_langgraph_tables()
