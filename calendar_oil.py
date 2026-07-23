"""
OilHybrid AI -- calendar_oil.py  (Guinevere)
Oil economic calendar. Hard blocks around the events that move oil most:
US Non-Farm Payrolls, Federal Reserve decisions, and US CPI. Plus a recurring
oil-specific hard block for the first 15 minutes of the New York open.

All event times are in UTC. Soft context (London/NY open, overlap) is passed
to Arthur but never hard-blocks.

NOTE: US CPI release dates are APPROXIMATED here as the second Wednesday of each
month at 13:30 UTC. Verify against the official BLS schedule before going live.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

log = logging.getLogger("OilHybrid.Guinevere")

HARD_BLOCK_MINUTES = 30

# ── Federal Reserve decisions 2026 (19:00 UTC) ────────────────────────────────
FED_DATES_2026 = [
    "2026-01-29", "2026-03-19", "2026-05-07", "2026-06-18",
    "2026-07-30", "2026-09-17", "2026-11-05", "2026-12-10",
]
FED_HOUR, FED_MIN = 19, 0

# ── NFP / CPI release time (13:30 UTC) ────────────────────────────────────────
US_HOUR, US_MIN = 13, 30

# ── NY open first-15-minutes recurring hard block ─────────────────────────────
NY_OPEN_MIN       = 13 * 60 + 30   # 13:30 UTC
NY_OPEN_BLOCK_END = 13 * 60 + 45   # 13:45 UTC


def _utc(date_str: str, hour: int, minute: int) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=hour, minute=minute, tzinfo=timezone.utc,
    )


def _first_friday_dates(year: int) -> list:
    dates = []
    for month in range(1, 13):
        d = datetime(year, month, 1)
        while d.weekday() != 4:   # Friday
            d += timedelta(days=1)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


def _second_wednesday_dates(year: int) -> list:
    dates = []
    for month in range(1, 13):
        d = datetime(year, month, 1)
        wednesdays = 0
        while True:
            if d.weekday() == 2:   # Wednesday
                wednesdays += 1
                if wednesdays == 2:
                    break
            d += timedelta(days=1)
        dates.append(d.strftime("%Y-%m-%d"))
    return dates


def _build_events() -> list:
    events = []
    for d in FED_DATES_2026:
        events.append({"name": "Federal Reserve Decision", "datetime": _utc(d, FED_HOUR, FED_MIN),
                       "impact": "HARD_BLOCK", "source": "Fed", "date_str": d})
    for year in (2026, 2027):
        for d in _first_friday_dates(year):
            events.append({"name": "US Non-Farm Payrolls", "datetime": _utc(d, US_HOUR, US_MIN),
                           "impact": "HARD_BLOCK", "source": "US", "date_str": d})
        for d in _second_wednesday_dates(year):
            events.append({"name": "US CPI (approx.)", "datetime": _utc(d, US_HOUR, US_MIN),
                           "impact": "HARD_BLOCK", "source": "US", "date_str": d})
    return events


_EVENTS = _build_events()


def _ny_open_block(now_utc: datetime) -> Optional[str]:
    """Recurring oil hard block: first 15 minutes of the NY open (weekdays)."""
    if now_utc.weekday() >= 5:
        return None
    hm = now_utc.hour * 60 + now_utc.minute
    if NY_OPEN_MIN <= hm < NY_OPEN_BLOCK_END:
        mins_remaining = NY_OPEN_BLOCK_END - hm
        return (f"New York open first 15 minutes (13:30-13:45 UTC) -- "
                f"extreme volatility spike, {mins_remaining} min remaining")
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def check_calendar(now_utc: Optional[datetime] = None) -> dict:
    """Main calendar check. Returns hard_block / block_reason / upcoming_events / calendar_summary."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    hard_block   = False
    block_reason = ""

    # Recurring NY-open block first.
    ny_block = _ny_open_block(now_utc)
    if ny_block:
        hard_block, block_reason = True, ny_block
        log.warning("GUINEVERE HARD BLOCK: %s", block_reason)

    # Dated events within +/- HARD_BLOCK_MINUTES.
    if not hard_block:
        window = HARD_BLOCK_MINUTES * 60
        for ev in _EVENTS:
            delta_secs = (ev["datetime"] - now_utc).total_seconds()
            if -window <= delta_secs <= window:
                hard_block = True
                if delta_secs >= 0:
                    mins = int(delta_secs / 60)
                    block_reason = (f"{ev['name']} in {mins} minutes "
                                    f"({ev['datetime'].strftime('%H:%M UTC')}, {ev['date_str']}) -- "
                                    f"hard block {HARD_BLOCK_MINUTES} min either side")
                else:
                    mins = int(-delta_secs / 60)
                    block_reason = (f"{ev['name']} released {mins} minutes ago -- "
                                    f"volatility window active, {HARD_BLOCK_MINUTES - mins} min remaining")
                log.warning("GUINEVERE HARD BLOCK: %s", block_reason)
                break

    # Upcoming events (next 24h).
    upcoming = []
    window_24h = timedelta(hours=24)
    for ev in _EVENTS:
        delta = ev["datetime"] - now_utc
        if timedelta(0) <= delta <= window_24h:
            upcoming.append({
                "name":      ev["name"],
                "time_utc":  ev["datetime"].strftime("%H:%M UTC"),
                "date":      ev["date_str"],
                "impact":    ev["impact"],
                "mins_away": int(delta.total_seconds() / 60),
            })
    upcoming.sort(key=lambda x: x["mins_away"])

    future = sorted([ev for ev in _EVENTS if ev["datetime"] > now_utc], key=lambda x: x["datetime"])
    next_ev = future[0] if future else None
    next_ev_str = ""
    if next_ev:
        days = (next_ev["datetime"] - now_utc).days
        next_ev_str = f"Next major event: {next_ev['name']} on {next_ev['date_str']} ({days} days away)"

    if hard_block:
        summary = f"HARD BLOCK ACTIVE: {block_reason}"
    elif upcoming:
        ev_list = "; ".join(f"{u['name']} in {u['mins_away']} min" for u in upcoming[:3])
        summary = f"Upcoming: {ev_list}. {next_ev_str}"
    else:
        summary = f"Calendar clear -- no oil events in next 24h. {next_ev_str}"

    return {
        "hard_block":       hard_block,
        "block_reason":     block_reason,
        "upcoming_events":  upcoming,
        "calendar_summary": summary,
        "next_event":       next_ev_str,
    }


def is_hard_blocked(now_utc: Optional[datetime] = None) -> tuple:
    """Quick check. Returns (hard_block, reason, event_name, mins_remaining)."""
    result = check_calendar(now_utc)
    if result["hard_block"]:
        return True, result["block_reason"], "Oil Event", HARD_BLOCK_MINUTES
    return False, "", "", 0


def get_calendar_context(now_utc: Optional[datetime] = None) -> str:
    """Formatted calendar context string for Arthur."""
    cal = check_calendar(now_utc)
    lines = [
        "OIL ECONOMIC CALENDAR",
        f"  Status: {'HARD BLOCK ACTIVE' if cal['hard_block'] else 'Clear'}",
    ]
    if cal["block_reason"]:
        lines.append(f"  Block reason: {cal['block_reason']}")
    if cal["upcoming_events"]:
        lines.append("  Upcoming (next 24h):")
        for ev in cal["upcoming_events"][:5]:
            lines.append(f"    {ev['name']} -- {ev['time_utc']} (in {ev['mins_away']} min) [HARD BLOCK]")
    if cal["next_event"]:
        lines.append(f"  {cal['next_event']}")
    lines.append("  NOTE: Oil moves hard on USD strength, Fed decisions, inflation data and geopolitics.")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("Guinevere self-test (Oil)")
    now = datetime.now(timezone.utc)
    log.info("Current UTC: %s", now.strftime("%Y-%m-%d %H:%M"))
    cal = check_calendar(now)
    log.info("Hard block: %s", cal["hard_block"])
    log.info("Summary: %s", cal["calendar_summary"])
    for ev in cal["upcoming_events"][:5]:
        log.info("  %s in %d min", ev["name"], ev["mins_away"])
    log.info("Guinevere self-test complete.")
