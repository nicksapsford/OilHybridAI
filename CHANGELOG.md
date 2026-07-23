## [1.0.0] - 2026-07-23  —  OilHybrid fork (Type 2 surgical hybrid)
### Added — OilHybrid, Hybrid Desk system (port 5045), cloned from OilTrader v1.3.1
Implements Gaius Commission 008 (Oil System Review). A SURGICAL hybrid: Arthur STILL
gates entry and manages exits (NOT a Lancelot-entry hybrid). Two changes:

- **Extended-rally filter (Change 1).** New Lancelot pre-check `check_not_extended`
  ("Not Extended") in `pre_checks_oil.py`: blocks a new LONG when price is > $2.50
  (`EXTENDED_LIMIT`) above the Asian-session open, a new SHORT when > $2.50 below it.
  `main_oilhybrid.py` tracks the session-open price (first valid tick at/after 22:00 UTC,
  labelled by session-end day, reset each session) and passes `current_price` +
  `session_open_price` to the pre-checks; the state exposes `session_open`/`extension`/
  `extended_limit`. Dashboard shows a green/red EXTENSION line in the Lancelot panel;
  Archie Brief adds an "EXTENDED RALLY FILTER" section. Review $2.50 after 20+ trades.
- **Morgan warning + manual reset (Change 2).** `performance_oil.py`: `morgan_below_floor`
  / `last_morgan_reset` helpers; perf dict exposes `morgan_below_floor` / `morgan_raw` /
  `morgan_last_reset`. Dashboard shows a red "⚠️ MORGAN BELOW FLOOR" warning + "RESET
  MORGAN TO 50" button (only when <50) + last-reset timestamp; new `/api/reset-morgan`
  endpoint (writes confidence_lift.json + morgan_last_reset.json) applied live by the
  engine (which now also `invalidate_cache()`s after a lift). Archie Brief flags it.
  NO automatic floor — Morgan tracks freely; Nick resets consciously.
- Port 5045, Crude Orange #FF6600 (unchanged). Phantom logging + all pages retained.
  Repo nicksapsford/OilHybridAI. Appears on HybridRoundTable (5050) automatically.
  OilHybrid P&L − OilTrader P&L isolates the value of the two changes.

## [1.2.7] - 2026-07-20
### Added -- Snag 19: recent phantom rows in the Archie Brief
- The Archie Brief now lists the **last 5 phantom rows** (newest first) directly under
  the STAY OUT QUALITY summary, so Archie sees overnight phantom activity inline without
  a separate PHANTOM-page screenshot. Columns: Date/Time (UTC), Direction, Confidence,
  1hr Move, Verdict. PENDING rows shown as PENDING; empty -> "No phantom data yet".
  Display only -- reads the same stay_out_quality decisions; no logic/threshold change.

## [1.2.6] - 2026-07-19
### Changed -- Macro Sentiment Live Reload (required before go-live)
- `get_macro()` now re-reads `macro_sentiment.json` fresh from disk on every Arthur
  consultation instead of caching for 5 min at startup. Changing the macro flag on
  RoundTable (e.g. NEUTRAL -> RISK_OFF) now takes effect on the next consultation --
  within one candle interval, NO restart, open positions unaffected.
- A 5-second debounce coalesces the several get_macro() calls made within a single
  consultation (fetch_sentiment / format_news_context / regime_block) so it doesn't
  hammer disk. Weighting logic unchanged -- overlay still feeds Arthur as context +
  directional sentiment only; Arthur makes every call.

## [1.2.5] - 2026-07-19
### Added -- dedicated PHANTOM page (desk rollout, template CryptoTrader v1.7.3)
- New **PHANTOM &rarr;** header button opens page 4: "PHANTOM TRADES -- Stay Out Quality"
  with a summary (Quality %% / Correct / Wrong / Neutral / Net Saved / Net Missed) and a
  clean **last-20** table (newest first): Date/Time UTC | Direction | Entry Price |
  Confidence | 1hr Move | colour-coded Verdict. Back to Dashboard + Trading nav.
- The right-panel Stay Out Quality card is now a **compact** clickable summary that opens
  the full page. Standardised to the last 20 rows (was 10). Display only -- reads the same
  get_stay_out_quality() data; no threshold/logic/recording change.

## [1.2.4] - 2026-07-18
### Changed -- Guinevere moved to a dedicated page (display only)
- The full Guinevere section (news sentiment + keyword editor) now lives on a dedicated
  page reached via a **GUINEVERE** button in the header (same pattern as P&L), with a
  "Back to Dashboard" link. This fixes the editor overlapping the main grid and the
  ADD BEARISH button falling below the visible area in the narrow right panel.
- The main dashboard right panel now shows a **compact** Guinevere summary (sentiment +
  score + top headline) that opens the full page on click. No trading-logic change.

## [1.2.3] - 2026-07-18
### Fixed -- Snag 17: session-aware liquidity countdown
- The dashboard countdown now shows the CURRENT open session and counts down to the
  next boundary (e.g. "OVERLAP (open) -- NEW YORK in 3:49:00") instead of only naming
  the next session, which read as if the market were shut (same root cause as USTrader
  Snag 13). Boundaries now mirror `data_feed_oil.get_liquidity_period` EXACTLY --
  added CLOSING (20:30), the 21:00-22:00 daily break, the 22:00 ASIAN reopen, and a
  Fri 21:00->Sun 22:00 weekend-closed state. NY session opens 17:00 UTC (OVERLAP 13:00-17:00).

## [1.2.2] - 2026-07-18
### Added -- Macro Sentiment Overlay reader (Guinevere Part 4)
- **`get_macro()` / `get_macro_adjustment()` / `get_macro_context()`** in `guinevere_news.py`:
  read RoundTable's `logs/macro_sentiment.json` (5-min cache) and apply this system's macro
  nudge to the final Guinevere sentiment score (RISK_ON +1).
- Macro flag + this system's adjustment now appear in Arthur's prompt context.
- CRISIS raises Arthur's confidence bar by 10 (trade more conservatively) desk-wide.

## [1.2.1] - 2026-07-18
### Added -- Guinevere live keyword editor (Guinevere Part 3)
- **Dashboard keyword editor** below the Guinevere news panel: BULLISH / BEARISH
  sections with removable pills, per-section add inputs, and a Save button. Edits
  apply LIVE -- Guinevere re-reads `logs/guinevere_keywords.json` every 5 min, no restart.
- **New `/api/keywords` route** (GET current lists, POST to save) in `dashboard_oil.py`.
- **`save_keywords()` + `_log_keyword_change()`** in `guinevere_news.py`: dedupes/strips,
  writes the keywords file, refreshes the 5-min cache immediately, and logs every
  add/remove to `logs/guinevere_keyword_changes.log`
  (`[ISO8601Z] ADDED/REMOVED "kw" (BULLISH|BEARISH) by Nick`).
- "Keywords last updated" indicator shows the last save timestamp (UTC). Data-only
  files (`logs/`, gitignored); no trading-rule change, no backtest required.

## [1.2.0] - 2026-07-18
### Changed -- OilHybrid System 5 Review: bidirectional + tight risk + Guinevere-aware
Backtest-provisional; 4-week review. Nick sign-off. Follows the 18 Jul threshold fix
(v1.1.18) that unblocked Morgan (now learning, ~52.5 -- left untouched here).

- **Bidirectional (Change 1):** direction from the daily SSL + Morgan SHORT regime in
  `main_oilhybrid` -- BULL -> LONG; BEAR + Morgan SHORT >= 65 -> SHORT; BEAR + Morgan
  SHORT < 65 -> STAY OUT (no short history; do not force shorts). New separate
  **Morgan SHORT confidence** (`performance_oil.get/set_short_confidence`,
  `logs/morgan_short_confidence.json`, init **30**). `check_ssl_agreement` now requires
  **1h AND 5m** SSL to match direction. The daily-trend filter was already direction-relative.
- **Risk (Change 2):** `TRAILING_STOP_POINTS` 5 -> **1.5**, `TAKE_PROFIT_POINTS` 25 -> **3.0**
  (2:1 R:R). Whipsaw backtest (BZ=F 60d 5m): 1.5pt stop = 2.0%% whipsaw; Brent median 30-min
  move 0.20pt, max live move ever 3.64pt. Sizing is risk/stop, so **stake auto-jumps £4 ->
  £13.33/pt** -- P&L now moves ~3x faster. Spread 0.034 unchanged.
- **Profit ladder (Change 3):** recalibrated to **£8->£6, £16->£13, £28->£24**.
- **Guinevere logging (Change 4):** `guinevere_score` now written to phantom rows
  (`build_snapshot(guinevere_score=fetch_oil_sentiment()["score"])`) -- was blank on all 102.
- **Arthur prompt (Change 5):** rewritten bidirectional/geopolitics-aware (8 elements:
  philosophy, direction awareness, risk params, Guinevere awareness, EIA awareness, point
  convention 1.5/3, profit ladder, SHORT gating). Live regime/Morgan-SHORT/Guinevere injected
  per tick; `get_trading_decision` gained `morgan_short` + `proposed_direction`.

## [1.1.18] - 2026-07-18
### Fixed -- phantom verdict threshold (System 5 Review, Rec 1)
- **`VERDICT_THRESHOLD` 2 -> 0.5** ($/bbl, on the 1hr window). The 2pt threshold (itself
  down from an inherited 10pt) was still far too coarse for Brent: of 102 phantom rows,
  0% reached 2pt at 30min, 1% at 1hr, 7.8% at 2hr, so 102/102 verdicts were NEUTRAL and
  Morgan (flat at 50.0) had zero learning signal. At 0.5pt ~44% of 1hr windows classify.
- **Retrospective re-score:** all 102 existing phantom rows re-scored to 0.5pt on the 1hr
  window (one-off): NEUTRAL 102 -> CORRECT 25 / WRONG 20 / NEUTRAL 57 (45 rows changed,
  44.1% now classified). Gives Morgan an immediate historical dataset. Data-only change
  in logs/ (gitignored): backup phantom_trades_pre_rescore_20260718.csv, summary
  phantom_rescore_20260718.txt. No trading-rule change; no backtest required.
  Note: desk-wide threshold mis-scaling assessed separately (Gas/Gold/FTSE/US/Crypto
  proposals reported to Nick; not yet applied).

## [1.1.11] - 2026-07-16
### Fixed
- Snag 9: confidence bar could display 50 when the real Morgan score was 0. The
  dashboard read `perf.confidence_score || 50`, and JS treats 0 as falsy, so a
  legitimate 0 was replaced by the 50 fallback. Changed to
  `(perf.confidence_score != null ? perf.confidence_score : 50)` -- 0 now shows as
  0; 50 is used only when the value is genuinely absent. In practice only GasTrader
  showed the wrong value (the only system with a 0 score, from a 5-loss streak); the
  latent bug was in all 6 dashboards. RoundTable was already correct.

## [1.1.10] - 2026-07-16
### Fixed
- Spread correction (Nick sign-off): SPREAD_POINTS 0.3 -> 0.034 ($/bbl), the confirmed
  Capital.com Brent demo spread. Deducted from P&L before the verdict/threshold
  comparison. No other changes today.
## [1.1.9] - 2026-07-16
### Changed
- Job 4 (Nick & Archie, 16 Jul 2026): phantom NEUTRAL verdict threshold lowered from
  10 points ($10/bbl) to 2 points ($2/bbl) -- ~40% of the 5-point stop, proportional to
  Brent's real hourly volatility ($0.50-$1.50; median daily range $3.46). The old $10
  threshold (inherited from a more volatile scale) made every signal NEUTRAL (95/95),
  leaving OilHybrid unassessable by Gaius and unable to teach Morgan. Applies to the 1hr
  verdict (OilHybrid's phantom tracker has a single verdict horizon). NEW verdicts only:
  PENDING rows resolving from now on + future rows. Existing rows are NOT changed
  (resolve_stale_pending only recomputes PENDING rows; all 95 existing rows are already
  resolved NEUTRAL). Spread (~0.30 pts) is already deducted from P&L before comparison.
## [1.1.8] - 2026-07-16
### Fixed
- Job 3 (Gaius Commission 001, Priority 3): OilHybrid had no morgan_confidence.csv, so
  Morgan read the 50/MEDIUM fallback and could not persist. Root cause: the file is
  only written by set_confidence(), which fires on a CORRECT/WRONG phantom verdict or
  on startup-restore when a value already exists -- OilHybrid had only NEUTRAL phantom
  verdicts and no prior file, so neither path ever ran. The startup restore's
  no-saved-value branch only logged the baseline without writing. Fix: initialise
  morgan_confidence.csv at the baseline on startup when none exists
  (set_confidence(get_confidence(), reason='init')). The Morgan module itself was
  correct and active; the phantom-verdict feedback loop is intact and will adjust the
  score once non-NEUTRAL verdicts arrive.

## [1.1.7] - 2026-07-16
### Added
- Job 1 (Gaius Commission 001, Priority 1): indicator snapshot at signal time in
  phantom_trades.csv. 17 columns APPENDED to the right of the existing 14-col schema
  (existing positions unchanged): ssl_daily/1hr/5min, rsi_daily/1hr/5min,
  tmo_1hr/5min, macd_1hr/5min, chande_mo_1hr/5min, money_flow_1hr/5min, morgan_score,
  session, guinevere_score. Captured from values Merlin already fetched for Arthur
  (no new data fetch) via phantom_tracker.build_snapshot() -> record_decision(indicators=).
  The snapshot build is wrapped in its own try/except so a failure can never stop a
  phantom row being written. phantom_tracker now migrates an older 14-col file in place
  on first use (old rows keep positions; new columns blank). Chronicle & Gaius read by
  column name and are unaffected. (guinevere_score currently blank pending a safe cached
  source -- column reserved.)

# OilHybrid A.I. Changelog

## [1.1.6] - 2026-07-14
### Fixed
- Morgan confidence (perf.confidence_score) now included in the lightweight always-running
  dashboard push (_push_dashboard_live), so /api/state exposes it in ALL market states --
  including the 21:00-22:00 UTC break. Previously perf was only pushed on full candle ticks
  (skipped when the market is closed), so RoundTable / Gaius / Chronicle showed null
  confidence out of hours. Matches CryptoTrader (performance in every push).

## [1.1.5] - 2026-07-13
### Changed
- Bug A (Nick sign-off): re-scaled stop/target for real Brent (~$80/bbl). TRAILING_STOP_POINTS 45 -> 5 ($5/bbl, ~1.4x median daily range $3.46, whipsaw ~15%); TAKE_PROFIT_POINTS 225 -> 25 ($25/bbl, 5:1 R:R). Prior 45/225 were calibrated for a ~$4000 oil scale and never triggered (0% stop/target hits in backtest; all force-closes).
- Updated agent_brain_oil.py stop/target/stake references (5pt stop, £4.00/pt, 25pt target) and REMINDERS.txt RISK/SIZING to match.
- Removed $4,155 oil-scale artefacts from strategy_oil.py and paper_trader_oil.py self-tests (now real ~$80 Brent prices).
### Note
- Standing Saturday-review item: monitor OilHybrid stop/target performance as signal-aligned trade data accumulates; adjust if warranted.

## [1.1.4] - 2026-07-13
### Fixed
- Bug B: open-position floating (unrealised) P&L now computed and exposed to RoundTable (`unrealised_gbp`, spread-inclusive) — previously the open position showed no P&L, only realised daily.
- Bug C: "Locked P&L" now only shows once the trailing stop trails to break-even (genuine secured profit); until then "---" (was showing a scary if-stopped loss on fresh positions).
### Changed
- Bug D: Arthur prompt now states the point convention explicitly (1 point = $1.00/bbl; never ×100) to stop cents-based "+351 points" narration.
- Bug E: epic standardised to OIL_BRENT across agent_brain_oil.py, data_feed_oil.py, REMINDERS.txt (live-verified connector_status=capitalcom). Added get_market_details() + startup logging of raw OIL_BRENT market details, and a BEFORE-GO-LIVE TODO to verify scalingFactor/onePipMeans/lot-size.
### Pending (awaiting Nick sign-off)
- Bug A: re-scale TRAILING_STOP_POINTS/TAKE_PROFIT_POINTS from 45/225 (calibrated for ~$4000 oil) to Brent reality — backtest completed, values not yet applied.

## [1.1.3] - 2026-07-12
### Fixed
- Log timestamps now emitted in UTC (logging.Formatter.converter = time.gmtime; datefmt suffixed " UTC") across main, watchdog and dashboard. Previously local/BST, causing a +1h mismatch vs the UTC CSV artefacts (phantom_trades.csv etc.).
### Added
- ALBION STANDING RULE comment blocks baked into the logging setup and the log/analysis modules (phantom_tracker.py, performance_oil.py, dashboard stay-out reader): all timestamps are UTC, never BST/local.

## [1.1.2] - 2026-07-11
### Added
- Silent launcher (pythonw -- no console windows); output to logs/console.log with daily rotation (7 days kept)
- Launcher now starts the dashboard + watchdog silently (was cmd windows)

## [1.1.1] - 2026-07-11
### Added
- Morgan confidence persistence: every confidence tick appended to logs/morgan_confidence.csv (timestamp, confidence, level HIGH>=65/LOW<=35/MEDIUM, reason) via save_confidence(); load_confidence() returns the last logged value
- set_confidence(value, reason='update') now also writes the CSV audit row after the JSON persist; restored on restart in main_oilhybrid.py (load_confidence() -> set_confidence(saved, reason='restore'), else baseline-50 log)
- Guinevere sentiment persistence: every fetch_oil_sentiment() result appended to logs/guinevere_sentiment.csv (timestamp, sentiment, score, headline_1..3, eia_window) via save_sentiment(); eia_window recorded from get_eia_calendar_status()

## [1.1.0] - 2026-07-11
### Added
- Morgan individual phantom feedback: persistent confidence store (logs/morgan_confidence.json) with get_confidence()/set_confidence(), clamped 0-100 and thread-safe under _morgan_lock
- apply_phantom_verdict_feedback() -- per-verdict confidence nudge (CORRECT +raw / WRONG -raw / NEUTRAL 0.0; raw = clamp(|pnl_1hr|/50, 0.5, 2.0))
- process_new_phantom_verdicts() -- MorganPhantomPoller daemon thread (300s) folds newly-judged phantom verdicts into Morgan's individual confidence, then marks them processed
- Reported confidence now folds in Morgan's phantom delta (get_confidence() - 50.0) separately from get_stay_out_adjustment() to avoid double-counting
- Startup hook in main_oilhybrid.py to launch the phantom-feedback poller
### Audit
- Arthur prompt (agent_brain_oil.py) audited for hardcoded win-rate/historical/backtest % figures: CLEAN -- all performance figures are injected at runtime via Morgan's perf_context; no contaminated constants found

## [1.0.3] - 2026-07-11
### Added
- Seven flat status fields merged into /api/state: lancelot_status, lancelot_fails, lancelot_fail_reasons, arthur_decision, arthur_confidence, arthur_consulted, locked_pnl (derived via compute_status_flats(), guarded so /api/state never 500s)
### Fixed
- Compact Open Position panel -- Entry/Stop/Target now use a tight two-column layout (fixed ~120px label, value immediately after) instead of wide label-left/value-hard-right

## [1.0.2] - 2026-07-10
### Fixed
- Staggered Capital.com API startup delay (45s + jitter) to prevent 429 rate limits on shared demo account (Z6CJSM)

## [1.0.1] - 2026-07-10
### Added
- phantom_tracker upgraded to match other systems (get_summary NEUTRAL/judged fix, resolve_stale_pending, start_watchdog)
- resolve_stale_pending() on startup
- start_watchdog() -- 15-min dynamic PENDING resolver
- Merlin OilDataFeed.get_historical_price() for historical lookups

## [1.0.0] - 2026-07-08
### Added
- Initial release — OilHybrid A.I.
- Cloned from GoldTrader A.I. v1.0.3
- Brent Crude (OIL_BRENT) on Capital.com
- Guinevere News module (Currents API + EIA)
- Oil news sentiment feeding Arthur's confidence
- Phantom P&L tracker (inherited from GoldTrader)
- Morgan STAY OUT quality integration
