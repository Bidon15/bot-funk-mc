"""Wallet management — uses Foundry's `cast` for offline tx signing."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

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

    # If keystore already exists, derive address from it
    if os.path.isfile(keystore_file):
        log.info("Keystore already exists, deriving address")
        addr = _run_cast(["cast", "wallet", "address", "--account", ACCOUNT_NAME, "--password", password])
        return addr.strip()

    # Write password to temp file for non-interactive import
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as pf:
        pf.write(password)
        pw_file = pf.name

    try:
        # cast wallet import expects interactive input; use stdin piping
        proc = subprocess.run(
            ["cast", "wallet", "import", ACCOUNT_NAME, "--private-key", private_key, "--password-file", pw_file],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"cast wallet import failed: {proc.stderr}")
        log.info("Keystore created: %s", proc.stdout.strip())
    finally:
        os.unlink(pw_file)

    addr = _run_cast(["cast", "wallet", "address", "--account", ACCOUNT_NAME, "--password", password])
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
        "--password", password,
    ]

    signed = _run_cast(cmd)
    return signed.strip()


def _run_cast(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"cast command failed: {' '.join(cmd[:4])}... — {proc.stderr.strip()}")
    return proc.stdout
