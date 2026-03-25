"""bot.fun autonomous trading agent — high-frequency market maker."""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from agent import client, wallet, market_maker, server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("botfun")


def startup() -> str:
    """Initialise wallet, register username, request faucet if needed. Returns address."""
    address = wallet.get_address()
    log.info("Wallet address: %s", address)

    try:
        bal = client.get_balance(address)
        tia_balance = int(bal.get("balance", bal.get("tiaBalance", "0")))
        log.info("TIA balance: %s wei", tia_balance)
        if tia_balance < 10**18:
            log.info("Low balance, requesting faucet...")
            faucet_resp = client.request_faucet(address)
            log.info("Faucet response: %s", json.dumps(faucet_resp))
            time.sleep(5)
    except Exception as e:
        log.warning("Balance/faucet check failed: %s", e)

    username = os.environ.get("AGENT_USERNAME")
    if username:
        try:
            agent_info = client.get_agent(address)
            existing = agent_info.get("username") or agent_info.get("agent", {}).get("username")
            if not existing:
                log.info("Registering username: %s", username)
                tx_data = client.build_register_username(address, username)
                signed = wallet.sign_tx(tx_data)
                result = client.submit_tx(signed)
                tx_hash = result.get("txHash")
                if tx_hash:
                    client.wait_for_tx(tx_hash)
                    log.info("Username registered: %s.bf", username)
            else:
                log.info("Username already registered: %s", existing)
        except Exception as e:
            log.warning("Username registration skipped: %s", e)

    return address


def run_loop(address: str):
    """Main market-making loop — programmatic high-frequency trading."""
    interval = int(os.environ.get("LOOP_INTERVAL_SECONDS", "30"))
    cycle = 0

    while True:
        cycle += 1
        try:
            log.info("=== CYCLE %d START ===", cycle)
            stats = market_maker.run_cycle(address)
            server.set_last_cycle({"cycle": cycle, "stats": stats, "ts": time.time()})
            log.info("=== CYCLE %d DONE: %d txs (%d buys, %d sells, %d errors) ===",
                     cycle, stats["total_txs"], stats["buys"], stats["sells"], stats["errors"])
        except Exception as e:
            log.error("Cycle %d failed: %s", cycle, e, exc_info=True)

        log.info("Sleeping %ds...", interval)
        time.sleep(interval)


def main():
    log.info("=== bot.fun Market Maker starting ===")
    server.start()
    address = startup()
    run_loop(address)


if __name__ == "__main__":
    main()
