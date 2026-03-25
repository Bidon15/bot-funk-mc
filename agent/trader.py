"""Trading logic — orchestrates market data, LLM decisions, and tx execution."""

from __future__ import annotations

import json
import logging
import os

from . import client, wallet, llm

log = logging.getLogger(__name__)

WEI = 10**18


def gather_market_snapshot(address: str) -> dict:
    """Collect all the data the LLM needs to make a decision."""
    balance = client.get_balance(address)
    agent_info = client.get_agent(address)
    trending = client.get_trending(limit=10)
    new_coins = client.get_new_coins(limit=10)
    leaderboard = client.get_leaderboard(limit=10)

    max_buy = os.environ.get("MAX_BUY_TIA", str(2 * WEI))
    max_impact = int(os.environ.get("MAX_PRICE_IMPACT_BPS", "500"))
    min_profit = int(os.environ.get("MIN_PROFIT_SELL_BPS", "2000"))
    max_loss = int(os.environ.get("MAX_LOSS_SELL_BPS", "3000"))

    return {
        "my_address": address,
        "balance": balance,
        "agent_info": agent_info,
        "trending_coins": trending,
        "new_coins": new_coins,
        "leaderboard": leaderboard,
        "trading_params": {
            "max_buy_tia_wei": max_buy,
            "max_price_impact_bps": max_impact,
            "min_profit_to_sell_bps": min_profit,
            "max_loss_to_cut_bps": max_loss,
        },
    }


def execute_actions(actions: list[dict], address: str) -> list[dict]:
    """Execute a list of LLM-decided actions. Returns results for each."""
    results = []
    for action in actions:
        act = action.get("action", "skip")
        try:
            if act == "buy":
                r = _do_buy(action, address)
            elif act == "sell":
                r = _do_sell(action, address)
            elif act == "launch":
                r = _do_launch(action, address)
            elif act == "post":
                r = _do_post(action, address)
            elif act == "skip":
                r = {"status": "skipped"}
            else:
                r = {"status": "unknown_action", "action": act}
        except Exception as e:
            log.error("Action %s failed: %s", act, e)
            r = {"status": "error", "error": str(e)}
        results.append({"action": act, **r})
    return results


def _sign_and_submit(tx_data: dict) -> dict:
    """Sign a tx and submit it, wait for confirmation."""
    log.info("Raw tx from API: %s", json.dumps(tx_data, default=str)[:500])
    signed = wallet.sign_tx(tx_data)
    result = client.submit_tx(signed)
    tx_hash = result.get("txHash")
    if not tx_hash:
        return {"status": "submit_failed", "result": result}
    log.info("Submitted tx: %s", tx_hash)
    confirmation = client.wait_for_tx(tx_hash)
    return {"status": confirmation.get("status", "unknown"), "txHash": tx_hash, "confirmation": confirmation}


def _do_buy(action: dict, address: str) -> dict:
    coin = action["coin"]
    tia_amount = action["tia_amount"]
    message = action.get("message", "")

    # Safety: check quote for price impact
    quote = client.quote_buy(coin, tia_amount)
    impact = int(quote.get("priceImpact", 0))
    max_impact = int(os.environ.get("MAX_PRICE_IMPACT_BPS", "500"))
    if impact > max_impact:
        return {"status": "skipped_high_impact", "priceImpact": impact, "limit": max_impact}

    min_tokens = quote.get("tokenAmount", "0")
    # Apply 5% slippage tolerance
    min_tokens = str(int(int(min_tokens) * 95 // 100))

    tx_data = client.build_buy(address, coin, tia_amount, min_tokens_out=min_tokens, message=message)
    return _sign_and_submit(tx_data)


def _do_sell(action: dict, address: str) -> dict:
    coin = action["coin"]
    token_amount = action["token_amount"]
    message = action.get("message", "")

    # Step 1: approve
    approve_tx = client.build_approve(address, coin)
    approve_result = _sign_and_submit(approve_tx)
    if approve_result.get("status") != "confirmed":
        return {"status": "approve_failed", "details": approve_result}

    # Step 2: get sell quote for slippage
    quote = client.quote_sell(coin, token_amount)
    min_tia = str(int(int(quote.get("tiaAmount", "0")) * 95 // 100))

    # Step 3: sell
    tx_data = client.build_sell(address, coin, token_amount, min_tia_out=min_tia, message=message)
    return _sign_and_submit(tx_data)


def _do_launch(action: dict, address: str) -> dict:
    name = action["name"]
    symbol = action["symbol"]
    description = action["description"]
    svg = action["svg"]
    value = action.get("value", "2000000000000000000")

    tx_data = client.build_launch(name, symbol, description, svg, address, value)
    return _sign_and_submit(tx_data)


def _do_post(action: dict, address: str) -> dict:
    coin = action["coin"]
    message = action["message"]

    tx_data = client.build_post(address, coin, message)
    return _sign_and_submit(tx_data)
