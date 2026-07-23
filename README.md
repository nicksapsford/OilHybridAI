# OilHybrid A.I. — Albion Trading Desk
**Version:** 1.0.0 | **Port:** 5045 | **Status:** Paper Trading | **Part of:** Hybrid Desk

Part of the Albion **Hybrid Desk**. OilHybrid is a **Type 2 SURGICAL hybrid** — cloned
from OilTrader v1.3.1, Arthur STILL gates every entry and manages exits (NOT a
Lancelot-entry hybrid), with two evidence-based changes from Gaius Commission 008:

1. **Extended-rally filter (primary fix).** A new Lancelot pre-check "Not Extended"
   blocks a new LONG when Brent is > **$2.50 above** the Asian-session open (22:00 UTC),
   and a new SHORT when > $2.50 below it — so Arthur can't chase the top of a mature move
   (the failure that lost £37 on 22 Jul). Session open = first valid price at/after 22:00
   UTC, reset daily. The dashboard shows the live extension; the Archie Brief reports it.
   Threshold $2.50 — review after 20+ OilHybrid trades.
2. **Morgan warning + MANUAL reset (not an auto-floor).** Morgan tracks freely and may
   drop below 50; when it does, the dashboard shows a "⚠️ MORGAN BELOW FLOOR" warning + a
   "RESET MORGAN TO 50" button and the Archie Brief flags it. Nick reviews the evidence
   and consciously resets (via `/api/reset-morgan`, applied live). Desk-wide hybrid
   principle: warning + manual reset, never an automatic floor.

Everything else is identical to OilTrader v1.3.1: Arthur entry+exit, 1.5pt stop / 3pt
target / £13.33/pt, session 22:00-21:00 UTC, Morgan SHORT gate ≥65, Guinevere news,
Profit Protection Ladder, **full phantom logging**, 5-min polling.

**Market:** Brent Crude — Capital.com (OIL_BRENT)
**Broker:** Capital.com demo (Z6CJSM, £1,000 virtual)
**Theme:** Crude Orange #FF6600

## The Team (Arthurian Naming)
| Role | Name | Function |
|------|------|----------|
| AI Brain | Arthur | Claude AI decision engine |
| Data Feed | Merlin | Brent Crude price + indicators |
| Pre-checks | Lancelot | Entry validation + EIA calendar |
| Broker | Excalibur | Capital.com connector |
| Calendar | Guinevere | Economic calendar + Oil news sentiment |
| Performance | Morgan | P&L tracker + confidence |
| Watchdog | Galahad | Auto-restart |
| Notifier | Percival | Pushover alerts |
| Trader | Stanley | Paper trade execution |

## Guinevere News Module
Monitors real-time oil news via Currents API.
Keywords: Hormuz, OPEC, Iran, sanctions, tanker,
          supply, pipeline, crude, Brent.
Sentiment: BULLISH / BEARISH / NEUTRAL
Confidence adjustment: +8 / -8 / 0

## EIA Inventory Calendar
Weekly Petroleum Status Report — every Wednesday 15:30 UTC.
Caution flag active 15:00-16:00 UTC on Wednesdays.

## Phantom P&L Tracker
Records every STAY OUT decision with hindsight scoring.
Data saved to: logs/phantom_trades.csv

## API Key Setup
Add your Currents API key to .env:
  CURRENTS_API_KEY=your_key_here
Never commit .env to GitHub.
