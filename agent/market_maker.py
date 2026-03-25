"""High-frequency market maker — LLM picks strategy, code executes at volume."""

from __future__ import annotations

import json
import logging
import os
import time

from . import client, wallet, llm, server

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


WHALE_AGENTS = {
    "0x95b84eb47e8f7c8ffa5c7469f2fdfa1f0dac2e25": "jonas089",
    "0xc9f5979c4447ef320b58279a6be19e749392b307": "ceausescu",
    "0x6bc3727fe0cafa22a9983b6efc21cee82c563ea5": "action_hous",
    "0xd5b4f3de07bcbda7ad6a1cd81adf0525bc0abfbc": "oracle_oz",
    "0xef22c4685a0cf3fdadea777e4c541a256e2bb636": "diamond_dave",
}


def _gather_whale_intel() -> list[dict]:
    """Fetch recent activity for each whale agent — what are they buying/selling?"""
    intel = []
    for addr, name in WHALE_AGENTS.items():
        try:
            agent_data = client.get_agent(addr)
            # Top positions
            top_pos = []
            for p in sorted(agent_data.get("positions", []), key=lambda x: float(x.get("currentValue", 0)), reverse=True)[:5]:
                val = float(p.get("currentValue", 0))
                cost = float(p.get("costBasis", 0))
                if val < 0.01:
                    continue
                top_pos.append({
                    "coin": p.get("coinSymbol", "?"),
                    "address": p.get("coinAddress", ""),
                    "value": round(val, 2),
                    "cost": round(cost, 2),
                    "unrealized_pct": round((val - cost) / cost * 100, 1) if cost > 0 else 0,
                })

            intel.append({
                "name": name,
                "address": addr,
                "realized_pnl": round(float(agent_data.get("realizedPnl", 0)), 2),
                "unrealized_pnl": round(float(agent_data.get("unrealizedPnl", 0)), 2),
                "top_positions": top_pos,
            })
        except Exception as e:
            log.warning("Failed to fetch whale %s: %s", name, str(e)[:60])
    return intel


def _ask_llm_for_targets(address: str, positions: list, trending: list, new_coins: list) -> dict:
    """Ask LLM which coins to buy, sell, and post about. Returns structured plan."""
    from . import server as srv

    instructions = srv.get_instructions()
    operator_block = ""
    if instructions:
        lines = "\n".join(f"- {i}" for i in instructions)
        operator_block = f"\nOPERATOR INSTRUCTIONS:\n{lines}\n"

    balance = client.get_balance(address)

    # Summarize positions compactly
    pos_summary = []
    for p in positions[:30]:
        try:
            val = float(p.get("currentValue", 0))
            cost = float(p.get("costBasis", 0))
            if val < 0.001 and cost < 0.001:
                continue
            pos_summary.append({
                "symbol": p.get("coinSymbol", "?"),
                "address": p.get("coinAddress", ""),
                "value": round(val, 4),
                "cost": round(cost, 4),
                "profit_pct": round((val - cost) / cost * 100, 1) if cost > 0 else 0,
            })
        except (ValueError, TypeError):
            continue

    # Fetch whale agent history — what are they buying/selling?
    whale_intel = _gather_whale_intel()

    # Recent global activity
    recent_activity = []
    try:
        activity = client.get_global_activity(page=1, page_size=30)
        act_list = activity if isinstance(activity, list) else activity.get("activity", activity.get("data", activity.get("items", [])))
        for a in act_list[:30]:
            recent_activity.append({
                "agent": a.get("username", a.get("agentUsername", a.get("address", "?")[:10])),
                "type": a.get("type", a.get("activityType", "?")),
                "coin": a.get("coinSymbol", a.get("symbol", "?")),
                "coinAddress": a.get("coinAddress", ""),
                "tiaAmount": a.get("tiaAmount", ""),
                "message": (a.get("message", a.get("content", "")))[:80],
            })
    except Exception:
        pass

    snapshot = {
        "balance": balance,
        "positions": pos_summary,
        "trending": [{"symbol": c.get("symbol", c.get("coinSymbol", "?")), "address": c.get("address", c.get("coinAddress", ""))} for c in trending[:15]],
        "new_coins": [{"symbol": c.get("symbol", c.get("coinSymbol", "?")), "address": c.get("address", c.get("coinAddress", ""))} for c in new_coins[:15]],
        "whale_intel": whale_intel,
        "recent_activity": recent_activity,
    }

    user_msg = f"""\
You are the STRATEGIST for a high-frequency market maker on bot.fun. Each cycle the engine executes 200-300 transactions.
Your job: pick WHICH coins to buy, which to sell, and what to post. The engine handles execution volume.
{operator_block}
Current state:
{json.dumps(snapshot, indent=2)}

WHALE INTELLIGENCE — use this to time entries and exits:
- "whale_intel" shows each whale's positions, realized vs unrealized PnL
- "recent_activity" shows the last 30 trades/posts across the platform
- If a whale is BUYING a coin → ride their pump, buy the same coin
- If a whale is SELLING a coin → SELL IMMEDIATELY before they crash the price
- If a whale has massive unrealized PnL and starts taking small sells → they're about to rug, dump everything in that coin
- Whales with high unrealized but low realized = vulnerable to rug, parasitize them

Return a JSON object with these fields:
- "buy_coins": list of coin addresses to buy into (engine buys each one multiple times at 0.5 TIA per tx)
- "sell_coins": list of coin addresses to sell (engine sells 80% of our position for each)
- "posts": list of {{"coin": "<address>", "message": "<text>"}} to post (max 5, be spicy)
- "reasoning": one sentence on your strategy this cycle

Return ONLY JSON, no markdown fences."""

    resp = llm._get_client().messages.create(
        model=llm._get_model(),
        max_tokens=2048,
        system=llm.SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = llm._extract_text(resp)
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON for strategy: %s", text[:200])
        return {"buy_coins": [], "sell_coins": [], "posts": [], "reasoning": "fallback"}


def run_cycle(address: str) -> dict:
    """Run one market-making cycle: LLM picks targets, engine executes at volume."""
    # Reset nonce at cycle start so first API call syncs, then we track locally
    wallet.reset_nonce()

    stats = {"buys": 0, "sells": 0, "posts": 0, "errors": 0, "total_txs": 0}
    tx_count = 0

    # ── Gather market data ────────────────────────────────────────
    try:
        agent_info = client.get_agent(address)
        positions = agent_info.get("positions", [])
    except Exception:
        positions = []

    trending_raw = []
    new_raw = []
    try:
        t = client.get_trending(limit=15)
        trending_raw = t if isinstance(t, list) else t.get("coins", t.get("data", []))
    except Exception:
        pass
    try:
        n = client.get_new_coins(limit=15)
        new_raw = n if isinstance(n, list) else n.get("coins", n.get("data", []))
    except Exception:
        pass

    # ── Ask LLM for strategy ──────────────────────────────────────
    log.info("=== Asking LLM for strategy ===")
    plan = _ask_llm_for_targets(address, positions, trending_raw, new_raw)
    log.info("LLM strategy: %s", plan.get("reasoning", "?"))
    log.info("LLM buy targets: %d coins, sell targets: %d coins, posts: %d",
             len(plan.get("buy_coins", [])), len(plan.get("sell_coins", [])), len(plan.get("posts", [])))

    # ── Execute sells first (realized PnL) ────────────────────────
    sell_targets = set(plan.get("sell_coins", []))
    # Also auto-sell anything profitable even if LLM didn't pick it
    for p in positions:
        try:
            val = float(p.get("currentValue", 0))
            cost = float(p.get("costBasis", 0))
            if cost > 0 and (val - cost) / cost > SELL_PROFIT_THRESHOLD:
                sell_targets.add(p.get("coinAddress", ""))
        except (ValueError, TypeError):
            continue

    approved = set()
    pos_by_addr = {p.get("coinAddress", ""): p for p in positions}

    for coin_addr in sell_targets:
        if tx_count >= MAX_TXS_PER_CYCLE or not coin_addr:
            break
        p = pos_by_addr.get(coin_addr)
        if not p:
            continue
        try:
            balance = float(p.get("balance", 0))
            if balance <= 0:
                continue
            sell_amount = str(int(balance * 0.8))

            # Approve
            if coin_addr not in approved:
                approve_tx = client.build_approve(address, coin_addr)
                h = _fire_tx(approve_tx)
                if h:
                    tx_count += 1
                    approved.add(coin_addr)
                    time.sleep(0.5)
                else:
                    stats["errors"] += 1
                    continue

            # Sell
            sell_tx = client.build_sell(address, coin_addr, sell_amount, min_tia_out="0",
                                        message=f"Locking profit on {p.get('coinSymbol', '?')}")
            h = _fire_tx(sell_tx)
            if h:
                tx_count += 1
                stats["sells"] += 1
                log.info("SELL %s: %s", p.get("coinSymbol", "?"), h)
            else:
                stats["errors"] += 1
        except Exception as e:
            log.warning("Sell failed: %s", str(e)[:100])
            stats["errors"] += 1

    # ── Execute buys at volume ────────────────────────────────────
    buy_targets = plan.get("buy_coins", [])
    # Fallback: if LLM gave nothing, use trending
    if not buy_targets:
        buy_targets = [c.get("address", c.get("coinAddress", "")) for c in trending_raw[:10]]

    buy_targets = [a for a in buy_targets if a]  # filter empty
    buy_amount = str(MIN_BUY_TIA)

    log.info("=== Executing %d buy targets, filling to %d txs ===", len(buy_targets), MAX_TXS_PER_CYCLE)
    rounds = 0
    while tx_count < MAX_TXS_PER_CYCLE and buy_targets:
        for coin_addr in buy_targets:
            if tx_count >= MAX_TXS_PER_CYCLE:
                break
            try:
                msg = "" if rounds > 0 else f"Market making round {rounds + 1}"
                tx_data = client.build_buy(address, coin_addr, buy_amount, min_tokens_out="0", message=msg)
                h = _fire_tx(tx_data)
                if h:
                    tx_count += 1
                    stats["buys"] += 1
                else:
                    stats["errors"] += 1
            except Exception as e:
                log.warning("Buy failed: %s", str(e)[:100])
                stats["errors"] += 1
        rounds += 1
        if rounds > 30:
            break

    # ── Execute posts ─────────────────────────────────────────────
    for post in plan.get("posts", [])[:5]:
        if tx_count >= MAX_TXS_PER_CYCLE:
            break
        try:
            coin_addr = post.get("coin", "")
            message = post.get("message", "")
            if not coin_addr or not message:
                continue
            tx_data = client.build_post(address, coin_addr, message)
            h = _fire_tx(tx_data)
            if h:
                tx_count += 1
                stats["posts"] += 1
            else:
                stats["errors"] += 1
        except Exception as e:
            log.warning("Post failed: %s", str(e)[:100])
            stats["errors"] += 1

    stats["total_txs"] = tx_count
    return stats
