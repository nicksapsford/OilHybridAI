"""
OilHybrid AI -- performance_oil.py  (Morgan)
Performance tracker and confidence engine for Arthur.
Tracks win rate by direction and by liquidity period (Asian/London/NY/Overlap).
"""

import csv
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import phantom_tracker

# ─── ALBION STANDING RULE: ALL TIMESTAMPS ARE UTC ────────────────────────────
# Every timestamp this module reads or writes (trades.csv, morgan_confidence.csv,
# phantom verdicts, log lines) is UTC — written via datetime.now(timezone.utc)
# and read back as UTC. NEVER interpret any Albion timestamp as BST/local.
# Confirm UTC before analysing. (Nick's standing rule, baked in 12 Jul 2026.)

log = logging.getLogger("OilHybrid.Morgan")


# ── Morgan individual phantom feedback: persistent confidence store ───────────
_MORGAN_STATE_PATH = os.path.join(os.path.dirname(__file__), 'logs', 'morgan_confidence.json')
_morgan_lock = threading.Lock()
_morgan_confidence = None

# Morgan SHORT confidence (System 5 Review, 18 Jul 2026) -- a SEPARATE confidence that a
# SHORT scalp must clear (>= 65) before it can execute. OilHybrid has NO short history, so
# this starts at 30 and only builds as SHORT phantom evidence accrues. Distinct from the
# general Morgan confidence above. Mirrors FTSE/Crypto's SHORT gate.
_MORGAN_SHORT_STATE_PATH = os.path.join(os.path.dirname(__file__), 'logs', 'morgan_short_confidence.json')
_MORGAN_SHORT_INIT = 30.0
_morgan_short_confidence = None


def get_short_confidence():
    """Return the persisted Morgan SHORT confidence (float), defaulting to 30."""
    global _morgan_short_confidence
    with _morgan_lock:
        if _morgan_short_confidence is None:
            try:
                with open(_MORGAN_SHORT_STATE_PATH) as f:
                    _morgan_short_confidence = float(json.load(f).get('confidence', _MORGAN_SHORT_INIT))
            except Exception:
                _morgan_short_confidence = _MORGAN_SHORT_INIT
        return _morgan_short_confidence


def set_short_confidence(value, reason='update'):
    """Persist a new Morgan SHORT confidence (clamped 0-100)."""
    global _morgan_short_confidence
    with _morgan_lock:
        _morgan_short_confidence = max(0.0, min(100.0, float(value)))
        try:
            os.makedirs(os.path.dirname(_MORGAN_SHORT_STATE_PATH), exist_ok=True)
            with open(_MORGAN_SHORT_STATE_PATH, 'w') as f:
                json.dump({'confidence': _morgan_short_confidence}, f)
        except Exception as e:
            log.warning("Morgan SHORT: could not persist confidence: %s", e)
        log.info("Morgan SHORT: confidence set to %.1f (%s)", _morgan_short_confidence, reason)
        return _morgan_short_confidence

# ── Morgan confidence CSV persistence (audit trail of every confidence tick) ───
CONFIDENCE_LOG = os.path.join(os.path.dirname(__file__), 'logs', 'morgan_confidence.csv')
CONFIDENCE_FIELDNAMES = ['timestamp', 'confidence', 'level', 'reason']


def save_confidence(confidence, reason='tick'):
    """Append a confidence observation to CONFIDENCE_LOG (CSV audit trail)."""
    try:
        conf = max(0.0, min(100.0, float(confidence)))
        if conf >= 65:
            level = 'HIGH'
        elif conf <= 35:
            level = 'LOW'
        else:
            level = 'MEDIUM'
        row = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'confidence': conf,
            'level': level,
            'reason': reason,
        }
        os.makedirs(os.path.dirname(CONFIDENCE_LOG), exist_ok=True)
        file_exists = os.path.exists(CONFIDENCE_LOG)
        with open(CONFIDENCE_LOG, 'a', newline='') as f:
            w = csv.DictWriter(f, fieldnames=CONFIDENCE_FIELDNAMES)
            if not file_exists:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        log.warning("Morgan: could not save confidence to CSV: %s", e)


def load_confidence():
    """Return the last-logged confidence (float) from CONFIDENCE_LOG, else None."""
    try:
        if not os.path.exists(CONFIDENCE_LOG):
            return None
        last = None
        with open(CONFIDENCE_LOG, newline='') as f:
            for row in csv.DictReader(f):
                last = row
        if last is None:
            return None
        return float(last['confidence'])
    except Exception as e:
        log.warning("Morgan: could not load confidence from CSV: %s", e)
        return None


def _load_morgan_confidence():
    global _morgan_confidence
    if _morgan_confidence is None:
        try:
            with open(_MORGAN_STATE_PATH) as f:
                _morgan_confidence = float(json.load(f).get('confidence', 50.0))
        except Exception:
            _morgan_confidence = 50.0
    return _morgan_confidence


# Morgan WARNING + MANUAL RESET (OilHybrid, 23 Jul 2026). Morgan tracks freely and MAY
# drop below 50; there is NO automatic floor. When it does, morgan_below_floor() is True
# so the dashboard shows a warning + a manual RESET button. Nick reviews the evidence and
# consciously resets to 50 (/api/reset-morgan -> confidence_lift.json, applied live by the
# engine). Desk-wide principle for hybrids: warning + manual reset, never an auto-floor.
MORGAN_FLOOR = 50   # WARNING threshold only -- NOT an automatic clamp
# THREE-ZONE MORGAN MODEL (desk-wide, 24 Jul 2026 -- Nick's direct order): below 30 is
# Zone-3 HARD BLOCK -- no new entries (existing positions still managed), Gaius intervenes.
MORGAN_HARD_BLOCK = 30   # HARD BLOCK threshold (Zone 3: no new entries below this)
_MORGAN_LAST_RESET_PATH = os.path.join(os.path.dirname(__file__), 'logs', 'morgan_last_reset.json')


def morgan_below_floor(score) -> bool:
    """True when reported Morgan confidence is below the 50 warning threshold."""
    try:
        return float(score) < MORGAN_FLOOR
    except (TypeError, ValueError):
        return False


def morgan_hard_block(score) -> bool:
    """True when Morgan is below the 30 HARD BLOCK threshold (Zone 3). No new entries;
    Gaius intervention fires. Existing open positions are still managed/exited."""
    try:
        return float(score) < MORGAN_HARD_BLOCK
    except (TypeError, ValueError):
        return False


def last_morgan_reset():
    """UTC timestamp string of the last manual Morgan reset, or None."""
    try:
        with open(_MORGAN_LAST_RESET_PATH) as f:
            return json.load(f).get('reset_utc')
    except Exception:
        return None


def get_confidence():
    with _morgan_lock:
        return _load_morgan_confidence()


def set_confidence(value, reason='update'):
    global _morgan_confidence
    with _morgan_lock:
        _morgan_confidence = max(0.0, min(100.0, float(value)))
        try:
            os.makedirs(os.path.dirname(_MORGAN_STATE_PATH), exist_ok=True)
            with open(_MORGAN_STATE_PATH, 'w') as f:
                json.dump({'confidence': _morgan_confidence}, f)
        except Exception as e:
            log.warning("Morgan: could not persist confidence: %s", e)
        save_confidence(_morgan_confidence, reason)
        log.info("Morgan: confidence set to %.1f", _morgan_confidence)
        return _morgan_confidence


def apply_phantom_verdict_feedback(verdict, pnl_1hr, current_confidence):
    """Compute a confidence adjustment from a single phantom verdict.
    NEUTRAL -> no change. Otherwise raw magnitude = clamp(|pnl|/50, 0.5, 2.0);
    CORRECT nudges confidence up (+raw), WRONG nudges it down (-raw).
    Returns (adjustment, reason)."""
    if verdict == 'NEUTRAL':
        log.info("Morgan: phantom NEUTRAL -> no confidence change")
        return 0.0, "NEUTRAL verdict -- no individual signal"

    try:
        pnl = float(pnl_1hr)
    except (TypeError, ValueError):
        pnl = 0.0

    raw = max(0.5, min(2.0, abs(pnl) / 50.0))

    if verdict == 'CORRECT':
        adjustment = raw
        reason = ("CORRECT phantom (pnl=%.1f) -> confidence +%.2f "
                  "(right to stay out)" % (pnl, raw))
    elif verdict == 'WRONG':
        adjustment = -raw
        reason = ("WRONG phantom (pnl=%.1f) -> confidence -%.2f "
                  "(missed a winner)" % (pnl, raw))
    else:
        log.info("Morgan: phantom verdict '%s' unrecognised -> no change", verdict)
        return 0.0, "Unrecognised verdict '%s'" % verdict

    log.info("Morgan: %s (from confidence %.1f)", reason, current_confidence)
    return adjustment, reason


# Guard so the phantom-feedback poller is only started once per process.
_phantom_poller_thread = None


def process_new_phantom_verdicts(get_confidence_fn=None, set_confidence_fn=None):
    """Start a daemon poller that folds newly-judged phantom verdicts into
    Morgan's individual confidence every 5 minutes. Idempotent: a second call
    while the poller is alive is a no-op. get/set confidence funcs default to
    this module's get_confidence()/set_confidence()."""
    global _phantom_poller_thread
    if _phantom_poller_thread is not None and _phantom_poller_thread.is_alive():
        log.info("Morgan: phantom poller already running -- not starting a second.")
        return _phantom_poller_thread

    get_conf = get_confidence_fn or get_confidence
    set_conf = set_confidence_fn or set_confidence

    def _poll_loop():
        log.info("Morgan: phantom-feedback poller started -- scanning every 300s.")
        while True:
            try:
                rows = phantom_tracker.get_unprocessed_verdicts()
                processed = []
                for row in rows:
                    verdict = row.get('verdict')
                    pnl_1hr = row.get('pnl_1hr')
                    current = get_conf()
                    adjustment, reason = apply_phantom_verdict_feedback(
                        verdict, pnl_1hr, current
                    )
                    if adjustment != 0.0:
                        set_conf(max(0.0, min(100.0, current + adjustment)))
                    ts = row.get('timestamp')
                    if ts:
                        processed.append(ts)
                if processed:
                    phantom_tracker.mark_processed(processed)
                    log.info("Morgan: processed %d new phantom verdict(s).",
                             len(processed))
            except Exception as e:
                log.error("Morgan: phantom poller error: %s", e)
            time.sleep(300)

    _phantom_poller_thread = threading.Thread(
        target=_poll_loop, daemon=True, name="MorganPhantomPoller"
    )
    _phantom_poller_thread.start()
    log.info("Morgan: phantom-feedback poller thread started.")
    return _phantom_poller_thread


def get_stay_out_adjustment():
    """Morgan self-improvement: nudge confidence by STAY OUT decision quality.
    >70% correct -> +5 ; <40% correct -> -5 ; 40-70% or <5 samples -> 0."""
    summary = phantom_tracker.get_summary(last_n=10)
    if summary['total'] < 5:
        return 0.0
    quality = summary['quality_score']
    if quality is None:
        return 0.0
    if quality > 70:
        log.info("Morgan: STAY OUT quality %s%% -> confidence +5", quality)
        return 5.0
    if quality < 40:
        log.info("Morgan: STAY OUT quality %s%% -> confidence -5", quality)
        return -5.0
    return 0.0

LOG_DIR    = Path(__file__).parent / "logs"
TRADES_LOG = LOG_DIR / "oil_trades.csv"
REVIEW_DIR = LOG_DIR

LIQUIDITY_PERIODS = ["ASIAN", "LONDON", "OVERLAP", "NEW_YORK"]

_cache: dict = {}
_cache_valid = False


def invalidate_cache() -> None:
    global _cache_valid
    _cache_valid = False


def _load_trades(trades_log: Path = TRADES_LOG) -> pd.DataFrame:
    if not trades_log.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(trades_log)
        if df.empty:
            return df
        df["pnl_gbp"] = pd.to_numeric(df["pnl_gbp"], errors="coerce").fillna(0)
        df["_dt"]     = pd.to_datetime(df["entry_time"], errors="coerce")
        return df
    except Exception as exc:
        log.warning("Could not load trades: %s", exc)
        return pd.DataFrame()


def _compute_confidence(df: pd.DataFrame) -> dict:
    """Confidence score 0-100 based on recent performance. Zone-3 HARD BLOCK below 30
    (no new entries); Zone-2 WARNING 30-49 (trading continues); NORMAL >=50."""
    if df.empty or len(df) < 5:
        _empty_score = int(max(0, min(100, 50 + get_stay_out_adjustment())))
        _empty_level = ("HIGH" if _empty_score >= 75 else "MEDIUM" if _empty_score >= 50
                        else "LOW" if _empty_score >= 25 else "VERY_LOW")
        return {
            "confidence_score":  _empty_score,
            "confidence_level": _empty_level,
            # conservative now means Zone-3 HARD BLOCK (<30); it drives Gaius + dashboard.
            "conservative": morgan_hard_block(_empty_score),
            "morgan_hard_block": morgan_hard_block(_empty_score),
            "total_trades": 0, "win_rate": 0.0, "recent_5": [],
            "streak_type": "", "streak_count": 0,
            "strongest_conditions": [], "weakest_conditions": [],
            "morgan_below_floor": morgan_below_floor(_empty_score),
            "morgan_raw": _empty_score, "morgan_last_reset": last_morgan_reset(),
        }

    pnls     = df["pnl_gbp"].values
    wins     = sum(1 for p in pnls if p >= 0)
    total    = len(pnls)
    win_rate = wins / total * 100

    recent_20 = df.tail(20)["pnl_gbp"].values
    recent_5  = ["WIN" if p >= 0 else "LOSS" for p in df.tail(5)["pnl_gbp"].values]
    r20_wins  = sum(1 for p in recent_20 if p >= 0)
    r20_wr    = r20_wins / len(recent_20) * 100 if recent_20.size > 0 else 50.0

    avg_win  = sum(p for p in pnls if p > 0) / max(1, wins)
    avg_loss = abs(sum(p for p in pnls if p < 0)) / max(1, total - wins)
    rr       = avg_win / avg_loss if avg_loss > 0 else 1.0

    streak_type, streak_count = "", 0
    for p in reversed(pnls):
        is_win = p >= 0
        if streak_count == 0:
            streak_type, streak_count = ("WIN" if is_win else "LOSS"), 1
        elif (streak_type == "WIN" and is_win) or (streak_type == "LOSS" and not is_win):
            streak_count += 1
        else:
            break

    score = 50.0
    score += (r20_wr - 50) * 0.6
    score += (rr - 1.0) * 5.0
    if streak_type == "WIN"  and streak_count >= 3: score += 10
    if streak_type == "LOSS" and streak_count >= 3: score -= 15
    score = max(0, min(100, round(score)))
    score = int(max(0, min(100, score + get_stay_out_adjustment())))
    # Fold in Morgan's individual phantom feedback (delta from the 50.0 baseline)
    # separately from get_stay_out_adjustment() so the two are not double-counted.
    score = int(max(0, min(100, score + (get_confidence() - 50.0))))

    if score >= 75:   level = "HIGH"
    elif score >= 50: level = "MEDIUM"
    elif score >= 25: level = "LOW"
    else:             level = "VERY_LOW"

    strongest, weakest = [], []
    if total >= 10:
        for direction in ["LONG", "SHORT"]:
            sub = df[df["direction"] == direction]
            if len(sub) >= 5:
                wr_dir = sum(1 for p in sub["pnl_gbp"] if p >= 0) / len(sub) * 100
                label  = f"{direction}: {wr_dir:.0f}% WR ({len(sub)} trades)"
                if wr_dir >= 60:
                    strongest.append(label)
                elif wr_dir < 45:
                    weakest.append(label)
        if "liquidity_period" in df.columns:
            for period in LIQUIDITY_PERIODS:
                sub = df[df["liquidity_period"] == period]
                if len(sub) >= 5:
                    wr_p  = sum(1 for p in sub["pnl_gbp"] if p >= 0) / len(sub) * 100
                    label = f"{period}: {wr_p:.0f}% WR ({len(sub)} trades)"
                    if wr_p >= 60:
                        strongest.append(label)
                    elif wr_p < 45:
                        weakest.append(label)

    return {
        "confidence_score":     score,
        "confidence_level":     level,
        # conservative now means Zone-3 HARD BLOCK (<30); it drives Gaius + dashboard.
        "conservative":         morgan_hard_block(score),
        "morgan_hard_block":    morgan_hard_block(score),
        "morgan_below_floor":   morgan_below_floor(score),
        "morgan_raw":           score,
        "morgan_last_reset":    last_morgan_reset(),
        "total_trades":         total,
        "win_rate":             round(win_rate, 1),
        "recent_5":             list(reversed(recent_5)),
        "streak_type":          streak_type,
        "streak_count":         streak_count,
        "strongest_conditions": strongest,
        "weakest_conditions":   weakest,
    }


def _compute_direction_liquidity_stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"direction": {}, "liquidity": {}}
    direction_stats = {}
    for d in ["LONG", "SHORT"]:
        sub = df[df["direction"] == d]
        if len(sub) == 0:
            continue
        wins = int(sum(1 for p in sub["pnl_gbp"] if p >= 0))
        direction_stats[d] = {
            "trades": int(len(sub)), "wins": wins,
            "win_rate": round(wins / len(sub) * 100, 1),
            "net_pnl": round(float(sub["pnl_gbp"].sum()), 2),
        }
    liquidity_stats = {}
    if "liquidity_period" in df.columns:
        for p in LIQUIDITY_PERIODS:
            sub = df[df["liquidity_period"] == p]
            if len(sub) == 0:
                continue
            wins = int(sum(1 for x in sub["pnl_gbp"] if x >= 0))
            liquidity_stats[p] = {
                "trades": int(len(sub)), "wins": wins,
                "win_rate": round(wins / len(sub) * 100, 1),
                "net_pnl": round(float(sub["pnl_gbp"].sum()), 2),
            }
    return {"direction": direction_stats, "liquidity": liquidity_stats}


def get_performance_context(trades_log: Path = TRADES_LOG) -> str:
    """Formatted performance context string for Arthur."""
    df   = _load_trades(trades_log)
    perf = _compute_confidence(df)
    lines = [
        "SELF PERFORMANCE AWARENESS (Morgan)",
        f"  Confidence:     {perf['confidence_score']}/100 {perf['confidence_level']}",
        f"  Morgan zone:    {'HARD BLOCK (<30) -- no new entries' if perf['morgan_hard_block'] else 'WARNING (30-49) -- trading continues' if perf['morgan_below_floor'] else 'NORMAL (>=50)'}",
        f"  Total trades:   {perf['total_trades']}",
        f"  Win rate:       {perf['win_rate']}%",
        f"  Current streak: {perf['streak_count']} {perf['streak_type']}",
        f"  Recent (last 5): {' | '.join(perf['recent_5']) if perf['recent_5'] else 'no trades yet'}",
    ]
    if perf["strongest_conditions"]:
        lines.append("  Strongest: " + ", ".join(perf["strongest_conditions"]))
    if perf["weakest_conditions"]:
        lines.append("  Weakest:   " + ", ".join(perf["weakest_conditions"]))
    lines.append(
        "\n  Confidence guide (context only -- does NOT change your entry threshold "
        "above 30): >=50 NORMAL, 30-49 WARNING (trade normally; Nick reviews), "
        "<30 HARD BLOCK (system suspends new entries; Gaius intervenes)."
    )
    return "\n".join(lines)


def get_perf_dashboard_dict(trades_log: Path = TRADES_LOG) -> dict:
    """Performance data dict for dashboard rendering (includes breakdown.liquidity)."""
    global _cache, _cache_valid
    if _cache_valid:
        return _cache
    df   = _load_trades(trades_log)
    perf = _compute_confidence(df)
    breakdown = _compute_direction_liquidity_stats(df)
    _cache = {**perf, "breakdown": breakdown}
    _cache_valid = True
    return _cache


def generate_milestone_review(trades_log: Path, milestone_num: int) -> None:
    """Save a milestone review to logs/arthur_oil_review_XX.txt every 50 trades."""
    df = _load_trades(trades_log)
    if df.empty:
        return
    perf      = _compute_confidence(df)
    breakdown = _compute_direction_liquidity_stats(df)
    review_file = REVIEW_DIR / f"arthur_oil_review_{milestone_num:02d}.txt"
    lines = [
        "=" * 60,
        f"OilHybrid AI -- Arthur Milestone Review #{milestone_num}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Trades completed: {perf['total_trades']}",
        "=" * 60,
        "",
        "PERFORMANCE SUMMARY",
        f"  Win rate:       {perf['win_rate']}%",
        f"  Confidence:     {perf['confidence_score']}/100 {perf['confidence_level']}",
        f"  Current streak: {perf['streak_count']} {perf['streak_type']}",
        "",
        "DIRECTION BREAKDOWN",
    ]
    for d, stats in breakdown["direction"].items():
        lines.append(f"  {d}: {stats['trades']} trades | {stats['win_rate']}% WR | net GBP {stats['net_pnl']:+.2f}")
    lines.append("\nLIQUIDITY PERIOD BREAKDOWN")
    for p, stats in breakdown["liquidity"].items():
        lines.append(f"  {p}: {stats['trades']} trades | {stats['win_rate']}% WR | net GBP {stats['net_pnl']:+.2f}")
    if perf["strongest_conditions"]:
        lines.append("\nSTRONGEST CONDITIONS")
        for c in perf["strongest_conditions"]:
            lines.append(f"  + {c}")
    if perf["weakest_conditions"]:
        lines.append("\nWEAKEST CONDITIONS (consider avoiding)")
        for c in perf["weakest_conditions"]:
            lines.append(f"  - {c}")
    lines.append("\n" + "=" * 60)
    with open(review_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    log.info("Milestone review saved: %s", review_file)


if __name__ == "__main__":
    logging.Formatter.converter = time.gmtime  # ALBION RULE: emit log timestamps in UTC
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S UTC",
    )
    log.info("Morgan self-test (Oil)")
    log.info("Performance context:\n%s", get_performance_context())
    log.info("Morgan self-test complete.")
