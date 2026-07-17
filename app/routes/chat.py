import datetime
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.session import ApprovalAuditLog, ChatThread, User, get_db
from app.graph.graph import chatbot
from app.middleware.cost_guard import reconcile_usage, reserve_usage_or_raise
from app.middleware.rate_limit import check_rate_limit
from app.observability.logging_config import get_langfuse_handler, get_logger
from app.schemas import (
    ChatRequest,
    ChatResponse,
    CreateThreadResponse,
    MessageItem,
    ResumeRequest,
    ThreadListResponse,
    ThreadMessagesResponse,
    ThreadSummary,
    UpdateThreadRequest,
)

router = APIRouter(prefix="/chat", tags=["chat"])
log = get_logger(__name__)


def _extract_token_usage(state_values: dict) -> int:
    messages = state_values.get("messages", [])
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


def _authorize_thread(db: Session, thread_id: str, user_id) -> ChatThread:
    existing = db.query(ChatThread).filter(ChatThread.thread_id == thread_id).first()
    if existing is None:
        existing = ChatThread(thread_id=thread_id, user_id=user_id, title="New chat", pinned=False)
        db.add(existing)
        db.commit()
        return existing

    if str(existing.user_id) != str(user_id):
        log.warning("thread_ownership_violation", thread_id=thread_id, requesting_user=str(user_id))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    return existing


def _touch_thread(db: Session, thread: ChatThread, first_message: str | None = None) -> None:
    thread.updated_at = datetime.datetime.utcnow()
    if first_message and (not thread.title or thread.title == "New chat"):
        thread.title = first_message.strip()[:60]
    db.commit()


def _get_real_pending_prompt(config: dict) -> str | None:
    snapshot = chatbot.get_state(config)
    for task in getattr(snapshot, "tasks", []):
        for interrupt in getattr(task, "interrupts", []):
            return interrupt.value
    return None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.get("/threads", response_model=ThreadListResponse)
def list_threads(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    threads = (
        db.query(ChatThread)
        .filter(ChatThread.user_id == current_user.id)
        .order_by(ChatThread.pinned.desc(), ChatThread.updated_at.desc())
        .all()
    )
    return ThreadListResponse(
        threads=[
            ThreadSummary(
                thread_id=t.thread_id,
                title=t.title or "New chat",
                pinned=t.pinned,
                updated_at=t.updated_at,
            )
            for t in threads
        ]
    )


@router.post("/threads", response_model=CreateThreadResponse, status_code=status.HTTP_201_CREATED)
def create_thread(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    new_id = str(uuid.uuid4())
    db.add(ChatThread(thread_id=new_id, user_id=current_user.id, title="New chat", pinned=False))
    db.commit()
    return CreateThreadResponse(thread_id=new_id)


@router.patch("/threads/{thread_id}", response_model=ThreadSummary)
def update_thread(
    thread_id: str,
    payload: UpdateThreadRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    thread = db.query(ChatThread).filter(ChatThread.thread_id == thread_id).first()
    if not thread or str(thread.user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    if payload.title is not None:
        thread.title = payload.title.strip()[:60] or "New chat"
    if payload.pinned is not None:
        thread.pinned = payload.pinned
    db.commit()

    return ThreadSummary(
        thread_id=thread.thread_id, title=thread.title, pinned=thread.pinned, updated_at=thread.updated_at
    )


@router.get("/threads/{thread_id}/messages", response_model=ThreadMessagesResponse)
def get_thread_messages(
    thread_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    thread = db.query(ChatThread).filter(ChatThread.thread_id == thread_id).first()
    if not thread or str(thread.user_id) != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thread not found")

    config = _run_config(thread_id, str(current_user.id))
    snapshot = chatbot.get_state(config)

    messages: list[MessageItem] = []
    for m in snapshot.values.get("messages", []):
        if isinstance(m, HumanMessage) and isinstance(m.content, str) and m.content.strip():
            messages.append(MessageItem(role="user", content=m.content))
        elif isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
            messages.append(MessageItem(role="assistant", content=m.content))

    return ThreadMessagesResponse(thread_id=thread_id, messages=messages)

@router.post("", response_model=ChatResponse)
def send_message(
    payload: ChatRequest,
    current_user: User = Depends(check_rate_limit),
    db: Session = Depends(get_db),
):
    thread = _authorize_thread(db, payload.thread_id, current_user.id)
    reserved = reserve_usage_or_raise(db, current_user.id)

    config = _run_config(payload.thread_id, str(current_user.id))
    result = chatbot.invoke({"messages": [HumanMessage(content=payload.message)]}, config)

    tokens = _extract_token_usage(result)
    reconcile_usage(db, current_user.id, reserved, tokens)
    _touch_thread(db, thread, first_message=payload.message)

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
    thread = _authorize_thread(db, payload.thread_id, current_user.id)
    reserved = reserve_usage_or_raise(db, current_user.id)

    config = _run_config(payload.thread_id, str(current_user.id))

    real_prompt = _get_real_pending_prompt(config) or "(no pending interrupt found)"
    db.add(
        ApprovalAuditLog(
            user_id=current_user.id,
            thread_id=payload.thread_id,
            prompt=real_prompt,
            decision=payload.decision,
        )
    )
    db.commit()

    result = chatbot.invoke(Command(resume=payload.decision), config)

    tokens = _extract_token_usage(result)
    reconcile_usage(db, current_user.id, reserved, tokens)
    _touch_thread(db, thread)

    last_message = result["messages"][-1]
    return ChatResponse(status="ok", reply=last_message.content, thread_id=payload.thread_id)


@router.post("/stream")
def send_message_stream(
    payload: ChatRequest,
    current_user: User = Depends(check_rate_limit),
    db: Session = Depends(get_db),
):
    thread = _authorize_thread(db, payload.thread_id, current_user.id)
    reserved = reserve_usage_or_raise(db, current_user.id)
    config = _run_config(payload.thread_id, str(current_user.id))

    def event_generator():
        try:
            for message_chunk, metadata in chatbot.stream(
                {"messages": [HumanMessage(content=payload.message)]},
                config,
                stream_mode="messages",
            ):
                if metadata.get("langgraph_node") != "chat":
                    continue
                content = getattr(message_chunk, "content", None)
                if content:
                    yield _sse("token", {"content": content})

            snapshot = chatbot.get_state(config)

            pending_prompt = None
            for task in getattr(snapshot, "tasks", []):
                for interrupt in getattr(task, "interrupts", []):
                    pending_prompt = interrupt.value

            tokens = _extract_token_usage(snapshot.values)
            reconcile_usage(db, current_user.id, reserved, tokens)
            _touch_thread(db, thread, first_message=payload.message)

            if pending_prompt:
                yield _sse("interrupt", {"prompt": pending_prompt})
            else:
                yield _sse("done", {})

        except Exception as exc:
            log.error("stream_failed", error=str(exc), thread_id=payload.thread_id)
            reconcile_usage(db, current_user.id, reserved, 0)
            yield _sse("error", {"message": "Something went wrong. Please try again."})

    return StreamingResponse(event_generator(), media_type="text/event-stream")
