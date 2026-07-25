"""
OilHybrid AI -- agent_brain_oil.py  (Arthur)
Claude AI brain for Brent crude spread betting decisions.
Called only after Lancelot pre-checks have passed.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic
import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

_ENV_PATH = BASE_DIR / ".env"
if _ENV_PATH.exists():
    load_dotenv(dotenv_path=_ENV_PATH)
else:
    load_dotenv()

log    = logging.getLogger("OilHybrid.Arthur")
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL      = "claude-sonnet-4-6"   # same model as the rest of the Blackpool suite
MAX_TOKENS = 2000

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Arthur, the AI trading brain for OilHybrid AI.
Your job is to analyse Oil (Brent Crude) market conditions and decide whether to
ENTER_LONG, ENTER_SHORT, HOLD an existing position, EXIT, or STAY_OUT.

PHILOSOPHY -- BIDIRECTIONAL, GEOPOLITICS-AWARE
OilHybrid is a bidirectional trend-following system trading Brent Crude (BZ) via
Capital.com spread betting. The daily SSL alone sets the direction each session:
LONG in an uptrend (Brent above its 200MA, supply risk), SHORT in a confirmed
downtrend. SHORTs take the SAME confidence bar, pre-checks and sizing as LONGs
(24 Jul 2026: no Morgan SHORT gate, no direction preference). Oil is geopolitically
sensitive -- Guinevere sentiment is critically important here. Spread-bet profits are
TAX FREE in the UK. Intraday only -- force close 20:45 UTC, never hold overnight.

DIRECTION AWARENESS (current regime is given in the market data below)
The daily SSL sets the direction symmetrically -- assess LONG and SHORT with EQUAL
weight (24 Jul 2026: no Morgan SHORT gate, no direction preference).
- Daily SSL BULL  -> look for LONG setups (uptrend).
- Daily SSL BEAR  -> look for SHORT setups (downtrend).
SHORTs take the SAME confidence bar, pre-checks and sizing as LONGs. The SSL alignment
tells you the direction; you assess QUALITY, not direction preference.

RISK PARAMETERS
Stop = 1.5 points ($1.50/bbl). Target = 3 points ($3.00/bbl). Stake = £13.33/pt. R:R = 2:1.
Brent barely moves 0.20pt in 30 minutes (median), so a 1.5pt stop gives ample room for
normal noise (backtest: 2.0%% whipsaw). These are TIGHT parameters -- every entry must have
strong confirmation across the timeframes; do not enter marginal setups.

GUINEVERE AWARENESS (CRITICAL FOR OIL -- current sentiment is given below)
Guinevere is particularly valuable for OilHybrid. Geopolitical news -- Strait of Hormuz
tension, Iran sanctions, OPEC+ decisions, pipeline attacks -- is the primary driver of
Brent moves. A BULLISH Guinevere score (supply disruption, OPEC cuts, Hormuz risk) adds
significant conviction to LONG entries -- all four of OilHybrid's live winning entries had
BULLISH Guinevere. A BEARISH score (inventory builds, demand destruction, recession fears)
adds conviction to SHORTs. Reference the current Guinevere sentiment in your reasoning.

EIA AWARENESS
EIA Petroleum Status Report: every Wednesday ~15:30 UTC. Hard block on NEW entries during
that window -- Lancelot enforces it automatically. If already in a position, hold through
EIA unless the stop triggers naturally.

POINT CONVENTION
1 point = $1.00 per barrel (USD/bbl). Stop = 1.5 points = $1.50/bbl. Target = 3 points =
$3.00/bbl. Stake = £13.33/pt. Never scale, multiply or divide by any factor.

PROFIT LADDER (active -- reference its status in HOLD reasoning)
  Step 1: floating profit >= £8  -> floor £6  guaranteed
  Step 2: floating profit >= £16 -> floor £13 guaranteed
  Step 3: floating profit >= £28 -> floor £24 guaranteed
With the tight 1.5pt stop, each ladder step is a significant fraction of the total target --
respect them. Once a rung locks, the position cannot close below that floor.

DIRECTION SYMMETRY (hard rule)
There is NO SHORT gate. SHORT and LONG are assessed on identical terms -- same
confidence bar, same pre-checks, same sizing. Do not add caution to a SHORT that you
would not add to the mirror-image LONG. Morgan confidence is context for BOTH
directions equally, not a SHORT-specific brake.

CORE IDENTITY / TIMEFRAMES
Three timeframes: daily (trend/direction), 1-hour (confirmation), 5-minute (entry).
Both LONG and SHORT are viable and assessed on identical terms. P&L is USD, converted to
GBP at the live GBPUSD rate (given below).

OIL MARKET CHARACTER
Oil moves on OPEC+ supply decisions, US shale output, global demand, weekly EIA inventories,
USD strength, and geopolitical risk. Supply shocks push crude UP; demand fears / oversupply
push it DOWN. Best trends form in the London and New York sessions.

LIQUIDITY PERIODS (UTC) -- you are told the current one each tick:
  ASIAN    (21:00-08:00): thinner, choppier -- higher conviction (Lancelot tightens RSI 60/40).
  LONDON   (08:00-13:00): good liquidity, trends often start.
  OVERLAP  (13:00-17:00): London/NY overlap -- most active.
  NEW_YORK (17:00-20:30): highest volume, strongest trends.
  CLOSING  (20:30-21:00): pre-close -- Lancelot blocks new entries.

INDICATOR HIERARCHY
TIER 1: daily SSL (direction), 1h SSL (must agree), 1h RSI (>55 bull / <45 bear; 60/40 Asian).
TIER 2: MACD histogram, TMO. TIER 3: Chande MO, Money Flow.
5-MINUTE ENTRY: last candle GREEN for LONG / RED for SHORT; 5m TMO > +0.3 LONG / < -0.3 SHORT.
Lancelot now also requires the 5m SSL to agree with the direction.

SELF PERFORMANCE AWARENESS (Morgan) -- CONTEXT ONLY
Morgan confidence is context; it does NOT change your entry threshold. Assess setups
the SAME way at any Morgan score of 30 or above -- do NOT raise the bar or demand
"exceptional" setups when Morgan is low. Below 30 the SYSTEM (not you) hard-blocks new
entries automatically and Gaius intervenes, so you will not be asked to enter there.

DECISION DISCIPLINE -- DISCRIMINATE, DO NOT DEFAULT TO CAUTION
Your job is to DISCRIMINATE between good and poor setups -- not to default to caution. A
clean setup deserves a HIGH confidence score and a trade; a poor setup a LOW score and a
stay-out. Both are equally valid. Capital preservation comes from ACCURATE ASSESSMENT, not
from systematically avoiding trades.

CONFIDENCE CALIBRATION (your score MUST discriminate):
  65-80 = clean 6/6 setup (Daily+1h+5m SSL aligned + momentum TMO/MACD with direction +
          RSI confirming + Money Flow/Chande aligned) -> trade with conviction.
  40-60 = most agree, 1-2 mixed -> merit + caution.
  20-39 = significantly mixed/conflicting -> stay-out likely correct.
  <20   = substantial disagreement -> no trade.
  A 35 on a clean 6/6 setup is WRONG; a 35 on a mixed setup is right. Force above 60 when
  all indicators agree.
  OIL-SPECIFIC: Oil moves develop slowly; extended price is risky. A clean setup is all SSL
  aligned + price within ~$2.50 of the session open (NOT extended) + momentum confirming =
  65-75. Extended >$2.50 from open, or mixed momentum = 30-45.

HARD RULES -- NEVER VIOLATE
1.  Check the daily SSL + regime first -- it sets the direction today (BULL->LONG, BEAR->SHORT).
2.  1h AND 5m SSL must agree with the intended direction before any entry.
3.  Assess LONG and SHORT on identical terms -- no SHORT gate, no direction preference.
4.  Never enter within 30 min of NFP/Fed/CPI, nor the first 15 min of NY open; hold through EIA.
5.  Never hold overnight -- force close by 20:45 UTC; no new entries after 20:30 UTC.
6.  Tight 1.5pt stop -- every entry needs strong confirmation; do NOT exit on ordinary noise.
7.  Factor Guinevere sentiment into conviction (geopolitics drives oil).
8.  Morgan is context only -- do NOT raise your entry bar at low Morgan (>=30). The
    system hard-blocks new entries below 30 on its own.

REQUIRED OUTPUT -- valid JSON only. No markdown, no preamble.
{
  "decision": "ENTER_LONG | ENTER_SHORT | HOLD | EXIT | STAY_OUT",
  "confidence": 0-100,
  "liquidity_bias": "ASIAN_CAUTION | LONDON_ACTIVE | NY_TRENDING | OVERLAP_OPTIMAL | CLOSING_AVOID",
  "reasoning": "2-4 sentences explaining your decision",
  "warnings": ["list of concerns"],
  "checklist": {
    "trend_aligned": true,
    "momentum_confirmed": true,
    "liquidity_good": true,
    "calendar_clear": true,
    "not_near_close": true,
    "high_conviction": true
  },
  "calendar_assessment": "brief comment on upcoming oil events",
  "liquidity_assessment": "brief comment on the current session"
}"""


# ── Format indicators for Arthur ──────────────────────────────────────────────

def _regime_block(bar_1d, proposed_direction, morgan_confidence, liquidity_period) -> str:
    """Live regime / Guinevere block for Arthur (bidirectional, no SHORT gate 24 Jul)."""
    ssl_1d = "BULL" if (bar_1d is not None and bar_1d.get("ssl_bull")) else \
             ("BEAR" if bar_1d is not None else "N/A")
    mc = 50.0 if morgan_confidence is None else float(morgan_confidence)
    direction = proposed_direction or "BOTH"
    guin = "unavailable"
    macro_line = "Global macro sentiment: NEUTRAL (set n/a UTC). no adjustment for this system."
    try:
        import guinevere_news
        g = guinevere_news.fetch_oil_sentiment()
        guin = f"{g.get('sentiment', 'NEUTRAL')} (score {g.get('score')})"
        macro_line = guinevere_news.get_macro_context()   # Part 4
    except Exception:
        pass
    return (
        "REGIME (current)\n"
        f"  Daily SSL:         {ssl_1d}\n"
        f"  Regime direction:  {direction}   (what to look for this session)\n"
        f"  Morgan confidence: {mc:.1f}/100   (context for BOTH directions equally)\n"
        f"  Direction rule:    symmetric -- LONG and SHORT on identical terms, no SHORT gate\n"
        f"  Guinevere (oil):   {guin}   (geopolitics drives Brent -- factor into conviction)\n"
        f"  Macro overlay:     {macro_line}\n"
        f"  Session:           {liquidity_period}"
    )


def _format_indicators(bar_1d, bar_1h, bar_5m, current_price, liquidity_period,
                       gbpusd_rate, current_trade=None,
                       calendar_context=None, perf_context=None,
                       morgan_confidence=None, proposed_direction=None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    regime_block = _regime_block(bar_1d, proposed_direction, morgan_confidence, liquidity_period)

    def _f(v, dp=2):
        if v is None or pd.isna(v):
            return "N/A"
        return f"{float(v):.{dp}f}"

    candle_colour = "GREEN" if bar_5m.get("close", 0) >= bar_5m.get("open", 0) else "RED"
    ssl_1d = "BULL" if (bar_1d is not None and bar_1d.get("ssl_bull")) else ("BEAR" if bar_1d is not None else "N/A")
    ssl_1h = "BULL" if bar_1h.get("ssl_bull") else "BEAR"
    ssl_5m = "BULL" if bar_5m.get("ssl_bull") else "BEAR"

    position_text = "None -- no open position"
    if current_trade is not None:
        pts = (current_price - current_trade.entry_price) if current_trade.direction == "LONG" \
              else (current_trade.entry_price - current_price)
        position_text = (
            f"OPEN {current_trade.direction} | entry=${current_trade.entry_price:,.2f} | "
            f"current=${current_price:,.2f} | pts_from_entry={pts:+.1f} | "
            f"stop=${current_trade.stop_loss:,.2f} | target=${current_trade.take_profit:,.2f} | "
            f"size={current_trade.size_oz:.2f}oz | stake=£{current_trade.stake:.4f}/pt | "
            f"{current_trade.liquidity_period}"
        )
        _ls = getattr(current_trade, "ladder_step", 0) or 0
        if _ls > 0:
            position_text += (
                f" | PROFIT LADDER ACTIVE: floor locked at £"
                f"{getattr(current_trade, 'ladder_floor_gbp', 0.0):.2f} (step {_ls}). "
                f"Position cannot close below this floor unless a gap event occurs -- "
                f"factor this into your HOLD reasoning.")

    return f"""Please analyse the current Oil (Brent Crude) market conditions.

TIME AND PRICE
  Time (UTC):        {now}
  Liquidity Period:  {liquidity_period}
  Oil (Brent/USD):    ${current_price:,.2f} per barrel
  GBPUSD rate:       {gbpusd_rate:.4f}  (for USD->GBP P&L conversion)

{regime_block}

DAILY CHART (Trend Direction -- sets allowed direction for today)
  SSL Cloud:        {ssl_1d}
  RSI (14):         {_f(bar_1d.get('rsi') if bar_1d is not None else None, 1)}
  TMO Main:         {_f(bar_1d.get('tmo_main') if bar_1d is not None else None, 3)}
  Chande MO (20):   {_f(bar_1d.get('chande_mo') if bar_1d is not None else None, 1)}

1-HOUR CHART (Trend Confirmation)
  SSL Cloud:        {ssl_1h}
  RSI (14):         {_f(bar_1h.get('rsi'), 1)}
  MACD Histogram:   {_f(bar_1h.get('macd_histogram'), 3)}
  TMO Main:         {_f(bar_1h.get('tmo_main'), 3)}
  TMO Smooth:       {_f(bar_1h.get('tmo_smooth'), 3)}
  Chande MO (20):   {_f(bar_1h.get('chande_mo'), 1)}
  Money Flow (14):  {_f(bar_1h.get('money_flow'), 2)}

5-MINUTE CHART (Entry Timing)
  SSL Cloud:        {ssl_5m}
  RSI (14):         {_f(bar_5m.get('rsi'), 1)}
  MACD Histogram:   {_f(bar_5m.get('macd_histogram'), 3)}
  TMO Main:         {_f(bar_5m.get('tmo_main'), 3)}
  TMO Smooth:       {_f(bar_5m.get('tmo_smooth'), 3)}
  Chande MO (20):   {_f(bar_5m.get('chande_mo'), 1)}
  Money Flow (14):  {_f(bar_5m.get('money_flow'), 2)}
  Last Candle:      {candle_colour} (close={_f(bar_5m.get('close'), 2)} open={_f(bar_5m.get('open'), 2)})

CURRENT POSITION
  {position_text}

{calendar_context if calendar_context else 'OIL ECONOMIC CALENDAR\n  No calendar data available.'}

{perf_context if perf_context else 'SELF PERFORMANCE AWARENESS\n  No performance data yet -- first trading session.'}

Please provide your analysis and trading decision in the required JSON format."""


# ── Main decision function ────────────────────────────────────────────────────

def get_trading_decision(bar_1h, bar_5m, current_price, liquidity_period,
                         bar_1d=None, current_trade=None,
                         calendar_context=None, perf_context=None,
                         gbpusd_rate: float = 1.27,
                         morgan_confidence=None, proposed_direction=None) -> dict:
    """
    Send indicator data to Arthur (Claude) and receive a trading decision.
    Only call this AFTER Lancelot pre-checks have passed.
    """
    log.info("Sending indicators to Arthur...")

    user_message = _format_indicators(
        bar_1d, bar_1h, bar_5m, current_price, liquidity_period,
        gbpusd_rate, current_trade, calendar_context, perf_context,
        morgan_confidence, proposed_direction,
    )

    for attempt in range(2):
        try:
            response = client.messages.create(
                model      = MODEL,
                max_tokens = MAX_TOKENS,
                system     = SYSTEM_PROMPT,
                messages   = [{"role": "user", "content": user_message}],
            )
            if response.stop_reason == "max_tokens":
                log.warning("Arthur hit max_tokens -- JSON may be truncated")

            raw_text = response.content[0].text.strip()
            if raw_text.startswith("```"):
                raw_text = "\n".join(l for l in raw_text.split("\n")
                                     if not l.strip().startswith("```")).strip()
            try:
                decision = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                log.error("Arthur returned invalid JSON (attempt %d/2): %s", attempt + 1, exc)
                if attempt == 0:
                    continue
                return _safe_stay_out("Arthur returned invalid JSON -- staying out for safety")

            decision["timestamp"]        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            decision["tokens_used"]      = response.usage.input_tokens + response.usage.output_tokens
            decision["current_price"]    = current_price
            decision["liquidity_period"] = liquidity_period
            decision["gbpusd_rate"]      = gbpusd_rate

            log.info("Arthur decision: %s | confidence=%s | tokens=%d",
                     decision.get("decision"), decision.get("confidence"),
                     decision.get("tokens_used", 0))
            return decision

        except anthropic.APIError as exc:
            log.error("Anthropic API error: %s", exc)
            return _safe_stay_out(f"API error: {str(exc)}")
        except Exception as exc:
            log.error("Unexpected error calling Arthur: %s", exc)
            return _safe_stay_out(f"Unexpected error: {str(exc)}")

    return _safe_stay_out("Arthur failed after all attempts")


def _safe_stay_out(reason: str) -> dict:
    return {
        "decision":             "STAY_OUT",
        "confidence":           0,
        "liquidity_bias":       "ASIAN_CAUTION",
        "reasoning":            reason,
        "warnings":             [reason],
        "checklist":            {},
        "calendar_assessment":  "",
        "liquidity_assessment": "",
        "timestamp":            datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tokens_used":          0,
    }


def format_decision_for_display(decision: dict) -> str:
    """Format Arthur's decision for terminal display."""
    d         = decision.get("decision", "UNKNOWN")
    conf      = decision.get("confidence", "--")
    bias      = decision.get("liquidity_bias", "--")
    reasoning = decision.get("reasoning", "No reasoning")
    warnings  = decision.get("warnings", [])
    tokens    = decision.get("tokens_used", 0)
    ts        = decision.get("timestamp", "")
    price     = decision.get("current_price", 0) or 0
    lines = [
        "=" * 60,
        "  OilHybrid AI -- Arthur's Decision",
        f"  {ts}",
        "=" * 60,
        f"  Decision:        {d}",
        f"  Confidence:      {conf}/100",
        f"  Liquidity Bias:  {bias}",
        f"  Oil Price:      ${price:,.2f}",
        f"  Liquidity:       {decision.get('liquidity_period', '--')}",
        "",
        "  Reasoning:",
        f"  {reasoning}",
        "",
    ]
    if warnings:
        lines.append("  Warnings:")
        for w in warnings:
            lines.append(f"    - {w}")
        lines.append("")
    if decision.get("calendar_assessment"):
        lines.append(f"  Calendar:  {decision.get('calendar_assessment')}")
    if decision.get("liquidity_assessment"):
        lines.append(f"  Liquidity: {decision.get('liquidity_assessment')}")
    cl = decision.get("checklist", {})
    if cl:
        lines.append("  Checklist:")
        for k, v in cl.items():
            lines.append(f"    [{'PASS' if v else 'FAIL'}] {k.replace('_', ' ').title()}")
    lines.append(f"  Tokens used: {tokens}")
    lines.append("=" * 60)
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("Arthur self-test -- calling Claude with a bullish Oil setup...")
    bar_1d = pd.Series({"ssl_bull": True, "rsi": 58.0, "tmo_main": 1.5, "chande_mo": 25.0})
    bar_1h = pd.Series({"ssl_bull": True, "rsi": 62.0, "macd_histogram": 8.5,
                        "tmo_main": 2.1, "tmo_smooth": 1.5, "chande_mo": 45.0, "money_flow": 150.0})
    bar_5m = pd.Series({"ssl_bull": True, "rsi": 58.0, "macd_histogram": 2.5,
                        "tmo_main": 0.8, "tmo_smooth": 0.5, "chande_mo": 30.0, "money_flow": 80.0,
                        "open": 4150.0, "close": 4160.0})
    decision = get_trading_decision(
        bar_1h=bar_1h, bar_5m=bar_5m, current_price=4160.0,
        liquidity_period="OVERLAP", bar_1d=bar_1d, gbpusd_rate=1.3376,
    )
    print(format_decision_for_display(decision))
    log.info("Arthur self-test complete.")
