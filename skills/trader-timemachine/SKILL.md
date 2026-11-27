---
name: trader-timemachine
description: >-
  Time Machine. Replays every possible outcome of a trade before you risk any
  money: 10,000 simulated sessions plus every past time the setup fired.
  Takes the plan from trader-exit (entry, stop, target), rebuilds the rest of
  the day 10,000 times from the stock's own 5-minute bars over the last 60
  days, and re-runs the same rule on every past session. Prints the odds of
  target first, stop first, or neither by the close, where the price sits at
  the close, the average R, the history, and one honest verdict, then hands
  off to /trader-budget. Use when the user says "run the time machine",
  "replay this trade", "what are the odds", "simulate this trade", "monte
  carlo", "backtest this setup", "how often does this hit the target", "is
  this a coin flip", or after /trader-exit writes a plan, before
  /trader-budget.
argument-hint: "[path to plan.json, or TICKER]"
---

# trader-timemachine

The Time Machine sits between the plan and the money. trader-exit has set
the entry, the stop and the target. Before anything is sized or sent, this
skill asks one question: if today plays out like the stock's own last 60
days, how often does this plan hit the target first, the stop first, or
neither? It answers with 10,000 replays and with the real record of the same
rule on every past session. It is a simulation built from the stock's own
recent bars, not a prediction. Day trading loses most people money, and a
good-looking replay does not change that.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-timemachine` in this repo, `.agents/skills/trader-timemachine` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/timemachine.py" run                    # trader/plan.json, 10,000 replays, seed 19
python "<skill-dir>/timemachine.py" run --write            # also save trader/timemachine.json
python "<skill-dir>/timemachine.py" run --until 15:45      # end each replay at your flat-by time
python "<skill-dir>/timemachine.py" run --json
python "<skill-dir>/timemachine.py" run --symbol BBCA --date 2026-11-23 \
    --entry 5550 --stop 5425 --target 5800 --entry-time "09:35"
python "<skill-dir>/timemachine.py" chart --from           # ASCII fan chart of the saved run
```

Other flags: `--replays N`, `--seed N` (default 19), `--window N` (default 2
bars), `--offline FILE` (a saved Yahoo chart JSON, `.json` or `.json.gz`),
`--now "2026-11-23 10:15"` (WIB) to pin the clock.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/plan.json` | the plan from trader-exit: symbol, date, entry, entry_time / entry_bar, stop, stop_rule, target, target_r, opening range |
| Yahoo chart API | one request: 60 days of 5-minute bars (`range=60d&interval=5m`), free and unofficial, can lag |
| `trader/timemachine.json` | with `--write`: `{plan, mc, history}` plus the verdict. `mc` holds the odds, percentiles, the fan-chart bands, 160 sample paths and a 24-bin histogram of the close |

## How it works

1. **The pool.** It keeps only FULL sessions before the plan's date: Mon-Thu
   64 five-minute bars (36 + 28) and Fri 52 bars (30 + 22), excluding the
   lunch break and pre-closing. Gaps and today are left out. Every bar
   becomes four ratios to the bar before it: open, high, low and close over
   the previous close.
2. **One replay.** Start at the entry price. For each bar left in the day,
   pick a past bar from the same time of day (plus or minus 2 bars) at
   random, and scale it to the current price. Bar by bar, it checks the stop
   first, then the target. A bar that touches both counts as the stop.
3. **10,000 replays** give four odds. Target first. Stop first. Neither,
   which means the trade was still open at `--until` (default 15:50 WIB, the
   close). Green, which means target
   first or above the entry at `--until`.
   R is +1 at a 1R target, -1 at the stop, and otherwise the distance from
   the entry at `--until` divided by the risk. A gap through the stop still
   counts as -1R here. A real fill can be worse.
4. **The history.** The plan's own rule (the same opening range, stop rule
   and target R) runs again on every one of those past sessions. That is
   what really happened, not a simulation.
5. **The verdict** is one line from the numbers. It looks only at the
   replays that hit one side, and asks how often the target came first. A
   bigger target needs to win less often to break even: 1 in (1 + R). That
   is 50 % at 1R, 33 % at 2R, 25 % at 3R. Less than 5 points from break-even:
   "Close to a coin flip" at 1R, "Close to break-even" at any other R. 5 to
   15 points: "Leans toward the target" or "Leans toward the stop". 15 or
   more: "Strongly toward" one of them. So a 2R plan with target first
   24.1 % and stop first 50.5 % is close to break-even (it needs 33 % of
   the 74.6 % that hit a side, and got 32 %), not a loser.
6. **Below the verdict**, when it applies: a line when more than 40 % of the
   replays hit neither (the price at `--until` decides those), and the
   average R when its sign goes against the lean. Those can only point the
   other way because of the replays that hit neither.

**The seed.** The draws come from Python's `random.Random(seed)`, seed 19 by
default. Same plan, same data, same seed: the same numbers, on any machine.
Say the seed with every result so the user can repeat it.

**5-minute bars only.** Yahoo keeps 60 days of 5-min bars but only about 7
days of 1-min bars, too few sessions for a fair pool. It refuses, in one
plain line, when there are fewer than 20 full sessions, when the entry bar is
not in the data (wrong date, not closed yet, a future day), or when the plan
does not make sense (a stop above a buy's entry, an entry off the 5-minute
grid). A live in-progress bar is never used.

## Steps

1. Make sure `trader/plan.json` is today's plan from `/trader-exit`. If there
   is none, run that first, or pass the plan as flags.
2. Run `timemachine.py run --write`. Add `--until 15:45` when the plan has a
   flat-by time, so "neither" means still open at the time you would get out.
3. Tell the user, in this order: the four odds, the median and the 5 to 95
   range of the price at the close, the average R, the history line, then the
   verdict line and any line under it exactly as printed. Say the seed.
4. If the verdict is a coin flip or close to break-even, say so plainly. Do
   not dress it up. If the history and the replays disagree, say that too.
5. Say once that this is built from the last 60 days and is not a prediction.
   Earnings, news and halts can do things those 60 days never did. Check
   `/trader-news` for the stock before going on.
6. If the user still wants the trade, hand off to `/trader-budget` to size it.

## Example

BBCA, Monday 2026-11-23. The 15-minute opening range is Rp 5.425 to Rp 5.500.
The 09:30 bar closes above it: entry Rp 5.550 at 09:35 WIB (bar 6), stop Rp 5.425
(the range low), target Rp 5.675 (1R, risk Rp 125 a share).

```
10,000 replays of the rest of the session, 09:35 to 15:50 WIB, seed 19.
  target first   29.4 %
  stop first     25.5 %
  neither        45.1 %   still open at 15:50 WIB
  green          51.7 %   target first, or above the entry at 15:50 WIB
  Price at 15:50 WIB: median 5560, 90 % of replays between 5400 and 5725.
  Average R: +0.034
History: the same rule on each of those 59 real sessions fired 33 times:
13 target, 15 stop, 5 neither. Average R -0.062.
Close to a coin flip: target first 29.4 % vs stop first 25.5 %.
45.1 % of the replays hit neither by 15:50 WIB; the price at 15:50 WIB decides those.
```

At 1R the target has to come first in half of the replays that hit one
side. It did in 53.6 %. The replays came out close to a coin flip, and the
real history was slightly worse than even. That is the honest answer for this setup, and it is what
the user should hear before `/trader-budget` sizes it in 100-share lots.

## Rules

- Every number comes from the run. Never round a coin flip up into an edge.
- The verdict line and the lines under it are printed by the tool. Repeat
  them, do not rewrite them. Never judge a 2R or 3R plan by target first vs
  stop first alone: the verdict already weighs the target's R.
- Simulated odds are not predictions and not promises. Say it once, plainly.
- Free Yahoo data is unofficial and can lag. Bars are 5-minute bars, checked
  bar by bar, never tick by tick and never real time.
- Always say the seed, so any run can be repeated.
- One plan per run. A changed entry, stop, target or date is a new run.

## What it never does

It never places an order, never sizes a position, never changes the plan,
and never calls a result a sure thing. It never prints a P&L or a profit.
It never uses a bar that has not closed yet, and never mixes today's bars
into the pool.

## IDX (Indonesian stocks)

Pass `--config trader/config.json` (with `"market": "idx"`) or a `trader/plan.json`
that carries `"market": "idx"`.

- **Separate slot maps:** Mon-Thu (36 + 28 = 64 bars) and Friday (30 + 22 = 52
  bars) use separate slot maps. Lunch-break, pre-closing (15:50/15:55), 16:00
  closing-auction, and post-trading (16:05-16:10) bars are excluded.
- **Lunch gap:** the first bar of session 2 draws only from past
  first-bars-of-session-2, so the lunch gap is part of the simulation.
- **ARA/ARB band and ticks:** simulated prices are clamped to the day's
  ARA/ARB band (reference = previous close), stops and targets are checked for
  valid IDX ticks, and runs that touch the band edge are counted.
- **Delay and minimum sessions:** Yahoo `.JK` data is about 10 minutes late.
  Fewer than 20 full sessions means no verdict.
- **Out of scope:** budget/risk/broker, short trades, forex.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables, never in the chat.
