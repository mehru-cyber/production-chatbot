import httpx
from langchain_core.tools import tool
from langgraph.types import interrupt
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.graph.cache import stock_price_cache
from app.observability.logging_config import get_logger

log = get_logger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4))
def _fetch_finnhub_quote(symbol: str) -> dict:
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol.upper(), "token": settings.finnhub_api_key}
    with httpx.Client(timeout=5.0) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


@tool
def get_stock_price(symbol: str) -> dict:
    """
    Get the latest quote for a stock symbol (e.g. 'AAPL', 'TSLA').
    Returns current price, change, and percent change.
    """
    if not settings.finnhub_configured:
        return {
            "status": "error",
            "message": (
                "Stock price lookups are not configured. Set FINNHUB_API_KEY "
                "to enable real quotes."
            ),
        }

    symbol = symbol.upper().strip()
    cached = stock_price_cache.get(symbol)
    if cached is not None:
        return cached

    try:
        data = _fetch_finnhub_quote(symbol)
    except httpx.HTTPError as exc:
        log.warning("stock_price_fetch_failed", symbol=symbol, error=str(exc))
        return {
            "status": "error",
            "message": f"Could not fetch a price for {symbol} right now. Try again shortly.",
        }

    if not data or data.get("c") in (None, 0):
        return {"status": "error", "message": f"No quote data found for symbol '{symbol}'."}

    result = {
        "status": "ok",
        "symbol": symbol,
        "current_price": data.get("c"),
        "change": data.get("d"),
        "percent_change": data.get("dp"),
        "high_of_day": data.get("h"),
        "low_of_day": data.get("l"),
    }
    stock_price_cache.set(symbol, result)
    return result


def _execute_paper_trade(symbol: str, quantity: int) -> dict:
    """Places a real order against Alpaca's PAPER trading endpoint. No real money moves."""
    url = f"{settings.alpaca_base_url}/v2/orders"
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key_id,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key,
    }
    payload = {
        "symbol": symbol.upper(),
        "qty": quantity,
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
    }
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        return {
            "status": "error",
            "message": f"Alpaca paper trade failed: {response.text}",
        }
    order = response.json()
    return {
        "status": "success",
        "mode": "paper_trade",
        "message": f"Paper order placed for {quantity} shares of {symbol.upper()}.",
        "order_id": order.get("id"),
        "symbol": symbol.upper(),
        "quantity": quantity,
    }


@tool
def purchase_stock(symbol: str, quantity: int) -> dict:
    """
    Purchase shares of a stock. Requires human approval before executing —
    the assistant will pause and ask you to confirm.

    If Alpaca paper-trading credentials are configured, this places a real
    order on Alpaca's PAPER trading API (no real money). Otherwise it returns
    a clearly labeled simulated response.
    """
    decision = interrupt(f"Approve buying {quantity} shares of {symbol.upper()}? (yes/no)")

    if not (isinstance(decision, str) and decision.strip().lower() == "yes"):
        return {
            "status": "cancelled",
            "message": f"Purchase of {quantity} shares of {symbol.upper()} was declined.",
            "symbol": symbol.upper(),
            "quantity": quantity,
        }

    if settings.alpaca_configured:
        return _execute_paper_trade(symbol, quantity)

    return {
        "status": "success",
        "mode": "simulated",
        "message": (
            f"[SIMULATED — no real or paper order was placed] "
            f"Purchase order for {quantity} shares of {symbol.upper()} would be placed here. "
            "Configure ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY to enable real paper trading."
        ),
        "symbol": symbol.upper(),
        "quantity": quantity,
    }


@tool
def rag_search(query: str) -> dict:
    """
    Search ingested reference documents for information relevant to the query.
    """
    # Stub: no documents are ingested in the base repo. See README section 7
    # for how to point this at a real FAISS/pgvector retriever.
    return {
        "status": "not_configured",
        "message": (
            "No documents have been ingested yet. This tool is a placeholder — "
            "see README section 7 to wire up real document retrieval."
        ),
    }


def get_web_search_tool():
    """Lazy import so the app doesn't hard-depend on duckduckgo-search at startup."""
    from langchain_community.tools import DuckDuckGoSearchRun

    return DuckDuckGoSearchRun()


def get_all_tools() -> list:
    return [get_stock_price, purchase_stock, rag_search, get_web_search_tool()]
