from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.routes import router as auth_router
from app.config import settings
from app.observability.logging_config import configure_logging, get_logger
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router

configure_logging()
log = get_logger(__name__)

app = FastAPI(title="Production LangGraph Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(health_router)


@app.on_event("startup")
def on_startup():
    log.info(
        "app_startup",
        finnhub_configured=settings.finnhub_configured,
        alpaca_configured=settings.alpaca_configured,
        langfuse_configured=settings.langfuse_configured,
    )
