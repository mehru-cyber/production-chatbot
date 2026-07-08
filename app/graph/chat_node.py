from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.store.base import BaseStore

from app.config import settings
from app.graph.memory_nodes import read_ltm_text
from app.graph.state import ChatState
from app.graph.tools import get_all_tools

_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, base_url=settings.llm_base_url)
_llm_with_tools = _llm.bind_tools(get_all_tools())

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant with memory and tool access.

Long-term facts about this user:
{ltm}

Summary of earlier conversation (if any):
{summary}

Use tools when the user asks about stock prices, wants to buy stock, or asks
you to search the web or reference documents. Purchases require the user's
explicit approval, which is handled automatically — just call the tool.
Be direct and personalize your answers using the facts above when relevant,
without assuming anything not stated.
"""


def chat_node(state: ChatState, config: RunnableConfig, *, store: BaseStore) -> dict:
    ltm_text = read_ltm_text(config, store=store) or "(none yet)"
    summary = state.get("summary") or "(none yet)"

    system_msg = SystemMessage(
        content=SYSTEM_PROMPT_TEMPLATE.format(ltm=ltm_text, summary=summary)
    )

    response = _llm_with_tools.invoke([system_msg] + state["messages"])
    return {"messages": [response]}
