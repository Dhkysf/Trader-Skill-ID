---
name: trader-exit
description: >-
  Exit Planner. Sets your stop and your target before you enter, so you know
  when to get out. Reads the entry from trader-entry (or a price you give),
  puts the stop at the opening-range midpoint by default (or the range low,
  your price, a percent, or a multiple of the ATR), rounds it down to a
  valid IDX tick, and sets the target at 2R (or 1R, or your price). Refuses a stop at or
  above the entry, a target at or below it, or a stop too tight to survive the
  spread, and says why. Writes trader/plan.json for the Time Machine, the
  Budget Manager and Price Alerts. Long side only. Use when the user says
  "where's my stop", "set my stop and target", "plan the exit", "when do I get
  out", "stop loss", "what's my R", "risk reward", or right after
  /trader-entry triggers, before /trader-timemachine.
argument-hint: "[--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|1R|price:X]"
---

# trader-exit

The Exit Planner decides how a trade ends before it starts. The stop is where
the setup has failed. The target is where you take what you came for. Both
are set BEFORE the entry, written down and handed on, so nobody has to decide
anything in the middle of a fast move. A stop is a plan, not a guarantee: a
gap or a fast market can fill past it. Day trading loses most people money,
and a neat plan does not change that.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-exit` in this repo, `.agents/skills/trader-exit` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/exit.py" plan                          # trader/entry.json: midpoint stop, 2R target
python "<skill-dir>/exit.py" plan --stop or-mid --target 1R --write
python "<skill-dir>/exit.py" plan --stop atr:1.5           # needs the session's bars (Yahoo or --offline)
python "<skill-dir>/exit.py" plan --symbol BBCA --entry 9875 --or-high 9850 --or-low 9700
python "<skill-dir>/exit.py" show                          # the current trader/plan.json
```

Other flags: `--flat-by 15:45`, `--json`, `--now "2026-11-23 09:35"` (WIB),
`--entry PRICE` with a waiting entry.json to plan ahead, `--setup level`,
`--offline FILE` (a saved Yahoo chart JSON for an ATR stop).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/entry.json` | the trigger from trader-entry: symbol, entry price, time, bar, opening range |
| `trader/config.json` | `flat_by` (15:45) and `min_reward_risk` (1.0: a note here, trader-risk enforces it) |
| Yahoo chart API | only for an `atr:K` stop: the session's bars up to the entry bar, free and unofficial |
| `trader/plan.json` | with `--write`: entry, stop and its rule, target and its R, risk a share, reward:risk, flat by. trader-timemachine, trader-budget and trader-alerts read it |

## Stops and targets

| stop | where it goes |
| --- | --- |
| `or-mid` | the opening-range midpoint (the default for an opening-range breakout) |
| `or-low` | the opening-range low: wider, so fewer shares for the same max loss |
| `price:X` | your price |
| `pct:X` | X percent under the entry |
| `atr:K` | K times the 14-bar ATR under the entry, on the session's bars up to the entry bar. With fewer than 14 bars by then it averages all of them and says so |

A level setup has no opening range to lean on, so it needs a stop you name.

- **Rounding.** The stop rounds AWAY from the entry to a valid IDX tick (down,
  for a long). Risk = entry minus stop. Target = entry + R x risk, rounded
  half up to a valid IDX tick. `2R` by default; `1R`, `1.5R` or `price:X` also
  work.
- **Refused, with the reason.** A stop at or above the entry. A target at or
  below it. A risk under 0.05% of the price: too tight to survive the
  spread, normal wiggle would stop you out. An entry.json that has not
  triggered (unless you give `--entry`). A short: v2 plans longs only.
- **Flat by.** 15:45 WIB by default (or `flat_by` in the config). Out by then,
  win or lose, no overnight hold. An entry at or after the flat-by time is
  refused.

## Steps

1. Run it right after `/trader-entry` triggers. Before that, `--entry PRICE`
   plans ahead at the level you expect.
2. Use the default stop for an opening-range breakout unless the user names
   another. A level setup needs one: ask.
3. Run `exit.py plan --write`. Read back the entry, the stop and its rule,
   the target and its rule, the risk a share, reward:risk and flat by.
4. If it refuses, say the reason and the fix (a wider stop, a farther
   target). Never loosen anything on your own.
5. Say once that the stop is a plan, not a guarantee.
6. Hand off to `/trader-timemachine` to replay the plan, then `/trader-budget`
   to size it to the max loss per trade. Offer `/trader-alerts` for the stop,
   the target and the flat-by time. The agent can keep `entry.py watch` running
   in the background or on a `/loop` until a setup triggers, then come here.

## Example

BBCA, Monday 2026-11-23. The entry is Rp 9.875 at 09:35 WIB (bar 6) and the
opening range is Rp 9.700 to Rp 9.850. `exit.py plan --stop or-mid --target 1R --write`:

```
Exit plan: BBCA long, Mon 2026-11-23, opening-range breakout on 5-minute bars
  Entry         Rp 9.875 at 09:35 WIB (bar 6)
  Stop          Rp 9.775  opening-range midpoint: (9.850 + 9.700) / 2 = Rp 9.775
  Target        Rp 9.975  1R (one times the risk)
  Risk a share  Rp 100 (1.01% of the entry)
  Reward:risk   1.0
  Flat by       15:45 WIB, win or lose: no overnight hold
```

The default 2R target would be 9.875 + 2 x 100 = Rp 10.075. trader-budget then
sizes it in 100-share lots within your max loss per trade.

## Rules

- The stop and the target are set before the entry, never after.
- Never move a stop further from the entry once the trade is on.
- Plain numbers only: entry, stop, target, risk a share, reward:risk. It
  never prints a P&L or a return.
- Nothing here promises winning trades or money. A 1R target is not a
  prediction that the price gets there.
- Long side only. v2 plans longs only.

## What it never does

It never places an order, never sizes a position, never widens a stop to
make a plan pass, and never calls a stop a guarantee.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables, never in the chat.
