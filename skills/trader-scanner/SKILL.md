---
name: trader-scanner
description: >-
  Chart Scanner. Scans thousands of charts for setups: opening-range
  breakouts, flags, oversold bounces. Builds the list of Indonesian stocks
  (IDX) from a local Daftar Saham CSV or watchlist,
  runs a pre-market scan of daily closes (20-day closing-high breakout, bull
  flag, reclaimed the 20-day average, oversold, oversold bounce) and an
  intraday opening-range breakout scan on 5-minute bars, then writes
  trader/watchlist.json for trader-news and trader-entry. Free Yahoo data,
  bar by bar. Use when the user says "scan the market", "find me setups",
  "what is breaking out", "opening range breakouts", "scan for bull flags",
  "oversold stocks", "pre-market scan", "build my watchlist", "what should I
  look at today", or at the start of a trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner

The Chart Scanner is the first step of a day trade. It reads thousands of
free charts and lists the ones that match a rule. That is all it does. A scan
is a list of charts that match a rule, not a list of stocks to buy, and a
setup on a chart is not a prediction. Most people who day trade lose money;
the scanner does not change that. It only saves you from flipping through
5,000 charts by hand.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-scanner` in this repo, `.agents/skills/trader-scanner` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/scan.py" universe --from data/daftar-saham.csv # -> trader/universe.txt
python "<skill-dir>/scan.py" daily                          # before the open -> trader/watchlist.json
python "<skill-dir>/scan.py" daily --symbols BBCA,BBRI,BMRI  # or --watchlist FILE, --limit 200
python "<skill-dir>/scan.py" orb                            # after 09:20 WIB -> trader/watchlist.json
python "<skill-dir>/scan.py" orb --at 09:35                 # cut the clock at 09:35 WIB
python "<skill-dir>/scan.py" orb --watchlist trader/watchlist.json --json
```

Flags: `--min-price 100` and `--min-volume` (daily 1,000,000, orb 0),
`--or-minutes 15`, `--max-confirm 200` (orb stage 2),
`--now "2026-11-23 10:15"` (WIB) to pin the clock, `--offline PATH`
to read saved Yahoo files, `--no-write`, `--show N`, `--json`. Exit code 0
when the scan found something, 1 when it found nothing or could not run (the
reason is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]`. trader-news and trader-entry read `hits[].symbol` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 15:30) |

## The universe

`universe --from data\daftar-saham.csv` reads a local IDX Daftar Saham CSV
(comma or semicolon separated) or plain text list and writes
`trader/universe.txt` (`SYMBOL|Name`):

1. Drops `Pemantauan Khusus` rows.
2. Keeps plain 4-letter IDX stock codes (e.g. `BBCA`, `BBRI`, `TLKM`).

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request. Liquidity comes
from the spark meta: last price at least `--min-price` (default `100` IDR) and
last session's value (price x volume) at least `min_value_idr` (`5,000,000,000`).
Run it before the open or after the close: during the session the volume is the
day's so far, and today's daily bar is left out until 16:00 WIB.

The setups are computed from daily closes only (spark has no highs or lows):

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

Hits are listed most traded first (price times volume).

## The opening-range breakout scan (during the session)

The opening range is the first `--or-minutes` (15) of the session: the 09:00,
09:05 and 09:10 WIB five-minute bars. A hit is the first completed 5-minute bar
to CLOSE above the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars, 20 a
   request. A chart goes on only if a completed bar after the range closed at
   or above the highest close of the range. That is a necessary condition
   (the range high is at least every range close), so no breakout is lost.
2. Stage 2, each candidate: the v8 chart with real highs and lows, one
   request each. Range high = the highest high of the range bars, range low =
   the lowest low. Stage 2 checks at most `--max-confirm` (200) of them, the
   most traded first (price times volume so far), and prints PARTIAL with the
   count it skipped. `--max-confirm 0` checks them all.

For a fast answer, scan the daily watchlist or a list of names you trade
(`--watchlist`, `--symbols`).

A chart is usable only when every 5-minute bar from 09:00 WIB to the cutoff is
there; a missing bar means a halt or a thin stock. Null closes are dropped,
a bar off the 5-minute grid (the live tick, like 10:58:07) is dropped, and a
bar counts only once it is complete (start + 5 minutes). Before 09:20 WIB, during
the lunch break, on a weekend or IDX holiday, after the 15:50 WIB close, or
after `no_entries_after` (an expired setup) it prints one plain line and writes
nothing.

## Data and limits

- Yahoo's chart and spark endpoints are free, unofficial and can lag. Bars are
  5-minute bars, bar by bar, never tick by tick. query2 first, query1 on a 429
  or 5xx, one retry after a 5-second wait on a 429.
- Partial results are said as partial: "Fetched 820 of 900 charts (80
  failed or had no data)". Never round a partial scan up to "the whole market".
- IDX holidays for 2026 are in `skills/trader-core/markets/idx.json`.
- IDX (`"market": "idx"` in `trader/config.json`): `universe --from data\daftar-saham.csv`
  reads a local IDX Daftar Saham CSV (comma or semicolon separated, dropping
  `Pemantauan Khusus` rows) or plain text list. `daily` defaults to
  `--min-price 100` and `min_value_idr` 5,000,000,000 (price x volume). `orb`
  starts at 09:00 WIB and skips the lunch break. Every IDX scan prints the
  10-minute Yahoo delay notice.

## Steps

1. Once a week or so: `scan.py universe --from data/daftar-saham.csv`.
2. Before the open: `scan.py daily`. Tell the user the counts (fetched,
   liquid, scanned, hits) and the top few by setup.
3. After 09:20 WIB (09:35 is the classic): `scan.py orb`. Tell the user how
   many usable charts broke their range and when, and that a later hit is
   closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news TICKER` (what is moving
   it), then `/trader-entry TICKER` (the entry bar by bar). Never pick for them.

## Example

Monday 2026-11-23, scan at 10:15 WIB over IDX watchlist (`--offline`):

```
python scan.py orb --offline BBCA_5M --now "2026-11-23 10:15"
Fetched 1 of 1 charts; 1 usable; 1 candidates, 1 confirmed with real highs and lows.
1 of 1 charts closed above their opening-range high by 10:15 WIB:
  09:35 WIB  BBCA   Rp 5.550  range Rp 5.425 to Rp 5.500  +0.91% over
```

BBCA's opening range is the 09:00 to 09:10 WIB bars (high Rp 5.500, low Rp 5.425);
the 09:30 bar closed at Rp 5.550, 0.91% over the high, at 09:35 WIB. The user
picks BBCA and the agent hands it to `/trader-news BBCA`, then
`/trader-entry BBCA`.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many
  were usable, and the time of the data.
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure.
- A hit is stale once the price has moved on. Re-run before acting on it.

## What it never does

It never places, sizes or checks an order, never says which stock to buy,
never calls data real time, and never promises that a setup works.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables, never in the chat.
