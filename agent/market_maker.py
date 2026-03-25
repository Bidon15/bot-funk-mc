"""Programmatic high-frequency market maker — no LLM needed for trades."""

from __future__ import annotations

import logging
import os
import time

from . import client, wallet

log = logging.getLogger(__name__)

WEI = 10**18
MIN_BUY_TIA = int(os.environ.get("MM_MIN_BUY_WEI", str(int(0.5 * WEI))))  # 0.5 TIA default
SELL_PROFIT_THRESHOLD = 0.02  # sell when unrealized > 2% of cost
MAX_TXS_PER_CYCLE = int(os.environ.get("MM_MAX_TXS", "300"))


def _fire_tx(tx_data: dict) -> str | None:
    """Sign and submit a tx, don't wait for confirmation. Returns txHash or None."""
    try:
        signed = wallet.sign_tx(tx_data)
        result = client.submit_tx(signed)
        return result.get("txHash")
    except Exception as e:
        log.warning("tx failed: %s", str(e)[:120])
        return None


def run_cycle(address: str) -> dict:
    """Run one market-making cycle. Returns summary stats."""
    stats = {"buys": 0, "sells": 0, "posts": 0, "errors": 0, "buy_tia": 0, "sell_tia": 0}
    tx_count = 0

    # ── 1. Get our positions and find profitable ones to sell ─────
    log.info("=== MM: Scanning positions for profit ===")
    try:
        agent_info = client.get_agent(address)
        positions = agent_info.get("positions", [])
    except Exception:
        positions = []

    # Track which coins we've approved this cycle
    approved = set()

    # Sell profitable positions first (this generates realized PnL)
    profitable = []
    for p in positions:
        try:
            balance = float(p.get("balance", 0))
            cost = float(p.get("costBasis", 0))
            value = float(p.get("currentValue", 0))
            if balance <= 0 or cost <= 0:
                continue
            profit_ratio = (value - cost) / cost if cost > 0 else 0
            if profit_ratio > SELL_PROFIT_THRESHOLD and value > 0.001:
                profitable.append({**p, "_profit_ratio": profit_ratio, "_balance": balance, "_value": value})
        except (ValueError, TypeError):
            continue

    profitable.sort(key=lambda x: x["_value"], reverse=True)
    log.info("Found %d profitable positions to sell", len(profitable))

    for p in profitable:
        if tx_count >= MAX_TXS_PER_CYCLE:
            break
        coin_addr = p.get("coinAddress", "")
        if not coin_addr:
            continue

        # Sell 80% of position
        sell_balance = int(p["_balance"] * 0.8)
        if sell_balance <= 0:
            continue
        sell_amount = str(sell_balance)

        try:
            # Approve if not yet done this cycle
            if coin_addr not in approved:
                approve_tx = client.build_approve(address, coin_addr)
                h = _fire_tx(approve_tx)
                if h:
                    tx_count += 1
                    approved.add(coin_addr)
                    time.sleep(0.5)  # brief wait for approve to land
                else:
                    stats["errors"] += 1
                    continue

            # Sell
            sell_tx = client.build_sell(address, coin_addr, sell_amount, min_tia_out="0",
                                        message=f"Taking profit on {p.get('coinSymbol', '?')}")
            h = _fire_tx(sell_tx)
            if h:
                tx_count += 1
                stats["sells"] += 1
                stats["sell_tia"] += p["_value"] * 0.8
                log.info("SELL %s: %s (profit %.1f%%)", p.get("coinSymbol", "?"), h, p["_profit_ratio"] * 100)
            else:
                stats["errors"] += 1
        except Exception as e:
            log.warning("Sell %s failed: %s", p.get("coinSymbol", "?"), str(e)[:100])
            stats["errors"] += 1

    # ── 2. Buy into trending and new coins ────────────────────────
    log.info("=== MM: Buying into coins ===")
    buy_amount = str(MIN_BUY_TIA)

    # Collect target coins from trending + new
    target_coins = []
    try:
        trending = client.get_trending(limit=15)
        coins_list = trending if isinstance(trending, list) else trending.get("coins", trending.get("data", []))
        for c in coins_list:
            addr = c.get("address", c.get("coinAddress", ""))
            if addr:
                target_coins.append({"address": addr, "symbol": c.get("symbol", c.get("coinSymbol", "?")), "source": "trending"})
    except Exception as e:
        log.warning("Failed to get trending: %s", e)

    try:
        new_coins = client.get_new_coins(limit=15)
        coins_list = new_coins if isinstance(new_coins, list) else new_coins.get("coins", new_coins.get("data", []))
        for c in coins_list:
            addr = c.get("address", c.get("coinAddress", ""))
            if addr and addr not in [t["address"] for t in target_coins]:
                target_coins.append({"address": addr, "symbol": c.get("symbol", c.get("coinSymbol", "?")), "source": "new"})
    except Exception as e:
        log.warning("Failed to get new coins: %s", e)

    log.info("Target coins: %d", len(target_coins))

    # Buy each coin multiple times to hit tx count target
    rounds = 0
    while tx_count < MAX_TXS_PER_CYCLE and target_coins:
        for coin in target_coins:
            if tx_count >= MAX_TXS_PER_CYCLE:
                break
            try:
                tx_data = client.build_buy(address, coin["address"], buy_amount, min_tokens_out="0",
                                           message=f"MM buy {coin['symbol']}" if rounds == 0 else "")
                h = _fire_tx(tx_data)
                if h:
                    tx_count += 1
                    stats["buys"] += 1
                    stats["buy_tia"] += MIN_BUY_TIA / WEI
                else:
                    stats["errors"] += 1
            except Exception as e:
                log.warning("Buy %s failed: %s", coin["symbol"], str(e)[:100])
                stats["errors"] += 1
        rounds += 1
        # Safety: don't loop forever if we can't fill
        if rounds > 20:
            break

    stats["total_txs"] = tx_count
    log.info("=== MM Cycle done: %s ===", stats)
    return stats
