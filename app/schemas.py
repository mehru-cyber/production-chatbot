from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    thread_id: str


class ResumeRequest(BaseModel):
    thread_id: str
    decision: str


class ChatResponse(BaseModel):
    status: str  # "ok" | "pending_approval"
    reply: str | None = None
    prompt: str | None = None
    thread_id: str
