"""
OilHybrid AI -- strategy_oil.py
Brent crude spread betting strategy mechanics.
Points-based trailing stop. Prices are in USD per barrel; P&L is computed
in USD then converted to GBP using the live GBPUSD rate from Capital.com.

Sizing (confirmed/approved settings -- v1.1.5, Nick sign-off 13 Jul 2026):
  Stop distance:   5 points ($5/bbl)   (~1.4x Brent's median daily range $3.46)
  Take profit:     25 points ($25/bbl) safety ceiling (5:1 R:R)
  Max risk/trade:  £20  (2% of £1,000)
  => stake sized so a full stop-out risks ~£20  (varies slightly with GBPUSD)
  NOTE: reviewed weekly (Saturday) as signal-aligned trade data accumulates.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("OilHybrid.Strategy")

# ── Settings ──────────────────────────────────────────────────────────────────

# Stop/target recalibrated to Brent's real intraday range (System 5 Review, 18 Jul
# 2026). The old 5pt stop / 25pt target never triggered: Brent's median 30-min adverse
# move is only 0.20pt and the largest live move ever was 3.64pt. Whipsaw backtest (BZ=F,
# 60d 5m): a 1.5pt stop whipsaws just 2.0% of the time in 30 min -- well above noise. So
# stop 1.5 / target 3.0 (2:1 R:R). Sizing is risk/stop, so stake jumps to £20/1.5 =
# £13.33/pt (was £4/pt at 5pt) -- P&L now moves ~3x faster. Backtest-provisional, 4-wk review.
TRAILING_STOP_POINTS   = 1.5     # trailing stop in oil points ($/bbl)
TAKE_PROFIT_POINTS     = 3.0     # scalp target, 2:1 R:R vs the 1.5pt stop
MAX_RISK_PER_TRADE_GBP = 20.0    # max GBP loss per trade (2% of £1,000)

# Profit Protection Ladder (Variant 2, 17 Jul 2026). As floating profit builds,
# tighten the trailing stop to guarantee a minimum GBP floor. Additive to the
# trailing stop -- only ever tightens, never triggers on a floating loss, and the
# 20:45 UTC force close remains master. Backtest-provisional -- review after 2wks.
# Recalibrated for the 1.5pt stop / 3pt target profile at £13.33/pt (System 5 Review,
# 18 Jul 2026): Step1 ~0.6pt (developing), Step2 ~1.2pt (halfway), Step3 ~2.1pt (approaching).
PROFIT_LADDER = [
    {"trigger_gbp": 8.00,  "floor_gbp": 6.00},
    {"trigger_gbp": 16.00, "floor_gbp": 13.00},
    {"trigger_gbp": 28.00, "floor_gbp": 24.00},
]
SPREAD_POINTS          = 0.034   # Capital.com Brent spread ($/bbl), confirmed from demo API 16 Jul 2026 (was 0.3)
DEFAULT_GBPUSD         = 1.27    # conservative fallback if live rate unavailable

# Force close 15 minutes before the 21:00 UTC daily close -- NEVER hold overnight.
FORCE_CLOSE_START_MIN  = 20 * 60 + 45   # 20:45 UTC
DAILY_CLOSE_MIN        = 21 * 60        # 21:00 UTC


# ── GBPUSD conversion ─────────────────────────────────────────────────────────

_last_gbpusd = DEFAULT_GBPUSD


def get_gbpusd_rate(connector=None) -> float:
    """
    Return the live GBPUSD rate from Capital.com (epic GBPUSD).
    NB: the connector rounds 'mid' to 1 dp (fine for oil, useless for FX), so we
    compute the mid ourselves from the raw bid/ask. Falls back to the last good
    rate, then DEFAULT_GBPUSD, if the market is unavailable.
    """
    global _last_gbpusd
    if connector is not None:
        try:
            if getattr(connector, "connected", False):
                p = connector.get_price("GBPUSD")
                if p and p.get("bid") and p.get("ask"):
                    rate = (float(p["bid"]) + float(p["ask"])) / 2
                    if rate > 0:
                        _last_gbpusd = round(rate, 5)
        except Exception as exc:
            log.warning("GBPUSD fetch failed: %s -- using %.4f", exc, _last_gbpusd)
    return _last_gbpusd


# ── Sizing helpers ────────────────────────────────────────────────────────────

def calculate_size(stop_pts: float = TRAILING_STOP_POINTS,
                   gbpusd: float = DEFAULT_GBPUSD,
                   risk_gbp: float = MAX_RISK_PER_TRADE_GBP) -> float:
    """
    Position size in barrels so that a full stop-out loses ~risk_gbp.
      risk_gbp = stop_pts * size_oz / gbpusd   =>   size_oz = risk_gbp * gbpusd / stop_pts
    At GBPUSD 1.3376 this is ~5.35 oz for a 5pt stop and £20 risk.
    """
    if stop_pts <= 0:
        return 0.0
    return round(risk_gbp * gbpusd / stop_pts, 2)


def calculate_stake(stop_pts: float = TRAILING_STOP_POINTS,
                    gbpusd: float = DEFAULT_GBPUSD) -> float:
    """Return £ risk per point for the given stop distance (= size_oz / gbpusd)."""
    size_oz = calculate_size(stop_pts, gbpusd)
    return round(size_oz / gbpusd, 4) if gbpusd > 0 else 0.0


def calculate_entry(current_price: float, direction: str) -> float:
    """Entry price for a market order (mid). Direction kept for interface parity."""
    return round(float(current_price), 2)


def calculate_stop_loss(entry_price: float, direction: str,
                        stop_pts: float = TRAILING_STOP_POINTS) -> float:
    return round(entry_price - stop_pts if direction == "LONG" else entry_price + stop_pts, 2)


def calculate_take_profit(entry_price: float, direction: str,
                          tp_pts: float = TAKE_PROFIT_POINTS) -> float:
    return round(entry_price + tp_pts if direction == "LONG" else entry_price - tp_pts, 2)


def calculate_pnl(entry_price: float, exit_price: float, direction: str,
                  size_oz: float, gbpusd: float) -> tuple:
    """
    Return (points_gained, pnl_usd, pnl_gbp), net of spread.
      points_gained = price move in USD points (minus spread)
      pnl_usd       = points_gained * size_oz  ($1/bbl per point)
      pnl_gbp       = pnl_usd / gbpusd
    """
    raw_pts = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
    points  = raw_pts - SPREAD_POINTS
    pnl_usd = points * size_oz
    pnl_gbp = pnl_usd / gbpusd if gbpusd > 0 else 0.0
    return round(points, 2), round(pnl_usd, 2), round(pnl_gbp, 2)


def should_force_close(ts_utc: Optional[datetime] = None) -> bool:
    """True during the 20:45-21:00 UTC pre-close window -- force close all positions."""
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc)
    hm = ts_utc.hour * 60 + ts_utc.minute
    return FORCE_CLOSE_START_MIN <= hm < DAILY_CLOSE_MIN


# ── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class OilTrade:
    """
    A single Oil spread bet. Entry/exit prices are USD per barrel.
    P&L is computed in USD then converted to GBP at the exit-time GBPUSD rate.
    """
    direction:        str
    entry_price:      float
    stop_pts:         float = TRAILING_STOP_POINTS
    size_oz:          float = 0.0
    gbpusd_entry:     float = DEFAULT_GBPUSD
    entry_time:       object = field(default=None)
    liquidity_period: str    = field(default="")

    def __post_init__(self):
        if self.size_oz <= 0:
            self.size_oz = calculate_size(self.stop_pts, self.gbpusd_entry)
        self.stake        = round(self.size_oz / self.gbpusd_entry, 4) if self.gbpusd_entry > 0 else 0.0
        self.trail_best   = self.entry_price
        self.stop_loss    = calculate_stop_loss(self.entry_price, self.direction, self.stop_pts)
        self.take_profit  = calculate_take_profit(self.entry_price, self.direction)
        self.exit_price   = None
        self.exit_time    = None
        self.exit_reason  = None
        self.points_gained = None
        self.pnl_usd      = None
        self.pnl_gbp      = None
        self.gbpusd_exit  = None
        self.ladder_step      = 0        # highest profit-ladder rung triggered
        self.ladder_floor_gbp = 0.0      # locked minimum-profit floor (GBP)
        if self.entry_time is None:
            self.entry_time = datetime.now(timezone.utc)

    def apply_profit_ladder(self, price: float):
        """Profit Protection Ladder (Variant 2). Tighten the stop to guarantee a
        minimum GBP floor as floating profit builds -- additive to the trailing stop,
        only ever tightens, never triggers on a floating loss. The trailing stop and
        the force close are unaffected (whichever stop is tighter wins). Idempotent,
        so it re-applies correctly on restart. Returns a dict describing a NEWLY
        triggered rung (for logging), else None."""
        if not PROFIT_LADDER or self.stake <= 0:
            return None
        if not hasattr(self, "ladder_step"):     # lazy init (also survives reload)
            self.ladder_step, self.ladder_floor_gbp = 0, 0.0
        pts = (price - self.entry_price) if self.direction == "LONG" else (self.entry_price - price)
        float_gbp = pts * self.stake
        if float_gbp <= 0:                       # never engage on a floating loss
            return None
        idx, floor = 0, 0.0
        for i, s in enumerate(PROFIT_LADDER, start=1):
            if float_gbp >= s["trigger_gbp"]:
                idx, floor = i, s["floor_gbp"]
        if idx == 0:
            return None
        new_rung = idx > self.ladder_step
        if new_rung:
            self.ladder_step = idx
            self.ladder_floor_gbp = floor
        if self.ladder_floor_gbp <= 0:
            return None
        floor_pts = self.ladder_floor_gbp / self.stake
        stop_before = self.stop_loss
        if self.direction == "LONG":
            floor_stop = round(self.entry_price + floor_pts, 2)
            if floor_stop > self.stop_loss:      # tighten only
                self.stop_loss = floor_stop
        else:
            floor_stop = round(self.entry_price - floor_pts, 2)
            if floor_stop < self.stop_loss:      # tighten only
                self.stop_loss = floor_stop
        if new_rung:
            log.info("  PROFIT LADDER step %d: float GBP %.2f -> floor GBP %.2f | stop %.2f -> %.2f",
                     idx, float_gbp, self.ladder_floor_gbp, stop_before, self.stop_loss)
            return {"step": idx, "floor_gbp": self.ladder_floor_gbp,
                    "trigger_float_gbp": round(float_gbp, 2),
                    "stop_before": round(stop_before, 2), "stop_after": self.stop_loss}
        return None

    def update_trailing_stop(self, price: float) -> bool:
        """Move the stop in favour of the trade. Returns True if moved."""
        if self.direction == "LONG" and price > self.trail_best:
            self.trail_best = price
            new_sl = price - self.stop_pts
            if new_sl > self.stop_loss:
                self.stop_loss = round(new_sl, 2)
                log.info("  Trailing stop moved UP to %.2f (price=%.2f)", self.stop_loss, price)
                return True
        elif self.direction == "SHORT" and price < self.trail_best:
            self.trail_best = price
            new_sl = price + self.stop_pts
            if new_sl < self.stop_loss:
                self.stop_loss = round(new_sl, 2)
                log.info("  Trailing stop moved DOWN to %.2f (price=%.2f)", self.stop_loss, price)
                return True
        return False

    def check_exit(self, price: float) -> Optional[str]:
        """Check stop loss and take profit. Returns exit reason or None."""
        if self.direction == "LONG":
            if price <= self.stop_loss:   return "STOP_LOSS"
            if price >= self.take_profit: return "TAKE_PROFIT"
        else:
            if price >= self.stop_loss:   return "STOP_LOSS"
            if price <= self.take_profit: return "TAKE_PROFIT"
        return None

    def close(self, price: float, reason: str, gbpusd: float) -> None:
        """Record exit and compute USD + GBP P&L at the given GBPUSD rate."""
        self.exit_price   = round(price, 2)
        self.exit_time    = datetime.now(timezone.utc)
        self.exit_reason  = reason
        self.gbpusd_exit  = round(gbpusd, 5)
        pts, pnl_usd, pnl_gbp = calculate_pnl(
            self.entry_price, price, self.direction, self.size_oz, gbpusd,
        )
        self.points_gained = pts
        self.pnl_usd       = pnl_usd
        self.pnl_gbp       = pnl_gbp

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    def summary(self) -> str:
        if self.is_open:
            return (
                f"[OPEN {self.direction}] entry=${self.entry_price:,.2f} "
                f"stop=${self.stop_loss:,.2f} target=${self.take_profit:,.2f} "
                f"size={self.size_oz:.2f}oz stake=£{self.stake:.4f}/pt"
            )
        sign = "WIN " if (self.pnl_gbp or 0) >= 0 else "LOSS"
        return (
            f"[{sign} {self.direction}] entry=${self.entry_price:,.2f} "
            f"exit=${self.exit_price:,.2f} pts={self.points_gained:+.1f} "
            f"P&L=£{self.pnl_gbp:+.2f} (${self.pnl_usd:+.2f} @ {self.gbpusd_exit}) "
            f"reason={self.exit_reason}"
        )


# ── Open / close helpers ──────────────────────────────────────────────────────

def open_trade(direction: str, price: float, gbpusd: float,
               liquidity_period: str = "", stop_pts: float = TRAILING_STOP_POINTS) -> OilTrade:
    trade = OilTrade(
        direction        = direction,
        entry_price      = round(price, 2),
        stop_pts         = stop_pts,
        gbpusd_entry     = gbpusd,
        entry_time       = datetime.now(timezone.utc),
        liquidity_period = liquidity_period,
    )
    log.info(
        ">>> TRADE OPENED | %s | entry=$%.2f | size=%.2foz | stake=£%.4f/pt | "
        "stop=$%.2f | target=$%.2f | %s | GBPUSD=%.4f",
        direction, price, trade.size_oz, trade.stake,
        trade.stop_loss, trade.take_profit, liquidity_period, gbpusd,
    )
    return trade


def close_trade(trade: OilTrade, price: float, reason: str, gbpusd: float) -> OilTrade:
    trade.close(price, reason, gbpusd)
    sign = "WIN " if trade.pnl_gbp >= 0 else "LOSS"
    log.info(
        "<<< TRADE CLOSED | [%s %s] | pts=%+.1f | P&L=£%+.2f ($%+.2f) | reason=%s",
        sign, trade.direction, trade.points_gained, trade.pnl_gbp, trade.pnl_usd, reason,
    )
    return trade


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("Strategy self-test (Oil)")
    gbpusd = 1.3376
    t = open_trade("LONG", 80.00, gbpusd, "OVERLAP")   # real Brent scale (~$80/bbl)
    log.info("%s", t.summary())
    log.info("Size=%.2foz | stake=£%.4f/pt | max risk=£%.2f",
             t.size_oz, t.stake, t.stop_pts * t.size_oz / gbpusd)
    t.update_trailing_stop(86.00)
    log.info("After +6.00 move: stop=$%.2f (trails to 81.00)", t.stop_loss)
    reason = t.check_exit(80.50)
    log.info("Check exit at 80.50: %s", reason)
    close_trade(t, 80.50, "STOP_LOSS", gbpusd)
    log.info("%s", t.summary())
    log.info("Force close at 20:45 UTC now? %s", should_force_close())
