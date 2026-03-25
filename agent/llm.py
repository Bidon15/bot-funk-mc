"""LLM decision engine — uses Minimax via Anthropic-compatible API."""

from __future__ import annotations

import json
import logging
import os

from anthropic import Anthropic

log = logging.getLogger(__name__)


def _extract_text(resp) -> str:
    """Extract text from LLM response, skipping thinking blocks (Minimax extended thinking)."""
    for block in resp.content:
        # Skip ThinkingBlock / thinking content
        block_type = getattr(block, "type", None)
        if block_type == "thinking":
            continue
        if hasattr(block, "text"):
            return block.text.strip()
        if isinstance(block, dict):
            if block.get("type") == "thinking":
                continue
            if "text" in block:
                return block["text"].strip()
    # Fallback: stringify the whole response
    log.warning("No text block found in LLM response, content types: %s",
                [getattr(b, "type", type(b).__name__) for b in resp.content])
    return str(resp.content[-1]).strip()

SYSTEM_PROMPT = """\
You are an autonomous trading agent on bot.fun, an onchain memecoin marketplace on Eden testnet.
You trade against bonding curves using TIA (testnet currency). Your goal: trade profitably, \
create interesting coins, and be the most vocal and entertaining presence on the platform.

## Personality
You are opinionated, bold, and love to stir conversation. You have strong takes on coins \
and aren't afraid to shill your bags or call out weak narratives. You engage with what other \
agents are doing — agree, disagree, build on their narratives, or counter-trade them.

## Rules
- Be concise. Return ONLY valid JSON matching the requested schema.
- Never risk more than the budget given in the context.
- ALWAYS include at least 1-2 "post" actions per cycle to coins you hold. Shill them! \
  Talk about why the narrative is strong, hype upcoming catalysts, react to other agents' moves.
- When you see other agents' recent activity, RESPOND to it. Debate their picks. \
  If they bought something you hold, amplify it. If they're in a rival coin, trash-talk it playfully.
- Vary your posting style: bullish calls, hot takes, narrative threads, agent callouts, \
  memes-in-text, market commentary. Never repeat the same message twice.
- Early entries on new/trending coins can be profitable — be aggressive on entries.
- Consider price impact before trading — skip if > 5%.
- When launching coins, pick creative names/symbols and compelling descriptions.
- Post messages should be punchy, 1-2 sentences max. Think crypto twitter energy.
"""


def _get_client() -> Anthropic:
    return Anthropic(
        api_key=os.environ["MINIMAX_API_KEY"],
        base_url=os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
    )


def _get_model() -> str:
    return os.environ.get("MINIMAX_MODEL", "minimax-01")


def decide_actions(market_snapshot: dict) -> list[dict]:
    """Ask the LLM to decide what trading actions to take.

    Returns a list of action dicts, e.g.:
      [{"action": "buy", "coin": "0x...", "tia_amount": "1000000000000000000", "message": "..."},
       {"action": "sell", "coin": "0x...", "token_amount": "...", "message": "..."},
       {"action": "launch", "name": "...", "symbol": "...", "description": "...", "svg": "...", "value": "..."},
       {"action": "post", "coin": "0x...", "message": "..."},
       {"action": "skip"}]
    """
    from . import server

    client = _get_client()

    # Inject live operator instructions if any
    instructions = server.get_instructions()
    operator_block = ""
    if instructions:
        lines = "\n".join(f"- {i}" for i in instructions)
        operator_block = f"\n\n## OPERATOR INSTRUCTIONS (follow these closely):\n{lines}\n"

    user_msg = f"""\
Here is the current market snapshot. Decide what actions to take.
{operator_block}
{json.dumps(market_snapshot, indent=2)}

Respond with a JSON array of actions. Each action is an object with an "action" field.
Valid actions:
- {{"action": "buy", "coin": "<address>", "tia_amount": "<wei>", "message": "<optional trade message>"}}
- {{"action": "sell", "coin": "<address>", "token_amount": "<wei>", "message": "<optional trade message>"}}
- {{"action": "launch", "name": "<name>", "symbol": "<SYMBOL>", "description": "<desc>", "svg": "<svg markup>", "value": "<initial buy in wei>"}}
- {{"action": "post", "coin": "<address>", "message": "<message>"}}
- {{"action": "skip"}}

Return ONLY the JSON array, no markdown fences or explanation."""

    resp = client.messages.create(
        model=_get_model(),
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _extract_text(resp)
    log.debug("Raw LLM response: %s", text[:500])
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        actions = json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON, skipping cycle: %s", text[:200])
        return [{"action": "skip"}]

    if isinstance(actions, dict):
        actions = [actions]

    return actions


def generate_coin_idea() -> dict | None:
    """Ask the LLM to come up with a creative coin to launch.

    Returns {"name": ..., "symbol": ..., "description": ..., "svg": ..., "value": ...} or None.
    """
    client = _get_client()

    user_msg = """\
Come up with a creative memecoin to launch on bot.fun. It should be fun, \
distinctive, and have an interesting concept that other agents and humans would want to trade.

Return a single JSON object:
{"name": "<name>", "symbol": "<SYMBOL 3-6 chars>", "description": "<compelling description>", "svg": "<svg art under 32KB, must include xmlns>", "value": "2000000000000000000"}

The SVG should be creative — use gradients, paths, shapes, CSS animations. Make it visually distinctive.
Return ONLY the JSON, no markdown fences."""

    resp = client.messages.create(
        model=_get_model(),
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = _extract_text(resp)
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("LLM returned invalid JSON for coin idea: %s", text[:200])
        return None
