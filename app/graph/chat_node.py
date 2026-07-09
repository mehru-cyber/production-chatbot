import re

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.store.base import BaseStore
from openai import BadRequestError

from app.config import settings
from app.graph.memory_nodes import read_ltm_text
from app.graph.state import ChatState
from app.graph.tools import get_all_tools
from app.observability.logging_config import get_logger

log = get_logger(__name__)

_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, base_url=settings.llm_base_url)
_llm_with_tools = _llm.bind_tools(get_all_tools(), parallel_tool_calls=False)

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

Never write out raw function-call-looking text such as
`<function=...>...</function>` in your reply. If you are unable to use a
tool right now, just say so in plain language instead of narrating a fake
tool call.
"""

_FAKE_TOOL_CALL_RE = re.compile(r"<function=.*?>.*?</function>", re.DOTALL)
_DANGLING_TOOL_CALL_RE = re.compile(r"<function=.*$", re.DOTALL)


def _sanitize_output(text: str) -> str:
    if not text or "<function=" not in text:
        return text
    cleaned = _FAKE_TOOL_CALL_RE.sub("", text)
    cleaned = _DANGLING_TOOL_CALL_RE.sub("", cleaned)
    return cleaned.strip()


def chat_node(state: ChatState, config: RunnableConfig, *, store: BaseStore) -> dict:
    ltm_text = read_ltm_text(config, store=store) or "(none yet)"
    summary = state.get("summary") or "(none yet)"

    system_msg = SystemMessage(
        content=SYSTEM_PROMPT_TEMPLATE.format(ltm=ltm_text, summary=summary)
    )

    messages = [system_msg] + state["messages"]

    try:
        response = _llm_with_tools.invoke(messages)
    except BadRequestError as exc:
        log.warning("tool_call_generation_failed", error=str(exc))
        response = _llm.invoke(messages)
        if isinstance(response, AIMessage):
            response.content = (
                _sanitize_output(response.content or "")
                + "\n\n(Note: I had trouble using a tool just now, so this answer doesn't include live tool data — try rephrasing if you need it.)"
            )
            return {"messages": [response]}

    if isinstance(response, AIMessage) and isinstance(response.content, str):
        response.content = _sanitize_output(response.content)

    return {"messages": [response]}
