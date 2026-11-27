---
name: trader-entry
description: >-
  Entry Timer for Indonesian stocks (IDX, long only) and spot forex (long and
  short). Watches a setup bar by bar on free Yahoo 1-minute or 5-minute bars
  and calls the entry on the first completed bar that CLOSES past the opening
  range or a given level, with an optional volume check. Writes trader/entry.json
  for /trader-exit. Never places an order. Use when the user says "tell me when
  to get in", "watch BBCA", "has it broken out", "entry signal", "time my
  entry", "kapan masuk", "pantau BBCA", "sinyal entry", "sudah breakout", or
  after /trader-scanner and /trader-news, before /trader-exit.
argument-hint: "[TICKER] [--setup orb|level] [--interval 5m|1m] [--side buy|sell]"
---

# trader-entry

The Entry Timer turns a setup into one moment: the bar that confirms it. It
reads bars, 1-minute or 5-minute, and waits for each one to finish. A price
that pokes above the high in the middle of a bar is not an entry. A bar that
CLOSES above it is. Then it says the time and the price, writes them down for
the Exit Planner, and stops. It never buys anything. Day trading loses most
people money, and a clean signal does not change that.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-entry` in this repo, `.agents/skills/trader-entry` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/entry.py" check BBCA                  # 15-minute opening range, 5-minute bars
python "<skill-dir>/entry.py" check BBCA --write          # also save trader/entry.json
python "<skill-dir>/entry.py" check BBCA --setup level --level 9900
python "<skill-dir>/entry.py" check BBCA --interval 1m --min-volume-x 1.5
python "<skill-dir>/entry.py" watch BBCA --until 15:30    # one line per closed bar, stops on the trigger
python "<skill-dir>/entry.py" check EURUSD --side sell --session london
python "<skill-dir>/entry.py" watchlist                   # every hit in trader/watchlist.json
```

Other flags: `--or-minutes N` (default 15), `--json`, `--offline FILE` (a
saved Yahoo chart JSON, `.json` or `.json.gz`, or a folder of
`<TICKER>.json`), `--now "2026-11-23 10:15"` (WIB) to replay a day.
`watch` with `--now` or `--offline` runs on a simulated clock and replays the
day bar by bar without waiting.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/watchlist.json` | the scanner's hits (`hits[].symbol`), for `watchlist` |
| `trader/config.json` | `no_entries_before` (09:15) and `no_entries_after` (15:30), WIB. Optional |
| Yahoo chart API | today's bars, `range=1d&interval=5m` (or `1m`): free, unofficial, can lag |
| `trader/entry.json` | with `check --write`, or when `watch` triggers: symbol, setup, status, time, bar, price, level, opening range |

## The rule

- **Opening range (orb).** The high and low of the first 15 minutes: the
  09:00, 09:05 and 09:10 WIB five-minute bars, or fifteen 1-minute bars. The
  level to beat is the range high.
- **Level.** A price you give, like a 20-day high from `/trader-scanner`.
- **The trigger** is the first completed bar after the range that CLOSES
  above the level. A wick above is not a trigger. A close exactly at the
  level is not above it.
- **The time** is that bar's close time (the 09:30 bar closes at 09:35 WIB).
  The price is its close, on a valid IDX tick.
- **Only closed bars count.** A bar is closed when the clock passes its start
  plus 5 (or 1) minutes and Yahoo has caught up to that moment (it waits a
  minute at most). Yahoo's live tick, like 10:49:45, is never a bar.
- **Volume, if you want it.** `--min-volume-x 1.5` also needs the trigger
  bar's volume at 1.5 times the range bars' average.
- **Time limits.** No entries before `no_entries_before` (09:15 WIB), during
  the lunch break (Mon-Thu 12:00-13:30, Fri 11:30-14:00 WIB), or after
  `no_entries_after` (15:30 WIB).
- **What it says.** Waiting (and how far the last close is from the level),
  triggered, expired, or no data. Before 09:00 WIB: not open yet. Before 09:15
  WIB: the range is still forming. Weekends and IDX holidays: the market is
  closed.

## Steps

1. Get the symbol from the user, or run `entry.py watchlist` after
   `/trader-scanner`. Check `/trader-news` for it first.
2. Run `entry.py check SYMBOL`. Tell the user the status in one line:
   waiting and how far, triggered at what time and price, or expired.
3. To wait for it, the agent can run `entry.py watch SYMBOL --until 15:30` in
   the background, or `entry.py check SYMBOL --write` on a `/loop` every 5
   minutes. `watch` wakes just after each bar closes, prints one line per
   bar, and exits 0 on the trigger (it writes `trader/entry.json`) or 1 when
   the setup expires. Keep the computer awake while it watches: a sleeping
   laptop pauses it, and it catches up, late, when it wakes.
4. When it triggers, say the time and the price, and that nothing was placed.
   If the trigger is more than a bar old, say that too: a late entry is a
   different trade.
5. Hand off to `/trader-exit` to set the stop and the target BEFORE anything
   is bought.

## Example

BBCA, Monday 2026-11-23, 5-minute bars. The opening range (09:00-09:15 WIB) is
Rp 5.425 to Rp 5.500. While the 09:30 bar is still forming, it waits:

```
WAITING  last close Rp 5.475 (09:25 bar), Rp 25 under the range high Rp 5.500 (-0.45%).
The 09:30 bar is still forming (Rp 5.550 so far, closes 09:35 WIB); it does not count until it closes.
```

At 09:35 WIB the bar has closed:

```
BBCA  Mon 2026-11-23 09:35 WIB  opening-range breakout (15-minute range) on 5-minute bars (Yahoo, free, can lag)
Opening range 09:00-09:15: high Rp 5.500, low Rp 5.425 (3 of 3 bars).
TRIGGERED 09:35 WIB at Rp 5.550: the 09:30 bar (bar 6) closed above the range high Rp 5.500 (+0.91%).
This is the moment to get in, if you take the trade. Nothing was placed.
Next: set the stop and target BEFORE you buy: /trader-exit (exit.py plan --from trader/entry.json).
```

With `--min-volume-x 1` the 10:10 bar is too thin (0.60x the range's volume)
and the trigger moves to 09:55 WIB at 5575 (the 09:50 bar, 7.98x).

## Rules

- Bar by bar, on free Yahoo 1-minute or 5-minute bars. They are unofficial
  and can lag. Say so when a minute matters.
- A signal is information, not an order, and not a promise. Nothing here
  promises winning trades or money.
- IDX is long-only; forex supports `--side sell` (short) when `"allow_short": true` and `--session london|newyork`.
- One trigger per setup per day: the first close above. Later closes do not
  reset it.
- Never call an entry early because a bar looks like it will close above.

## What it never does

It never places an order, never sizes a position, never sets the stop (that
is `/trader-exit`), never moves the level after the fact, and never counts a
bar that has not closed. It never runs `/trader-broker` from a background
watch: nobody is there to say yes.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables, never in the chat.
