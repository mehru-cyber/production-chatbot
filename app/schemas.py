from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    thread_id: str = Field(min_length=1, max_length=128)


class ResumeRequest(BaseModel):
    thread_id: str = Field(min_length=1, max_length=128)
    decision: str = Field(min_length=1, max_length=16)
    prompt: str | None = Field(default=None, max_length=2000)  # the approval prompt shown to the user, for audit logging


class ChatResponse(BaseModel):
    status: str  # "ok" | "pending_approval"
    reply: str | None = None
    prompt: str | None = None
    thread_id: str