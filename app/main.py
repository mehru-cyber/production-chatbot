import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.auth.routes import router as auth_router
from app.config import settings
from app.observability.logging_config import configure_logging, get_logger
from app.routes.chat import router as chat_router
from app.routes.health import router as health_router

configure_logging()
log = get_logger(__name__)

app = FastAPI(
    title="Production LangGraph Chatbot",
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catches anything not already handled as a deliberate HTTPException
    (FastAPI's own HTTPException/RequestValidationError handlers still take
    precedence over this one — Starlette matches the most specific handler
    first). Guarantees two things explicitly, rather than relying on a
    framework default: (1) the client never sees a stack trace or raw
    exception message, and (2) every unhandled error is actually logged
    through our structured logger, with an id the client can quote back if
    they report the issue.
    """
    error_id = str(uuid.uuid4())
    log.error(
        "unhandled_exception",
        error_id=error_id,
        path=str(request.url.path),
        method=request.method,
        exc_info=exc,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong on our end. Please try again.",
            "error_id": error_id,
        },
    )


class EnforceHTTPSMiddleware:
    """
    Pure ASGI middleware (not Starlette's BaseHTTPMiddleware) for HTTPS
    redirection. BaseHTTPMiddleware (the @app.middleware("http") decorator
    style) has a well-documented bug: when a real exception occurs inside a
    route it wraps, it can lose track of the actual response and surface a
    misleading "response was None" ResponseValidationError instead of the
    real underlying exception — actively hiding what actually broke. This
    class-based ASGI middleware operates directly on scope/receive/send and
    doesn't have that failure mode, regardless of whether ENFORCE_HTTPS is
    on or off.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.enforce_https:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        proto = headers.get(b"x-forwarded-proto", b"https").decode()

        if proto == "http":
            request = Request(scope, receive=receive)
            redirect_url = str(request.url.replace(scheme="https"))
            response = RedirectResponse(redirect_url, status_code=308)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


app.add_middleware(EnforceHTTPSMiddleware)


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
        smtp_configured=settings.smtp_configured,
        enforce_https=settings.enforce_https,
    )
