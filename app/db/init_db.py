from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.store.postgres import PostgresStore

from app.config import settings
from app.db.session import Base, engine
from app.observability.logging_config import get_logger

log = get_logger(__name__)


def init_app_tables() -> None:
    Base.metadata.create_all(bind=engine)
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
