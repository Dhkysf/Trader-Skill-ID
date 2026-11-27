---
name: trader-alerts
description: >-
  Price Alerts for Indonesian stocks (IDX) and spot forex. Rings when a price,
  stop, target, percent move, flat-by time, or opening bell hits. Turns
  trader/plan.json into three alerts in one go, knows IDX hours and 2026
  holidays plus 24/5 forex hours, fetches free Yahoo quotes, and writes
  trader/prices.json for sizing and risk checks. Use when the user says
  "alert me when", "tell me if BBCA hits", "watch my stop", "is the market
  open", "pasang alert", "ingatkan saya", "apakah bursa buka", or right after
  /trader-exit writes a plan.
argument-hint: "[ticker] [price]"
---

# trader-alerts

Price Alerts watches the numbers so the user does not have to stare at a
chart. An alert is information, never an order: when a stop alert rings,
nothing is sold by this skill. With a bracket order the stop-loss and the
take-profit already sit at the broker and do the work; the alerts tell the
user what happened and when it is time to be flat.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-alerts` in this repo, `.agents/skills/trader-alerts` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/alerts.py" clock                          # IDX open or closed, next open
python "<skill-dir>/alerts.py" add --from-plan                # stop, target, flat by close from trader/plan.json
python "<skill-dir>/alerts.py" add --opening-bell
python "<skill-dir>/alerts.py" add --symbol BBCA --stop 8800
python "<skill-dir>/alerts.py" add --symbol BBCA --target 9200
python "<skill-dir>/alerts.py" add --at 15:45 --label "flat by close" --before-close
python "<skill-dir>/alerts.py" add --symbol TLKM --pct 3
python "<skill-dir>/alerts.py" check                          # exit 0 = something rang
python "<skill-dir>/alerts.py" quote BBCA --write             # -> trader/prices.json
python "<skill-dir>/alerts.py" quote --holdings --write       # portfolio + plan tickers
python "<skill-dir>/alerts.py" list
python "<skill-dir>/alerts.py" reset bbca-plan-stop
```

`--now "2026-11-23 15:45"` pins the clock (WIB); `--offline DIR`
reads saved quote files instead of the network.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the trade from trader-exit, for `add --from-plan` |
| `trader/alerts.json` | the rules (`alerts.example.json` in this folder) |
| `trader/state/alerts.json` | which rules rang and when, so each rings once |
| `trader/prices.json` | the latest quotes, merged in, for trader-budget and trader-risk |
| `trader/portfolio.json` | the tickers held, for `quote --holdings` |

## Rule types

| type | rings when | rings again |
| --- | --- | --- |
| `above` / `target` | price at or above `price` | after `reset`, or on its own if `"rearm": true` and the price fell back |
| `below` / `stop` | price at or below `price` | same |
| `pct_move` | moved `pct` percent from the previous close (or `ref`), optional `direction` up or down | once per day at most |
| `time` | the WIB clock passed `at` ("15:45") on a trading day | once per trading day |
| `opening_bell` | IDX is open | once per trading day |

A rule with `"date"` is watched on that WIB date only; `--from-plan`
rules carry the plan's date, so yesterday's stop never rings today.

## Quotes

- `yahoo` (default): `query2.finance.yahoo.com/v8/finance/chart/<TICKER>` (e.g.
  `BBCA.JK`), an unofficial free JSON endpoint, one request per ticker, half a
  second apart. On a 429 it waits and tries once more; on a 429 or a 5xx
  after that it tries `query1`. It identifies itself as `day-trader-skill/2.0`.
- Free quotes are unofficial, delayed and can lag. They are fine for alerts
  and for checking a size, not for timing an order. The broker's price is the
  one that fills. Each price in `trader/prices.json` keeps its quote time, and
  trader-risk only uses one under 15 minutes old.
- If Yahoo is down, enter the latest price from your broker app into
  `trader/prices.json` as `{"as_of": "...Z", "prices": {"BBCA": 9875}}`.

## The IDX clock

Regular sessions: Mon-Thu 09:00-12:00 and 13:30-15:50 WIB, Fri 09:00-11:30 and
14:00-15:50 WIB. Closed on weekends and on 2026 IDX holidays in
`skills/trader-core/markets/idx.json`.

WIB is UTC+7 year-round (no daylight saving time), worked out in the tool so it
ignores the computer's own zone. For any other year it notes that the holiday
list is unknown.

## Steps

1. Right after trader-exit writes the plan, run `add --from-plan`. Confirm
   the three alerts back to the user: the stop, the target and the flat-by time.
2. Run `check` while the trade is open: every few minutes from a
   scheduled task or `/loop`. Each run fetches only the tickers in today's
   rules and rings each alert once. A check reads the latest delayed quote;
   it is not a live feed, and a price can pass a level between two checks.
3. Tell the user what rang in one line each. A stop or target alert means the
   bracket order has probably filled: check your broker app and record the fill
   with trader-broker. "Flat by close" means close anything still open:
   trader-broker `flatten`, then trader-risk, then the user's yes. Never act
   for them.

## Example

BBCA on Monday 2026-11-23: entry Rp 9.875 at 09:35 WIB, stop Rp 9.775, target
Rp 9.975, flat by 15:45. `add --from-plan` writes `bbca-plan-stop`,
`bbca-plan-target` and `bbca-flat-by` for that day. A `check` at 10:53 reads
a quote of Rp 9.900, between the stop and the target:

```
IDX OPEN (2026-11-23 10:53 WIB, session 1).
Nothing hit. 3 rule(s) watched today, BBCA Rp 9.900.
```

At 15:45 WIB:

```
ALERT Flat by close: it is 15:45 WIB (set for 15:45), the market closes at 15:50. If BBCA is still
open, close it: trader-broker flatten --symbol BBCA builds the sell ticket, then trader-risk and your yes.
```

It rings once. The next morning the plan's three alerts are no longer
watched; with `add --opening-bell`, the bell rings at 09:00 WIB.

## Rules

- An alert is a fact about a price or the clock. Say it as a fact.
- Never present a quote as live. Free quotes are delayed and unofficial.
- Confirm every new rule back to the user: ticker, type, level, day.

## What it never does

It never places, cancels or changes an order, never claims a quote is
live, and never predicts where a price is going.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables, never in the chat.
