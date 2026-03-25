"""Wallet management — pure Python signing with eth-account."""

from __future__ import annotations

import logging
import os

from eth_account import Account
from eth_utils import to_checksum_address

log = logging.getLogger(__name__)

CHAIN_ID = 3735928814


def get_address() -> str:
    """Derive wallet address from private key."""
    private_key = os.environ["PRIVATE_KEY"]
    acct = Account.from_key(private_key)
    return acct.address


def sign_tx(tx_data: dict) -> str:
    """Sign an unsigned transaction dict returned by bot.fun API.

    Returns the signed raw transaction as a hex string (0x-prefixed).
    """
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

    log.info("Signing tx: to=%s nonce=%d gas=%d gasPrice=%d value=%d",
             tx["to"], tx["nonce"], tx["gas"], tx["gasPrice"], tx["value"])

    signed = Account.sign_transaction(tx, private_key)
    return signed.raw_transaction.hex()
