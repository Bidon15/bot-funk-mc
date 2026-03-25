"""Direct RPC client for Eden testnet — nonce and tx submission."""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)

RPC_URL = os.environ.get("RPC_URL", "https://rpc.eu-central-8.gateway.fm/v4/eden/non-archival/testnet")
RPC_AUTH = os.environ.get("RPC_AUTH", "")  # Bearer token


def _rpc_call(method: str, params: list) -> dict:
    headers = {"Content-Type": "application/json"}
    if RPC_AUTH:
        headers["Authorization"] = f"Bearer {RPC_AUTH}"

    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

    with httpx.Client(timeout=15) as c:
        r = c.post(RPC_URL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"RPC error: {data['error']}")
        return data


def get_pending_nonce(address: str) -> int:
    """Get pending transaction count from RPC (includes mempool)."""
    result = _rpc_call("eth_getTransactionCount", [address, "pending"])
    return int(result["result"], 16)


def send_raw_tx(signed_hex: str) -> str:
    """Submit signed tx directly to RPC. Returns tx hash."""
    if not signed_hex.startswith("0x"):
        signed_hex = "0x" + signed_hex
    result = _rpc_call("eth_sendRawTransaction", [signed_hex])
    return result["result"]
