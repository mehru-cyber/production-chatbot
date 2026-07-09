from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.store.postgres import PostgresStore
from psycopg_pool import ConnectionPool

from app.config import settings
from app.graph.chat_node import chat_node
from app.graph.memory_nodes import manage_history_node, remember_node
from app.graph.state import ChatState
from app.graph.tools import get_all_tools

# A single long-lived connection pool backs both the checkpointer (STM) and
# the store (LTM) for the lifetime of the app process.
_pool = ConnectionPool(
    conninfo=settings.database_url,
    max_size=10,
    max_idle=300,  # seconds; recycle idle connections well before most providers would
    kwargs={"autocommit": True},
)

_checkpointer = PostgresSaver(_pool)
_store = PostgresStore(_pool)


def build_graph():
    builder = StateGraph(ChatState)

    builder.add_node("remember", remember_node)
    builder.add_node("manage_history", manage_history_node)
    builder.add_node("chat", chat_node)
    builder.add_node("tools", ToolNode(get_all_tools()))

    builder.add_edge(START, "remember")
    builder.add_edge("remember", "manage_history")
    builder.add_edge("manage_history", "chat")
    builder.add_conditional_edges("chat", tools_condition)
    builder.add_edge("tools", "chat")

    return builder.compile(checkpointer=_checkpointer, store=_store)


# Compiled once at import time; FastAPI routes reuse this instance.
chatbot = build_graph()
