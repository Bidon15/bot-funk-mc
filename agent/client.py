"""bot.fun API client — market data, quotes, tx building, and submission."""

from __future__ import annotations

import httpx
import time
import os
import logging

log = logging.getLogger(__name__)

API = os.environ.get("BOTFUN_API", "https://testnet12.bot.fun")
_MIN_REQUEST_GAP = 0.22  # 200ms+ between requests (rate limit)
_last_request_ts: float = 0.0


def _client() -> httpx.Client:
    return httpx.Client(base_url=API, timeout=30)


def _throttle():
    global _last_request_ts
    now = time.monotonic()
    gap = now - _last_request_ts
    if gap < _MIN_REQUEST_GAP:
        time.sleep(_MIN_REQUEST_GAP - gap)
    _last_request_ts = time.monotonic()


# ── Market data ──────────────────────────────────────────────

def get_chain_info() -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/chain").json()


def get_coins(page: int = 1, page_size: int = 20, sort: str = "market_cap", order: str = "desc", search: str = "") -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/coins", params={"page": page, "pageSize": page_size, "sort": sort, "order": order, "search": search}).json()


def get_trending(limit: int = 20) -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/coins/trending", params={"limit": limit}).json()


def get_new_coins(limit: int = 20) -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/coins/new", params={"limit": limit}).json()


def get_coin(coin_id: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/coins/{coin_id}").json()


def get_coin_activity(coin_id: str, page: int = 1, page_size: int = 20) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/coins/{coin_id}/activity", params={"page": page, "pageSize": page_size}).json()


def get_candles(coin_id: str, interval: str = "1h", limit: int = 200) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/coins/{coin_id}/candles", params={"interval": interval, "limit": limit}).json()


def get_global_activity(page: int = 1, page_size: int = 50) -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/activity", params={"page": page, "pageSize": page_size}).json()


def get_agents(sort: str = "total_pnl", order: str = "desc") -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/agents", params={"sort": sort, "order": order}).json()


def get_agent(address: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/agents/{address}").json()


def get_leaderboard(limit: int = 50) -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/leaderboard", params={"limit": limit}).json()


# ── Quotes ───────────────────────────────────────────────────

def quote_buy(coin_address: str, tia_amount: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/quote/buy", params={"coin": coin_address, "tiaAmount": tia_amount}).json()


def quote_sell(coin_address: str, token_amount: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get("/api/v1/quote/sell", params={"coin": coin_address, "tokenAmount": token_amount}).json()


# ── Balance / Faucet ─────────────────────────────────────────

def get_balance(address: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/balance/{address}").json()


def request_faucet(address: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/faucet/drip", params={"address": address}).json()


# ── Transaction building ─────────────────────────────────────

def _build_tx(endpoint: str, payload: dict) -> dict:
    _throttle()
    with _client() as c:
        r = c.post(f"/api/v1/tx/build/{endpoint}", json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"tx/build/{endpoint} {r.status_code}: {r.text[:300]}")
        return r.json()


def build_buy(from_addr: str, coin_address: str, tia_amount: str, min_tokens_out: str = "0", message: str = "") -> dict:
    payload = {"from": from_addr, "coinAddress": coin_address, "tiaAmount": tia_amount, "minTokensOut": min_tokens_out}
    if message:
        payload["message"] = message
    return _build_tx("buy", payload)


def build_sell(from_addr: str, coin_address: str, token_amount: str, min_tia_out: str = "0", message: str = "") -> dict:
    payload = {"from": from_addr, "coinAddress": coin_address, "tokenAmount": token_amount, "minTiaOut": min_tia_out}
    if message:
        payload["message"] = message
    return _build_tx("sell", payload)


def build_approve(from_addr: str, coin_address: str) -> dict:
    return _build_tx("approve", {"from": from_addr, "coinAddress": coin_address})


def build_launch(name: str, symbol: str, description: str, svg: str, from_addr: str, value: str = "2000000000000000000") -> dict:
    return _build_tx("launch", {"name": name, "symbol": symbol, "description": description, "svg": svg, "from": from_addr, "value": value})


def build_register_username(from_addr: str, username: str) -> dict:
    return _build_tx("register-username", {"from": from_addr, "username": username})


def build_post(from_addr: str, coin_address: str, message: str) -> dict:
    return _build_tx("post", {"from": from_addr, "coinAddress": coin_address, "message": message})


def build_transfer(from_addr: str, coin_address: str, to: str, amount: str) -> dict:
    return _build_tx("transfer", {"from": from_addr, "coinAddress": coin_address, "to": to, "amount": amount})


# ── Submit & track ───────────────────────────────────────────

def submit_tx(signed_tx: str) -> dict:
    _throttle()
    with _client() as c:
        r = c.post("/api/v1/tx/submit", json={"signedTx": signed_tx})
        r.raise_for_status()
        return r.json()


def get_tx_status(tx_hash: str) -> dict:
    _throttle()
    with _client() as c:
        return c.get(f"/api/v1/tx/{tx_hash}/status").json()


def wait_for_tx(tx_hash: str, timeout: int = 60, poll_interval: float = 2.0) -> dict:
    """Poll tx status until confirmed or timeout."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        status = get_tx_status(tx_hash)
        if status.get("status") in ("confirmed", "failed"):
            return status
        time.sleep(poll_interval)
    return {"txHash": tx_hash, "status": "timeout"}
