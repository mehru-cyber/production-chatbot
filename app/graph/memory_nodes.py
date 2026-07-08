import uuid
from typing import List

from langchain_core.messages import RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.state import ChatState

_extractor_llm = ChatOpenAI(
    model=settings.chat_model, temperature=0, api_key=settings.openai_api_key, base_url=settings.llm_base_url
)


class MemoryItem(BaseModel):
    text: str = Field(description="A short, atomic, stable fact about the user")
    is_new: bool = Field(description="True if this adds new info vs. existing memory")


class MemoryDecision(BaseModel):
    should_write: bool
    memories: List[MemoryItem] = Field(default_factory=list)


_memory_extractor = _extractor_llm.with_structured_output(MemoryDecision, method="function_calling")

MEMORY_PROMPT = """You maintain accurate long-term memory about a user.

EXISTING MEMORY:
{existing}

TASK:
- Extract only stable, long-term-worthy facts from the user's latest message
  (identity, durable preferences, ongoing projects/goals).
- Do not store one-off requests, small talk, or anything already covered by
  EXISTING MEMORY (mark those is_new=false).
- No speculation. Only facts the user actually stated.
- If nothing is memory-worthy, return should_write=false with an empty list.
"""


def remember_node(state: ChatState, config: RunnableConfig, *, store: BaseStore) -> dict:
    user_id = config["configurable"]["user_id"]
    ns = ("user", user_id, "details")

    existing_items = store.search(ns)
    existing_text = (
        "\n".join(it.value.get("data", "") for it in existing_items) if existing_items else "(empty)"
    )

    last_message = state["messages"][-1]
    last_text = getattr(last_message, "content", "") or ""
    if not last_text.strip():
        return {}

    decision: MemoryDecision = _memory_extractor.invoke(
        [
            SystemMessage(content=MEMORY_PROMPT.format(existing=existing_text)),
            {"role": "user", "content": last_text},
        ]
    )

    if decision.should_write:
        for mem in decision.memories:
            if mem.is_new and mem.text.strip():
                store.put(ns, str(uuid.uuid4()), {"data": mem.text.strip()})

    return {}


def read_ltm_text(config: RunnableConfig, *, store: BaseStore) -> str:
    user_id = config["configurable"]["user_id"]
    ns = ("user", user_id, "details")
    items = store.search(ns)
    return "\n".join(it.value.get("data", "") for it in items) if items else ""


_summarizer_llm = ChatOpenAI(
    model=settings.chat_model, temperature=0, api_key=settings.openai_api_key, base_url=settings.llm_base_url
)

def manage_history_node(state: ChatState) -> dict:
    """
    Once the conversation grows past STM_TRIM_MESSAGE_THRESHOLD messages,
    summarize everything except the last STM_KEEP_LAST_N turns into a rolling
    `summary`, and delete the summarized raw messages so the prompt stays bounded.
    """
    messages = state["messages"]
    if len(messages) <= settings.stm_trim_message_threshold:
        return {}

    keep_n = settings.stm_keep_last_n
    to_summarize = messages[:-keep_n]
    existing_summary = state.get("summary", "")

    summary_prompt = (
        f"Existing summary:\n{existing_summary}\n\n"
        "Extend it with the key points of this conversation segment. "
        "Keep it concise (a few sentences)."
    )
    convo_text = "\n".join(f"{m.type}: {m.content}" for m in to_summarize)

    new_summary = _summarizer_llm.invoke(
        [SystemMessage(content=summary_prompt), {"role": "user", "content": convo_text}]
    ).content

    remove_ops = [RemoveMessage(id=m.id) for m in to_summarize if getattr(m, "id", None)]

    return {"summary": new_summary, "messages": remove_ops}
