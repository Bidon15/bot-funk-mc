"""Wallet management — uses Foundry's `cast` for offline tx signing."""

from __future__ import annotations

import logging
import os
import subprocess

log = logging.getLogger(__name__)

CHAIN_ID = "3735928814"
KEYSTORE_DIR = os.path.expanduser("~/.foundry/keystores")
ACCOUNT_NAME = "botfun-agent"


def setup_keystore() -> str:
    """Import private key into cast keystore at startup. Returns wallet address."""
    private_key = os.environ["PRIVATE_KEY"]
    password = os.environ["KEYSTORE_PASSWORD"]

    os.makedirs(KEYSTORE_DIR, exist_ok=True)
    keystore_file = os.path.join(KEYSTORE_DIR, ACCOUNT_NAME)

    if not os.path.isfile(keystore_file):
        proc = subprocess.run(
            ["cast", "wallet", "import", ACCOUNT_NAME, "--private-key", private_key, "--unsafe-password", password],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"cast wallet import failed: {proc.stderr}")
        log.info("Keystore created: %s", proc.stdout.strip())
    else:
        log.info("Keystore already exists")

    # Derive address from private key directly (no keystore password needed)
    addr = _run_cast(["cast", "wallet", "address", private_key])
    return addr.strip()


def sign_tx(tx_data: dict) -> str:
    """Sign an unsigned transaction dict returned by bot.fun API using cast mktx.

    Returns the signed raw transaction hex string.
    """
    password = os.environ["KEYSTORE_PASSWORD"]
    to = tx_data["to"]
    data = tx_data["data"]
    value = str(tx_data.get("value", "0"))
    nonce = str(tx_data["nonce"])
    gas_limit = str(tx_data["gasLimit"])
    gas_price = str(tx_data["gasPrice"])

    cmd = [
        "cast", "mktx", to, data,
        "--value", value,
        "--nonce", nonce,
        "--gas-limit", gas_limit,
        "--gas-price", gas_price,
        "--chain", CHAIN_ID,
        "--account", ACCOUNT_NAME,
    ]

    # Pass password via --password flag for non-interactive signing
    cmd += ["--password", password]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"cast mktx failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _run_cast(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"cast command failed: {' '.join(cmd[:4])}... — {proc.stderr.strip()}")
    return proc.stdout
