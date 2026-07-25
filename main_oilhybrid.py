"""
OilHybrid AI -- main_oilhybrid.py
Brent crude (Brent Crude) spread betting main loop. Runs 24/7 Mon-Fri.
Never holds overnight -- force close at 20:45 UTC, before the 21:00 daily close.

PAPER_TRADING_MODE = True until the demo account is verified.
"""

import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────

PAPER_TRADING_MODE = True
VERSION            = "1.4.0"
# BIDIRECTIONAL (Nick's direct order, 24 Jul 2026): the Morgan SHORT gate has been
# removed. SHORTs take the SAME confidence bar and pre-checks as LONGs -- the daily
# SSL alone sets direction (BULL -> LONG, BEAR -> SHORT). No direction asymmetry.
CANDLE_INTERVAL    = 300      # 5-minute candle loop (seconds)
POSITION_INTERVAL  = 30       # position monitoring (seconds)
HEARTBEAT_INTERVAL = 240      # liveness log at least this often, even when idle
DASHBOARD_INTERVAL = 15       # push live top-line state this often, in all periods
BASE_DIR           = Path(__file__).resolve().parent
LOG_DIR            = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
SHUTDOWN_FLAG      = LOG_DIR / "shutdown.flag"
LIFT_FLAG          = LOG_DIR / "confidence_lift.json"   # manual Morgan confidence lift (live)
DASHBOARD_URL      = "http://localhost:5045/api/update"

# ── Env / logging setup ───────────────────────────────────────────────────────

_ENV_PATH = BASE_DIR / ".env"
# Capital.com / Anthropic credentials: prefer this system's own .env, then the
# template original's .env, then a known-good sibling (all Albion systems share the
# one Capital.com demo account). Fixes the yfinance fallback when a freshly-cloned
# hybrid has no own .env -- TideTraderAI/.env carries only Kraken keys, no CAPITALCOM_.
_ENV_CANDIDATES = [
    _ENV_PATH,
    BASE_DIR.parent / "OilTraderAI" / ".env",
    BASE_DIR.parent / "USTraderAI" / ".env",
    BASE_DIR.parent / "GoldTraderAI" / ".env",
]
for _cand in _ENV_CANDIDATES:
    if _cand.exists():
        load_dotenv(dotenv_path=_cand)
        break
else:
    load_dotenv()

# ─── ALBION STANDING RULE: ALL LOG TIMESTAMPS ARE UTC ────────────────────────
# Force Python's logging to emit %(asctime)s in UTC, not BST/local. Without this
# line, logging defaults to local time and every log line is +1h vs the UTC CSV
# artefacts (phantom_trades.csv etc.) — the exact BST/UTC mismatch that caused a
# misread on 11 Jul 2026. Never interpret an Albion log timestamp as local time;
# confirm UTC before analysing. (Baked in per Nick's directive, 12 Jul 2026.)
logging.Formatter.converter = time.gmtime
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-24s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S UTC",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "oilhybrid.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("OilHybrid.Main")

# ── Internal imports ──────────────────────────────────────────────────────────

import phantom_tracker
import performance_oil
import guinevere_news
from agent_brain_oil    import get_trading_decision, format_decision_for_display
from calendar_oil       import check_calendar, is_hard_blocked, get_calendar_context
from data_feed_oil      import (
    OilDataFeed, OIL_EPIC, is_market_open, get_liquidity_period,
    minutes_until_next_open, liquidity_note,
)
from capitalcom_connector import CapitalComConnector
from notifier_oil       import (
    notify_system_startup, notify_system_shutdown,
    notify_trade_opened, notify_trade_closed_win, notify_trade_closed_loss,
    notify_kill_switch_triggered, notify_kill_switch_reset,
    notify_daily_summary, notify_system_error,
)
from paper_trader_oil   import PaperTraderOil
from performance_oil    import (
    get_performance_context, get_perf_dashboard_dict, invalidate_cache,
    generate_milestone_review,
)
from pre_checks_oil     import (
    run_all_pre_checks, run_individual_pre_checks, check_kill_switch_reset,
    EXTENDED_LIMIT,
)
from strategy_oil       import should_force_close, get_gbpusd_rate, TRAILING_STOP_POINTS

# ── Graceful shutdown ─────────────────────────────────────────────────────────

_SHUTDOWN = False


def _handle_signal(sig, frame):
    global _SHUTDOWN
    log.info("Shutdown signal received (%s)", sig)
    _SHUTDOWN = True


signal.signal(signal.SIGINT,  _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Account state ─────────────────────────────────────────────────────────────

class AccountState:
    """Holds live trading account state passed to pre-checks."""

    def __init__(self, capital: float) -> None:
        self.capital_gbp        = capital
        self.daily_pnl_gbp      = 0.0
        self.consecutive_losses = 0
        self.last_loss_time     = None
        self.kill_switch_active = False
        self.kill_switch_tier   = 0
        self.kill_switch_until  = None
        self.kill_switch_reason = ""
        self.kill_history       = []

    def record_trade(self, pnl_gbp: float) -> None:
        self.daily_pnl_gbp += pnl_gbp
        self.capital_gbp = round(self.capital_gbp + pnl_gbp, 2)
        if pnl_gbp < 0:
            self.consecutive_losses += 1
            self.last_loss_time = datetime.now(timezone.utc)
        else:
            self.consecutive_losses = 0

    def reset_daily(self) -> None:
        self.daily_pnl_gbp = 0.0


# ── Dashboard push ────────────────────────────────────────────────────────────

_dash_first_ok:   bool  = False
_dash_fail_count: int   = 0
_dash_last_warn:  float = 0.0


def _dashboard_push_ok(kind, period, price, status, http) -> None:
    global _dash_first_ok
    if not _dash_first_ok:
        _dash_first_ok = True
        log.info("Dashboard connected -- first %s push OK | period=%s oil=$%.2f status=%s HTTP %s",
                 kind, period, price, status, http)
    else:
        log.debug("Dashboard %s push | period=%s oil=$%.2f status=%s HTTP %s",
                  kind, period, price, status, http)


def _dashboard_push_warn(exc) -> None:
    global _dash_fail_count, _dash_last_warn
    _dash_fail_count += 1
    now = time.monotonic()
    if now - _dash_last_warn > 60:
        log.warning("Dashboard push failing (%d so far): %s -- is dashboard_oil.py running on :5045?",
                    _dash_fail_count, exc)
        _dash_last_warn = now


def _safe_float(v):
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _indicator_snapshot(bar) -> dict:
    if bar is None:
        return {}
    return {
        "ssl_bull":   bool(bar.get("ssl_bull", False)),
        "rsi":        _safe_float(bar.get("rsi")),
        "macd":       _safe_float(bar.get("macd")),
        "tmo_main":   _safe_float(bar.get("tmo_main")),
        "chande_mo":  _safe_float(bar.get("chande_mo")),
        "money_flow": _safe_float(bar.get("money_flow")),
    }


def _ssl_label(ind: dict) -> str:
    """BULL / BEAR / -- from an indicator snapshot's ssl_bull flag."""
    if not ind or "ssl_bull" not in ind:
        return "--"
    return "BULL" if ind["ssl_bull"] else "BEAR"


def _fmt_ind(v) -> str:
    """2dp string for a numeric indicator, or '' if unavailable."""
    return "" if v is None else f"{float(v):.2f}"


def _build_exit_meta(ind_1d: dict, ind_1h: dict, ind_5m: dict, decision: dict) -> dict:
    """Indicator snapshot + Arthur's exit-decision confidence for an ARTHUR_EXIT
    (Gaius Commission 012). Scalars are taken from the 1h snapshot (the confirmation
    timeframe). Best-effort -- returns None on any error so a logging failure never
    blocks a trade close."""
    try:
        ind_1h = ind_1h or {}
        conf = decision.get("confidence") if decision else None
        return {
            "exit_daily_ssl":  _ssl_label(ind_1d),
            "exit_1h_ssl":     _ssl_label(ind_1h),
            "exit_5m_ssl":     _ssl_label(ind_5m),
            "exit_tmo":        _fmt_ind(ind_1h.get("tmo_main")),
            "exit_money_flow": _fmt_ind(ind_1h.get("money_flow")),
            "exit_rsi":        _fmt_ind(ind_1h.get("rsi")),
            "exit_chande_mo":  _fmt_ind(ind_1h.get("chande_mo")),
            "exit_confidence": "" if conf is None else str(conf),
        }
    except Exception:
        return None


def _serialise_trade(t):
    if t is None:
        return None
    return {
        "direction":        t.direction,
        "entry_price":      t.entry_price,
        "exit_price":       t.exit_price,
        "stop_loss":        t.stop_loss,
        "take_profit":      t.take_profit,
        "ladder_step":      getattr(t, "ladder_step", 0),
        "ladder_floor_gbp": getattr(t, "ladder_floor_gbp", 0.0),
        "stake":            t.stake,
        "size_oz":          t.size_oz,
        "pnl_usd":          t.pnl_usd,
        "pnl_gbp":          t.pnl_gbp,
        "gbpusd_rate":      getattr(t, "gbpusd_exit", None) or getattr(t, "gbpusd_entry", None),
        "liquidity_period": t.liquidity_period,
        "entry_time":       t.entry_time.isoformat() if t.entry_time else None,
    }


def _post(payload, kind, period, price, status) -> None:
    try:
        import requests
        resp = requests.post(DASHBOARD_URL, data=json.dumps(payload, default=str),
                             headers={"Content-Type": "application/json"}, timeout=2)
        _dashboard_push_ok(kind, period, price, status, resp.status_code)
    except Exception as exc:
        _dashboard_push_warn(exc)


def _push_dashboard_live(stanley, account, ig, feed, now_utc) -> None:
    """Lightweight, frequent push of always-known top-line state (all periods)."""
    period = get_liquidity_period(now_utc)
    price  = _get_price(ig, feed)
    gbpusd = get_gbpusd_rate(ig)
    connector_status = "capitalcom" if (ig is not None and ig.connected) else "yahoo"
    payload = {
        "mode":             "PAPER" if PAPER_TRADING_MODE else "LIVE",
        "version":          VERSION,
        "liquidity_period": period,
        "oil_price_usd":   price,
        "connector_status": connector_status,
        "capital":          stanley.capital_gbp,
        "daily_pnl":        account.daily_pnl_gbp,
        "total_trades":     stanley.total_trades,
        "win_rate":         stanley.win_rate,
        "in_trade":         stanley.in_trade,
        "current_trade":    _serialise_trade(stanley.current_trade),
        "gbpusd_rate":      gbpusd,
        "kill_switch":      account.kill_switch_active,
        "kill_tier":        account.kill_switch_tier,
        "perf":             get_perf_dashboard_dict(),   # keep confidence exposed in ALL market states
        "updated_at":       now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    _post(payload, "live", period, price, connector_status)


def _push_dashboard(stanley, account, ig, price, gbpusd, period, *,
                    decision=None, pre_checks=None, calendar_summary="",
                    connector_status="yahoo", panel_mode="pre_checks",
                    trend_1d="NEUTRAL", trend_1h="NEUTRAL", signal_5m="NEUTRAL",
                    indicators_1d=None, indicators_1h=None, indicators_5m=None) -> None:
    """Full push with decision / pre-checks / indicators (on candle ticks)."""
    perf = get_perf_dashboard_dict()
    payload = {
        "mode":             "PAPER" if PAPER_TRADING_MODE else "LIVE",
        "version":          VERSION,
        "liquidity_period": period,
        "oil_price_usd":   price,
        "connector_status": connector_status,
        "capital":          stanley.capital_gbp,
        "daily_pnl":        account.daily_pnl_gbp,
        "total_trades":     stanley.total_trades,
        "win_rate":         stanley.win_rate,
        "in_trade":         stanley.in_trade,
        "current_trade":    _serialise_trade(stanley.current_trade),
        "decision":         decision,
        "panel_mode":       panel_mode,
        "checklist":        (decision or {}).get("checklist", {}),
        "pre_checks":       pre_checks,
        "trend_1d":         trend_1d,
        "trend_1h":         trend_1h,
        "signal_5m":        signal_5m,
        "indicators_1d":    indicators_1d or {},
        "indicators_1h":    indicators_1h or {},
        "indicators_5m":    indicators_5m or {},
        "perf":             perf,
        "calendar":         calendar_summary,
        "gbpusd_rate":      gbpusd,
        "kill_switch":      account.kill_switch_active,
        "kill_tier":        account.kill_switch_tier,
        "session_open":     _session_open["price"],
        "extension":        (round(price - _session_open["price"], 2)
                             if (price is not None and _session_open["price"] is not None) else None),
        "extended_limit":   EXTENDED_LIMIT,
        "updated_at":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    _post(payload, "full", period, price, connector_status)


# ── Price / rate getters ──────────────────────────────────────────────────────

def _get_price(ig, feed) -> float:
    """Current Oil price in USD -- Capital.com first, yfinance fallback."""
    try:
        if ig is not None and ig.connected:
            pd_ = ig.get_price(OIL_EPIC)
            if pd_:
                b, a = pd_.get("bid"), pd_.get("ask")
                if b and a:
                    return round((float(b) + float(a)) / 2, 2)
                return float(pd_.get("mid", 0.0))
    except Exception:
        pass
    try:
        df = feed.get("5m")
        if df is not None and not df.empty:
            return round(float(df["close"].iloc[-1]), 2)
    except Exception:
        pass
    return 0.0


# ── Core candle tick ──────────────────────────────────────────────────────────

# OilHybrid extended-rally filter (Commission 008): track the Asian-session open price.
# The Oil session runs 22:00 UTC -> 21:00 UTC; the first valid price at/after 22:00 each
# day is the session open, held until the next 22:00. Extension = price - session open.
_session_open = {"day": None, "price": None}


def _session_day(now_utc):
    """Label the 22:00->21:00 UTC session by the calendar day it ENDS on."""
    return (now_utc.date() + timedelta(days=1)) if now_utc.hour >= 22 else now_utc.date()


def _update_session_open(now_utc, price):
    """Set the session-open price on the first tick of each new session; return it."""
    try:
        if price is None or float(price) != float(price):   # None / NaN
            return _session_open["price"]
    except (TypeError, ValueError):
        return _session_open["price"]
    sd = _session_day(now_utc)
    if sd != _session_open["day"]:
        _session_open["day"] = sd
        _session_open["price"] = round(float(price), 2)
        log.info("New Oil session %s -- session-open price set to $%.2f", sd, _session_open["price"])
    return _session_open["price"]


def run_candle_tick(feed, stanley, account, ig) -> None:
    now_utc = datetime.now(timezone.utc)
    period  = get_liquidity_period(now_utc)
    price   = _get_price(ig, feed)
    session_open_price = _update_session_open(now_utc, price)
    gbpusd  = get_gbpusd_rate(ig)
    connector_status = "capitalcom" if (ig is not None and ig.connected) else "yahoo"

    log.info("--- CANDLE TICK | %s | period=%s | OIL=$%.2f | GBPUSD=%.4f ---",
             now_utc.strftime("%H:%M:%S UTC"), period, price, gbpusd)

    # Gaius Commission 012: fill any ARTHUR_EXIT row's post-exit prices once 30/60 min
    # have elapsed (runs every tick, survives restarts, never raises).
    stanley.fill_post_exit_prices(price, now_utc)

    # Calendar hard block (Guinevere)
    hard_blocked, block_reason, event_name, mins_remain = is_hard_blocked(now_utc)
    cal_context = get_calendar_context(now_utc)
    cal_summary = check_calendar(now_utc).get("calendar_summary", "")

    if hard_blocked:
        log.warning("CALENDAR HARD BLOCK: %s (%d min)", block_reason, mins_remain)
        if not stanley.in_trade:
            _push_dashboard(stanley, account, ig, price, gbpusd, period,
                            calendar_summary=cal_summary, connector_status=connector_status)
            return

    # Refresh data
    try:
        feed.refresh()
    except Exception as exc:
        log.error("Data refresh failed: %s", exc)
        return

    try:
        bar_1d = feed.latest_bar("1d")
    except Exception:
        bar_1d = None
    try:
        bar_1h = feed.latest_bar("1h")
        bar_5m = feed.latest_bar("5m")
    except Exception:
        log.warning("Insufficient indicator data -- skipping tick")
        return

    perf_context = get_performance_context()

    sig_1h = feed.composite_signal("1h")
    sig_5m = feed.composite_signal("5m")
    trend_1d = "LONG" if (bar_1d is not None and bar_1d.get("ssl_bull")) else "SHORT"

    # ── Bidirectional regime direction (fully symmetric, 24 Jul 2026) ───────────
    # Daily SSL sets direction both ways: BULL -> LONG, BEAR -> SHORT. No Morgan gate
    # (Nick's direct order) -- SHORTs take the SAME confidence bar and pre-checks as
    # LONGs. Neutral/NaN daily -> the 1h signal decides. Morgan is still COMPUTED and
    # passed to Arthur as context, it just no longer gates or biases direction.
    _morgan = get_perf_dashboard_dict().get("confidence_score")
    _morgan = 50.0 if _morgan is None else float(_morgan)
    _ssl_1d = bar_1d.get("ssl_bull") if bar_1d is not None else None
    if _ssl_1d is None or (isinstance(_ssl_1d, float) and pd.isna(_ssl_1d)):
        proposed_direction = sig_1h if sig_1h in ("LONG", "SHORT") else "BOTH"   # neutral daily
    elif bool(_ssl_1d):                                   # BULL daily -> LONG
        proposed_direction = "LONG"
    else:                                                 # BEAR daily -> SHORT
        proposed_direction = "SHORT"

    ind_1d = _indicator_snapshot(bar_1d)
    ind_1h = _indicator_snapshot(bar_1h)
    ind_5m = _indicator_snapshot(bar_5m)

    checks = run_all_pre_checks(
        bar_1h=bar_1h, bar_5m=bar_5m, account=account,
        current_trade=stanley.current_trade, bar_1d=bar_1d,
        proposed_direction=proposed_direction, now_utc=now_utc,
        current_price=price, session_open_price=session_open_price,
    )
    individual_checks = run_individual_pre_checks(
        bar_1h=bar_1h, bar_5m=bar_5m, account=account,
        current_trade=stanley.current_trade, bar_1d=bar_1d,
        proposed_direction=proposed_direction, now_utc=now_utc,
        current_price=price, session_open_price=session_open_price,
    )

    if not checks["passed"]:
        log.info("Pre-checks FAILED: %s", checks.get("reason"))
        _push_dashboard(stanley, account, ig, price, gbpusd, period,
                        pre_checks=individual_checks, calendar_summary=cal_summary,
                        connector_status=connector_status, panel_mode="pre_checks",
                        trend_1d=trend_1d, trend_1h=sig_1h, signal_5m=sig_5m,
                        indicators_1d=ind_1d, indicators_1h=ind_1h, indicators_5m=ind_5m)
        if checks.get("kill_switch_triggered"):
            account.kill_switch_active = True
            tier = checks.get("kill_tier", 1)
            account.kill_switch_tier = tier
            wait_hours = {1: 6, 2: 12}.get(tier, 24)
            notify_kill_switch_triggered(tier=tier, reason=checks.get("reason", ""),
                                         wait_hours=wait_hours, daily_pnl=account.daily_pnl_gbp,
                                         capital=stanley.capital_gbp)
        return

    # ── Zone-3 MORGAN HARD BLOCK (three-zone model, 24 Jul 2026, Nick's direct order) ──
    # Below 30, suspend NEW entries and let Gaius intervene. Existing open positions are
    # unaffected -- when in a trade we fall through so Arthur still manages HOLD/EXIT.
    # (Zone 2, 30-49, is WARNING only: trading continues, no code restriction here.)
    if not stanley.in_trade:
        _morgan_now = get_perf_dashboard_dict().get("confidence_score")
        if performance_oil.morgan_hard_block(50 if _morgan_now is None else _morgan_now):
            log.warning("MORGAN HARD BLOCK: confidence %s < 30 -- new entries suspended "
                        "(Gaius intervention active)", _morgan_now)
            _push_dashboard(stanley, account, ig, price, gbpusd, period,
                            pre_checks=individual_checks, calendar_summary=cal_summary,
                            connector_status=connector_status, panel_mode="pre_checks",
                            trend_1d=trend_1d, trend_1h=sig_1h, signal_5m=sig_5m,
                            indicators_1d=ind_1d, indicators_1h=ind_1h, indicators_5m=ind_5m)
            return

    # Call Arthur
    decision = get_trading_decision(
        bar_1h=bar_1h, bar_5m=bar_5m, current_price=price, liquidity_period=period,
        bar_1d=bar_1d, current_trade=stanley.current_trade,
        calendar_context=cal_context, perf_context=perf_context, gbpusd_rate=gbpusd,
        morgan_confidence=_morgan, proposed_direction=proposed_direction,
    )

    # Guinevere news -> Arthur confidence adjustment (soft, additive; never blocks).
    _action = decision.get("decision", "STAY_OUT")
    if _action in ("ENTER_LONG", "ENTER_SHORT"):
        _dir = "LONG" if _action == "ENTER_LONG" else "SHORT"
        try:
            _news_adj, _news_reason = guinevere_news.get_confidence_adjustment(_dir)
            _base = float(decision.get("confidence") or 0)
            decision["confidence"] = max(0, min(100, _base + _news_adj))
            decision["news_adjustment"] = _news_adj
            log.info(_news_reason)
        except Exception as _e:
            log.warning("Guinevere news adjustment failed: %s", _e)

    log.info(format_decision_for_display(decision))
    _push_dashboard(stanley, account, ig, price, gbpusd, period,
                    decision=decision, pre_checks=individual_checks, calendar_summary=cal_summary,
                    connector_status=connector_status, panel_mode="claude",
                    trend_1d=trend_1d, trend_1h=sig_1h, signal_5m=sig_5m,
                    indicators_1d=ind_1d, indicators_1h=ind_1h, indicators_5m=ind_5m)

    action = decision.get("decision", "STAY_OUT")
    if action == "ENTER_LONG" and not stanley.in_trade:
        _open_trade(stanley, account, ig, "LONG", price, period, gbpusd)
    elif action == "ENTER_SHORT" and not stanley.in_trade:
        _open_trade(stanley, account, ig, "SHORT", price, period, gbpusd)
    elif action == "EXIT" and stanley.in_trade:
        # Gaius Commission 012: capture the indicator snapshot + Arthur's exit confidence
        # so we can later judge whether the early exit was skill or premature.
        _emeta = _build_exit_meta(ind_1d, ind_1h, ind_5m, decision)
        _close_trade(stanley, account, ig, price, gbpusd, "ARTHUR_EXIT", exit_meta=_emeta)
    elif action == "HOLD" and stanley.in_trade:
        log.info("Arthur says HOLD -- maintaining position")
    elif action == "STAY_OUT":
        log.info("Arthur says STAY_OUT -- no action")
        try:
            _dir = proposed_direction if proposed_direction in ("LONG", "SHORT") else ("LONG" if (bar_1d and bar_1d.get("ssl_bull")) else "SHORT")
            try:
                # Guinevere sentiment score at signal time (System 5 Review, Change 4):
                # was never logged for Oil. Cached fetch (5-min) -- no extra API call.
                try:
                    _guin_score = guinevere_news.fetch_oil_sentiment().get("score")
                except Exception:
                    _guin_score = None
                _snap = phantom_tracker.build_snapshot(
                    ind_1d, ind_1h, ind_5m,
                    morgan_score=performance_oil.get_confidence(),
                    session=period,
                    guinevere_score=_guin_score,
                )
            except Exception as _se:
                log.warning("phantom indicator snapshot failed: %s", _se)
                _snap = None
            phantom_tracker.record_decision(
                market="OIL",
                direction_blocked=_dir,
                price_at_decision=price,
                confidence=decision.get("confidence"),
                reason_for_stay_out="ARTHUR_STAY_OUT",
                get_price_fn=lambda m: _get_price(ig, feed),
                indicators=_snap,
            )
        except Exception as _exc:
            log.warning("phantom_tracker record failed: %s", _exc)

    if stanley.total_trades > 0 and stanley.total_trades % 50 == 0:
        generate_milestone_review(LOG_DIR / "oil_trades.csv", stanley.total_trades // 50)


# ── Position monitoring ───────────────────────────────────────────────────────

def monitor_open_position(stanley, account, ig, feed) -> None:
    if not stanley.in_trade:
        return
    now_utc = datetime.now(timezone.utc)
    price   = _get_price(ig, feed)
    gbpusd  = get_gbpusd_rate(ig)

    if should_force_close(now_utc):
        log.warning("Force close window (20:45 UTC) -- closing all positions")
        _close_trade(stanley, account, ig, price, gbpusd, "FORCE_CLOSE_2045")
        return

    reason = stanley.monitor_trade(price, gbpusd)
    if reason:
        trade = stanley.trade_history[-1] if stanley.trade_history else None
        _handle_closed_trade(account, trade)
        log.info("Position auto-closed: %s | price=$%.2f", reason, price)
        invalidate_cache()


# ── Open / close helpers ──────────────────────────────────────────────────────

def _open_trade(stanley, account, ig, direction, price, period, gbpusd) -> None:
    trade = stanley.open_trade(direction, price, gbpusd, period)
    if PAPER_TRADING_MODE:
        log.info("[PAPER] OPEN %s | entry=$%.2f | size=%.2foz | stop=$%.2f | target=$%.2f",
                 direction, price, trade.size_oz, trade.stop_loss, trade.take_profit)
    else:
        try:
            ig.open_position(epic=OIL_EPIC, direction="BUY" if direction == "LONG" else "SELL",
                             size=trade.size_oz, stop_distance=trade.stop_pts)
            log.info("[LIVE] OPEN %s via Capital.com | entry=$%.2f", direction, price)
        except Exception as exc:
            log.error("Capital.com open_position failed: %s -- tracked paper only", exc)
            notify_system_error(f"Capital.com open failed: {exc}")
    notify_trade_opened(direction=direction, entry_price=price, stop_loss=trade.stop_loss,
                        take_profit=trade.take_profit, stake=trade.stake,
                        liquidity_period=period, size_oz=trade.size_oz)
    log.info("Trade opened: %s", trade.summary())


def _close_trade(stanley, account, ig, price, gbpusd, reason, exit_meta=None) -> None:
    trade = stanley.close_trade(price, reason, gbpusd, exit_meta=exit_meta)
    if trade is None:
        return
    _handle_closed_trade(account, trade)
    invalidate_cache()
    if not PAPER_TRADING_MODE:
        try:
            positions = ig.get_open_positions()
            for pos in positions:
                ig.close_position(deal_id=pos.get("dealId"),
                                  direction="SELL" if trade.direction == "LONG" else "BUY",
                                  size=trade.size_oz)
            log.info("[LIVE] Position closed via Capital.com | reason=%s", reason)
        except Exception as exc:
            log.error("Capital.com close_position failed: %s", exc)
            notify_system_error(f"Capital.com close failed: {exc}")
    if trade.pnl_gbp >= 0:
        notify_trade_closed_win(direction=trade.direction, exit_price=price,
                                points_gained=trade.points_gained, pnl_gbp=trade.pnl_gbp,
                                capital=account.capital_gbp, reason=reason)
    else:
        notify_trade_closed_loss(direction=trade.direction, exit_price=price,
                                 points_gained=trade.points_gained, pnl_gbp=trade.pnl_gbp,
                                 capital=account.capital_gbp, reason=reason)


def _handle_closed_trade(account, trade) -> None:
    if trade is None:
        return
    account.record_trade(trade.pnl_gbp)
    log.info("Trade result: %s%+.2f GBP | capital=£%.2f",
             "+" if trade.pnl_gbp >= 0 else "", trade.pnl_gbp, account.capital_gbp)


# ── Daily summary ─────────────────────────────────────────────────────────────

_last_summary_date: str = ""


def _maybe_send_daily_summary(stanley, account) -> None:
    global _last_summary_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today == _last_summary_date:
        return
    notify_daily_summary(date_str=today, trades=stanley.total_trades,
                         pnl_gbp=account.daily_pnl_gbp, capital=stanley.capital_gbp,
                         win_rate=stanley.win_rate)
    account.reset_daily()
    _last_summary_date = today
    log.info("Daily summary sent for %s", today)


# ── Main loop ─────────────────────────────────────────────────────────────────

def _interruptible_sleep(seconds: float) -> None:
    end = time.monotonic() + seconds
    while not _SHUTDOWN and time.monotonic() < end:
        time.sleep(min(1, end - time.monotonic()))


def _apply_confidence_lift() -> None:
    """Apply a pending manual confidence lift (logs/confidence_lift.json) in-process
    so a Gaius/dashboard lift takes effect LIVE -- Morgan's persisted baseline is
    otherwise cached in this process until restart. Written by the dashboard
    /api/lift-confidence endpoint (or Gaius --lift); consumed here via the existing
    set_confidence() and the flag deleted. Does not change the confidence algorithm."""
    import json
    try:
        if not LIFT_FLAG.exists():
            return
        data = json.loads(LIFT_FLAG.read_text(encoding="utf-8"))
        val = max(0.0, min(100.0, float(data.get("confidence", 50.0))))
        reason = data.get("reason") or "CONFIDENCE LIFT -- manual override"
        prior = performance_oil.get_confidence()
        performance_oil.set_confidence(val, reason=reason)
        invalidate_cache()   # so the reset/lift reflects on the next state push, not the next trade
        LIFT_FLAG.unlink(missing_ok=True)
        log.warning("Morgan CONFIDENCE LIFT applied live: %.1f -> %.1f (%s)", prior, val, reason)
    except Exception as _exc:
        log.warning("Confidence lift apply failed: %s", _exc)
        try:
            LIFT_FLAG.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> None:
    log.info("=" * 70)
    log.info("  OilHybrid AI v%s", VERSION)
    log.info("  Brent Crude (Brent Crude) Spread Betting -- Capital.com")
    log.info("  Mode: %s", "PAPER TRADING" if PAPER_TRADING_MODE else "LIVE TRADING")
    log.info("=" * 70)

    ig = CapitalComConnector()
    try:
        ig.connect()
        ig_connected = True
        log.info("Capital.com connected")
        # Bug E: log the FULL raw market details for OIL_BRENT so the real point
        # value (scalingFactor / onePipMeans / lotSize) can be verified before
        # go-live. Paper trading currently assumes 1 point = $1/bbl.
        try:
            details = ig.get_market_details(OIL_EPIC)
            if details:
                inst = details.get("instrument", {})
                rules = details.get("dealingRules", {})
                log.info("OIL_BRENT market details (VERIFY BEFORE GO-LIVE):")
                log.info("  instrument: %s", json.dumps(inst))
                log.info("  dealingRules: %s", json.dumps(rules))
            else:
                log.warning("OIL_BRENT market details unavailable (get_market_details returned None)")
        except Exception as exc:
            log.warning("OIL_BRENT market-details log failed: %s", exc)
    except Exception as exc:
        log.error("Capital.com connection failed: %s -- yfinance fallback", exc)
        ig_connected = False

    feed = OilDataFeed(ig_connector=ig if ig_connected else None)
    try:
        feed.initialise()
    except Exception as exc:
        log.warning("Initial data load partial: %s -- will retry", exc)

    stanley = PaperTraderOil()
    account = AccountState(capital=stanley.capital_gbp)
    stanley.print_status()

    notify_system_startup(capital=stanley.capital_gbp,
                          mode="PAPER" if PAPER_TRADING_MODE else "LIVE")

    # Clear any stale shutdown flag from a previous session (watchdog owns it during a run).
    SHUTDOWN_FLAG.unlink(missing_ok=True)

    log.info("OilHybrid AI is running. Ctrl+C to stop.")
    log.info("Dashboard: http://localhost:5045  (start dashboard_oil.py separately)")

    last_candle_tick    = 0.0
    last_position_check = 0.0
    last_heartbeat      = 0.0
    last_dashboard_push = 0.0
    _force_close_done   = False

    # Resolve stale phantom PENDING rows on startup, then run a 15-min watchdog
    try:
        phantom_tracker.resolve_stale_pending(get_historical_price_fn=feed.get_historical_price)
        phantom_tracker.start_watchdog(get_historical_price_fn=feed.get_historical_price, interval_minutes=15)
    except Exception as _exc:
        log.warning("phantom resolve/watchdog startup failed: %s", _exc)

    # Morgan individual phantom feedback -- poll newly-judged verdicts every 5 min
    try:
        performance_oil.process_new_phantom_verdicts()
    except Exception as _exc:
        log.warning("Morgan phantom-feedback poller startup failed: %s", _exc)

    # Restore Morgan's last-logged confidence from the CSV audit trail on startup
    try:
        _saved_conf = performance_oil.load_confidence()
        if _saved_conf is not None:
            performance_oil.set_confidence(_saved_conf, reason='restore')
            log.info("Morgan: restored confidence %.1f from CSV on startup", _saved_conf)
        else:
            # No saved confidence yet -- initialise morgan_confidence.csv at the
            # baseline so Morgan is visibly active and the file exists (Job 3).
            # OilHybrid had only NEUTRAL phantom verdicts, so nothing had ever
            # triggered a confidence write.
            performance_oil.set_confidence(performance_oil.get_confidence(), reason='init')
            log.info("Morgan: no saved confidence -- initialised morgan_confidence.csv "
                     "at baseline %.1f", performance_oil.get_confidence())
    except Exception as _exc:
        log.warning("Morgan confidence restore failed: %s", _exc)

    # Apply any confidence lift requested while the engine was down (Step 4).
    _apply_confidence_lift()

    import random
    # Stagger Capital.com API calls across systems (shared demo Z6CJSM) to avoid 429s
    STARTUP_DELAY_SECONDS = 45
    _delay = STARTUP_DELAY_SECONDS + random.uniform(0, 10)  # jitter avoids re-sync
    log.info("Staggering Capital.com requests -- waiting %.0fs before main loop", _delay)
    time.sleep(_delay)

    while not _SHUTDOWN:
        try:
            now     = time.monotonic()
            now_utc = datetime.now(timezone.utc)

            # Shutdown flag -- exit cleanly, leave flag for the watchdog to consume.
            if SHUTDOWN_FLAG.exists():
                log.info("Shutdown requested via dashboard -- stopping (flag left for watchdog)")
                break

            # Apply a pending manual confidence lift live (Gaius intervention Step 4).
            _apply_confidence_lift()

            # Live dashboard push (all periods, every ~15s)
            if (now - last_dashboard_push) >= DASHBOARD_INTERVAL:
                _push_dashboard_live(stanley, account, ig, feed, now_utc)
                last_dashboard_push = now

            # Liveness heartbeat
            if (now - last_heartbeat) >= HEARTBEAT_INTERVAL:
                log.info("Heartbeat -- alive | %s | period=%s | in_trade=%s",
                         now_utc.strftime("%H:%M UTC"), get_liquidity_period(now_utc),
                         stanley.in_trade)
                last_heartbeat = now

            # Kill-switch auto-reset
            if check_kill_switch_reset(account):
                notify_kill_switch_reset(tier=account.kill_switch_tier, wait_hours=0,
                                         capital=stanley.capital_gbp)
                account.kill_switch_tier = 0

            # Market closed (21:00-22:00 daily break or weekend)
            if not is_market_open(now_utc):
                if stanley.in_trade:
                    price  = _get_price(ig, feed)
                    gbpusd = get_gbpusd_rate(ig)
                    log.warning("Market closed with open position -- closing now")
                    _close_trade(stanley, account, ig, price, gbpusd, "MARKET_CLOSED")
                _maybe_send_daily_summary(stanley, account)
                mins = minutes_until_next_open(now_utc)
                sleep_sec = max(60, min(mins * 60, HEARTBEAT_INTERVAL)) if mins else HEARTBEAT_INTERVAL
                log.info("Oil market closed -- next open in %s min", mins if mins else "?")
                _interruptible_sleep(sleep_sec)
                _force_close_done = False
                continue

            # Force close at 20:45 UTC (never hold overnight)
            if should_force_close(now_utc):
                if stanley.in_trade and not _force_close_done:
                    price  = _get_price(ig, feed)
                    gbpusd = get_gbpusd_rate(ig)
                    log.warning("20:45 UTC force close triggered")
                    _close_trade(stanley, account, ig, price, gbpusd, "FORCE_CLOSE_2045")
                    _force_close_done = True
                _interruptible_sleep(30)
                continue

            # Position monitoring every 30s
            if stanley.in_trade and (now - last_position_check) >= POSITION_INTERVAL:
                monitor_open_position(stanley, account, ig, feed)
                last_position_check = now

            # Candle tick every 5 minutes
            if (now - last_candle_tick) >= CANDLE_INTERVAL:
                run_candle_tick(feed, stanley, account, ig)
                last_candle_tick = now

            _interruptible_sleep(5)

        except KeyboardInterrupt:
            break
        except Exception as exc:
            log.error("Main loop error: %s", exc, exc_info=True)
            notify_system_error(str(exc)[:200])
            time.sleep(30)

    # Shutdown
    log.info("")
    log.info("=" * 70)
    log.info("  OilHybrid AI -- Shutdown")
    log.info("=" * 70)
    if stanley.in_trade:
        log.warning("Position still open at shutdown -- closing paper record")
        price  = _get_price(ig, feed)
        gbpusd = get_gbpusd_rate(ig)
        _close_trade(stanley, account, ig, price, gbpusd, "SHUTDOWN")
    stanley.print_status()
    notify_system_shutdown(stanley.capital_gbp)
    log.info("OilHybrid AI stopped cleanly.")


if __name__ == "__main__":
    main()
