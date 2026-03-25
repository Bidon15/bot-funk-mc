"""Wallet management — Python signing with RPC-based nonce tracking."""

from __future__ import annotations

import logging
import os
import threading

from eth_account import Account
from eth_utils import to_checksum_address

from . import rpc

log = logging.getLogger(__name__)

CHAIN_ID = 3735928814

_nonce_lock = threading.Lock()
_local_nonce: int | None = None


def get_address() -> str:
    private_key = os.environ["PRIVATE_KEY"]
    return Account.from_key(private_key).address


def sync_nonce(address: str):
    """Sync local nonce from RPC pending count. Call at cycle start."""
    global _local_nonce
    pending = rpc.get_pending_nonce(address)
    with _nonce_lock:
        _local_nonce = pending
    log.info("Nonce synced from RPC: %d", pending)


def _next_nonce() -> int:
    global _local_nonce
    with _nonce_lock:
        if _local_nonce is None:
            raise RuntimeError("Nonce not synced — call sync_nonce() first")
        n = _local_nonce
        _local_nonce += 1
        return n


def sign_tx(tx_data: dict) -> str:
    """Sign tx with locally-managed nonce (ignores API nonce)."""
    private_key = os.environ["PRIVATE_KEY"]
    nonce = _next_nonce()

    tx = {
        "to": to_checksum_address(tx_data["to"]),
        "data": tx_data.get("data", "0x"),
        "value": int(tx_data.get("value", 0)),
        "nonce": nonce,
        "gas": int(tx_data.get("gasLimit", tx_data.get("gas_limit", tx_data.get("gas", 300000)))),
        "gasPrice": int(tx_data.get("gasPrice", tx_data.get("gas_price", 1000000007))),
        "chainId": CHAIN_ID,
    }

    signed = Account.sign_transaction(tx, private_key)
    return signed.raw_transaction.hex()
