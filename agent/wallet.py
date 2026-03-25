"""Wallet management — pure Python signing with local nonce tracking."""

from __future__ import annotations

import logging
import os
import threading

from eth_account import Account
from eth_utils import to_checksum_address

log = logging.getLogger(__name__)

CHAIN_ID = 3735928814

# Local nonce tracker — avoids stale nonces from the API during fire-and-forget
_nonce_lock = threading.Lock()
_local_nonce: int | None = None


def get_address() -> str:
    """Derive wallet address from private key."""
    private_key = os.environ["PRIVATE_KEY"]
    acct = Account.from_key(private_key)
    return acct.address


def _get_next_nonce(api_nonce: int) -> int:
    """Return the next nonce, using local tracking to stay ahead of the API."""
    global _local_nonce
    with _nonce_lock:
        if _local_nonce is None or api_nonce > _local_nonce:
            # First call or API caught up — sync
            _local_nonce = api_nonce
        else:
            # We're ahead of the API — increment locally
            _local_nonce += 1
        return _local_nonce


def reset_nonce():
    """Reset local nonce tracker (e.g. after errors)."""
    global _local_nonce
    with _nonce_lock:
        _local_nonce = None


def sign_tx(tx_data: dict) -> str:
    """Sign an unsigned transaction dict returned by bot.fun API.

    Uses local nonce tracking to avoid stale nonce conflicts during
    rapid fire-and-forget submission.

    Returns the signed raw transaction as a hex string (0x-prefixed).
    """
    private_key = os.environ["PRIVATE_KEY"]
    api_nonce = int(tx_data.get("nonce", 0))
    nonce = _get_next_nonce(api_nonce)

    tx = {
        "to": to_checksum_address(tx_data["to"]),
        "data": tx_data.get("data", "0x"),
        "value": int(tx_data.get("value", 0)),
        "nonce": nonce,
        "gas": int(tx_data.get("gasLimit", tx_data.get("gas_limit", tx_data.get("gas", 300000)))),
        "gasPrice": int(tx_data.get("gasPrice", tx_data.get("gas_price", 1000000007))),
        "chainId": CHAIN_ID,
    }

    log.info("Signing tx: to=%s nonce=%d gas=%d value=%d",
             tx["to"], tx["nonce"], tx["gas"], tx["value"])

    signed = Account.sign_transaction(tx, private_key)
    return signed.raw_transaction.hex()
