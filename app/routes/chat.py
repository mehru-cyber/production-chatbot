from fastapi import APIRouter, Depends
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.db.session import User, get_db
from app.graph.graph import chatbot
from app.middleware.cost_guard import assert_within_daily_cap, record_usage
from app.middleware.rate_limit import check_rate_limit
from app.observability.logging_config import get_langfuse_handler, get_logger
from app.schemas import ChatRequest, ChatResponse, ResumeRequest

router = APIRouter(prefix="/chat", tags=["chat"])
log = get_logger(__name__)


def _extract_token_usage(result: dict) -> int:
    """Best-effort token count from the last AI message's usage metadata."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        usage = getattr(msg, "usage_metadata", None)
        if usage:
            return usage.get("total_tokens", 0)
    return 0


def _run_config(thread_id: str, user_id: str) -> dict:
    cfg = {"configurable": {"thread_id": thread_id, "user_id": user_id}}
    handler = get_langfuse_handler()
    if handler:
        cfg["callbacks"] = [handler]
    return cfg


@router.post("", response_model=ChatResponse)
def send_message(
    payload: ChatRequest,
    current_user: User = Depends(check_rate_limit),
    db: Session = Depends(get_db),
):
    assert_within_daily_cap(db, current_user.id)

    config = _run_config(payload.thread_id, str(current_user.id))
    result = chatbot.invoke({"messages": [HumanMessage(content=payload.message)]}, config)

    tokens = _extract_token_usage(result)
    record_usage(db, current_user.id, tokens)

    interrupts = result.get("__interrupt__", [])
    if interrupts:
        return ChatResponse(status="pending_approval", prompt=interrupts[0].value, thread_id=payload.thread_id)

    last_message = result["messages"][-1]
    return ChatResponse(status="ok", reply=last_message.content, thread_id=payload.thread_id)


@router.post("/resume", response_model=ChatResponse)
def resume(
    payload: ResumeRequest,
    current_user: User = Depends(check_rate_limit),
    db: Session = Depends(get_db),
):
    assert_within_daily_cap(db, current_user.id)

    config = _run_config(payload.thread_id, str(current_user.id))
    result = chatbot.invoke(Command(resume=payload.decision), config)

    tokens = _extract_token_usage(result)
    record_usage(db, current_user.id, tokens)

    last_message = result["messages"][-1]
    return ChatResponse(status="ok", reply=last_message.content, thread_id=payload.thread_id)
