"""Wallet management — Python signing using API-provided nonce."""

from __future__ import annotations

import logging
import os

from eth_account import Account
from eth_utils import to_checksum_address

log = logging.getLogger(__name__)

CHAIN_ID = 3735928814


def get_address() -> str:
    private_key = os.environ["PRIVATE_KEY"]
    return Account.from_key(private_key).address


def sign_tx(tx_data: dict) -> str:
    """Sign tx using the nonce from the API (no local override)."""
    private_key = os.environ["PRIVATE_KEY"]

    tx = {
        "to": to_checksum_address(tx_data["to"]),
        "data": tx_data.get("data", "0x"),
        "value": int(tx_data.get("value", 0)),
        "nonce": int(tx_data.get("nonce", 0)),
        "gas": int(tx_data.get("gasLimit", tx_data.get("gas_limit", tx_data.get("gas", 300000)))),
        "gasPrice": int(tx_data.get("gasPrice", tx_data.get("gas_price", 1000000007))),
        "chainId": CHAIN_ID,
    }

    signed = Account.sign_transaction(tx, private_key)
    return signed.raw_transaction.hex()
