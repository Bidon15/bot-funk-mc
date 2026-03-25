"""bot.fun autonomous trading agent — main loop."""

from __future__ import annotations

import json
import logging
import os
import sys
import time

from agent import client, wallet, trader, llm, server

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

    # Request faucet TIA if balance is low
    try:
        bal = client.get_balance(address)
        tia_balance = int(bal.get("balance", bal.get("tiaBalance", "0")))
        log.info("TIA balance: %s wei", tia_balance)
        if tia_balance < 10**18:  # < 1 TIA
            log.info("Low balance, requesting faucet...")
            faucet_resp = client.request_faucet(address)
            log.info("Faucet response: %s", json.dumps(faucet_resp))
            time.sleep(5)
    except Exception as e:
        log.warning("Balance/faucet check failed (may be fine on first run): %s", e)

    # Register username if configured
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
    """Main trading loop — gather data, ask LLM, execute."""
    interval = int(os.environ.get("LOOP_INTERVAL_SECONDS", "180"))

    while True:
        try:
            log.info("=== Gathering market snapshot ===")
            snapshot = trader.gather_market_snapshot(address)

            log.info("=== Asking LLM for decisions ===")
            actions = llm.decide_actions(snapshot)
            log.info("LLM decided %d action(s): %s", len(actions), json.dumps(actions, default=str)[:500])

            if actions and actions[0].get("action") != "skip":
                log.info("=== Executing actions ===")
                results = trader.execute_actions(actions, address)
                for r in results:
                    log.info("Result: %s", json.dumps(r, default=str)[:300])
                server.set_last_cycle({"actions": actions, "results": results, "ts": time.time()})
            else:
                log.info("LLM decided to skip this cycle.")
                server.set_last_cycle({"actions": [{"action": "skip"}], "results": [], "ts": time.time()})

        except Exception as e:
            log.error("Loop iteration failed: %s", e, exc_info=True)

        log.info("Sleeping %ds until next cycle...", interval)
        time.sleep(interval)


def main():
    log.info("=== bot.fun Trading Agent starting ===")
    server.start()
    address = startup()
    run_loop(address)


if __name__ == "__main__":
    main()
