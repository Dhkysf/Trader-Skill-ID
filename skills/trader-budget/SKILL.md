---
name: trader-budget
description: >-
  Budget Manager for Indonesian stocks (IDX, 100-share lots) and spot forex
  (0.01 lot step, leverage, spread). Sizes every position to your budget and
  max loss per trade from trader-exit's plan and writes ONE manual bracket
  order to `trader/orders.json`. Nothing is placed. Use when the user says
  "how many shares", "how many lots", "size this trade", "I have Rp
  10,000,000", "hitung lot", "berapa lot", "atur modal", or after
  /trader-exit writes a plan.
argument-hint: "[budget in rupiah]"
---

# trader-budget

The Budget Manager turns a plan ("buy BBCA at Rp 9.875, stop Rp 9.775") into an
exact order ("buy 10 lots / 1,000 shares"), inside rules the user sets once. The stop
decides the size: the further away the stop, the fewer shares. It writes a
proposal only. trader-risk checks it and trader-broker asks the user yes or
no. Day trading loses most people money. Sizing to a max loss keeps each
loss small; it does not make a trade win.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-budget` in this repo, `.agents/skills/trader-budget` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/size.py"                        # trader/plan.json + trader/config.json
python "<skill-dir>/size.py" --write                # write trader/orders.json
python "<skill-dir>/size.py" --limit --write        # a limit order at the plan's entry
python "<skill-dir>/size.py" --limit 9875 --json    # a limit order at Rp 9.875
python "<skill-dir>/size.py" --weights BBCA=40,BBRI=60 --config split.json   # weights mode, below
```

`--now "2026-11-23 10:15"` pins the clock (WIB). A plan for
another day is refused: make a new one with trader-exit.

## What it reads and writes

| file | what |
| --- | --- |
| `trader/config.json` | the rules (start from `config.example.json` in this folder) |
| `trader/plan.json` | the trade: entry, stop, target, setup, flat-by time (trader-exit writes it) |
| `trader/prices.json` | optional: a fresh price above the plan's entry means a bigger risk (trader-alerts writes it) |
| `trader/portfolio.json` | optional: its cash caps the size (trader-broker keeps it) |
| `trader/orders.json` | the one proposed bracket order it writes with `--write` |

## Step 1: set the rules once

If `trader/config.json` does not exist, copy `config.example.json` into
`trader/config.json` and ask the user for each value in plain words:

- **budget**: how much money this is for. Only money they can afford to lose.
- **cash_buffer_pct**: how much always stays in cash (default 10).
- **max_loss_per_trade**: the most one trade may lose if the stop fills at the stop (default 100000).
- **max_position_pct**, **max_order**, **min_order**: the biggest position (75% of the
  budget), the biggest order (Rp 8.000.000) and the smallest order (Rp 100.000).
- The day limits trader-risk enforces: **max_daily_loss** (300000), **max_trades_per_day** (3),
  **min_reward_risk** (1.0), **require_stop** (true), **no_entries_before** / **no_entries_after**
  ("09:15" / "15:30") and **flat_by** ("15:45"), all WIB.
- **blocked**: tickers they never want to trade.
- Keep **paper** true until they have watched it work on a paper account.

## Step 2: size the trade

```bash
python "<skill-dir>/size.py" --write
```

IDX trades in 100-share lots (1 lot = 100 shares). The size is
the smallest of four limits:

| limit | shares |
| --- | --- |
| max loss | `max_loss_per_trade` / risk a share (entry minus stop, incl. fees) |
| position cap | budget x `max_position_pct` / entry |
| max order | `max_order` / entry |
| cash | (budget minus the cash buffer) / entry, never more than the cash in `trader/portfolio.json` |

The entry it sizes at: the limit price with `--limit`. For a market order, the
plan's entry, or the price in `trader/prices.json` if it is fresh (under 15
minutes old) and higher. A price that ran up since the plan means a bigger
loss at the same stop, so fewer shares. A lower price never shrinks the risk.

It refuses, and writes no order, when: the size is zero shares, the order is
under the minimum, reward:risk is under `min_reward_risk`, the stop is not
below the entry, the target is not above it (the move already happened), the
plan is for another day, the ticker is blocked, or the plan is a short. Say
the reason to the user in one line.

## Step 3: show the user

Show the four limits, which one decided the size, the shares (lots), the rupiah
and the max loss at the stop. Say plainly that a stop is an order, not a
promise: in a fast market it can fill below the stop. Then hand over to
`/trader-risk`.

## Example

BBCA on Monday 2026-11-23. Opening-range breakout: entry Rp 9.875 at 09:35 WIB,
stop Rp 9.775 (the opening-range midpoint), target Rp 9.975 (1R). Risk Rp 100 a
share (plus broker fees). Example config: Rp 10.000.000 budget, 10% cash buffer,
Rp 100.000 max loss per trade.

```json
{"symbol": "BBCA", "side": "buy", "qty": "700", "type": "market", "time_in_force": "day",
 "order_class": "bracket", "take_profit_limit_price": "9975", "stop_loss_stop_price": "9775",
 "why": "opening-range breakout on BBCA: 7 lots (700 shares), bound by your Rp 100.000 max loss per trade",
 "plan": {"entry": 9875, "stop": 9775, "target": 9975, "risk_per_share": 100, "max_loss": 97510,
          "setup": "orb", "entry_time": "09:35", "flat_by": "15:45"}}
```

`why` and `plan` are notes for trader-risk and trader-broker. They are never
ready for your broker app. With a wider stop, one lot would risk more than
your max loss: no order.

## Weights mode (kept from v1)

`--weights BBCA=40,BBRI=30,TLKM=30` or `--targets FILE` (`targets.example.json`
here) splits a budget across a list by weight: the cash buffer comes off the
top, weights are renormalised to 100, any stock over `max_position_pct` is
pinned at the cap and its excess shared out, slices under the minimum order
are dropped, and amounts round to whole rupiah so nothing is left idle by
accident. With `"whole_shares": true` (default) it buys whole lots and
needs prices (`--prices trader/prices.json`). These are plain buys with no stop: trader-risk blocks them while
`require_stop` is true and counts each one against `max_trades_per_day`. Use
a separate config (`--config`) for a long-term split.

## Rules

- Proposals only. This skill never calls a broker tool.
- Never size money the user has not said is for this. Ask for the budget and the max loss.
- Every number comes from the config, the plan or the prices. Nothing is guessed.
- No projections: never say what a trade will make. A target is a plan, not a forecast.
- Free Yahoo prices are unofficial and can lag. The broker's price is the one that fills.

## What it never does

It never places, approves or schedules an order, never raises a limit on its
own, never shrinks a stop to fit more shares, and never sizes options,
margin or short positions.

## IDX (Indonesian stocks)

When `"market": "idx"` is set in `trader/config.json`:

- Quantity is rounded down to whole lots of 100 shares. Under 1 lot (100 shares)
  is refused with the reason.
- Max loss per trade includes buy and sell broker fees from
  `skills/trader-core/markets/idx.json` (default 0.15% buy, 0.25% sell;
  overridable via `buy_fee_pct` / `sell_fee_pct` in `trader/config.json`).
- Amounts are printed in Rupiah (`Rp 9.875.000`). Orders are manual (no
  broker API).

## Forex (24/5 spot)

When `"market": "fx"` is set in `trader/config.json` (see `config.fx.example.json`):

- Sizes in 0.01-lot steps from `max_loss_per_trade` (including spread), `max_lots`, and `max_leverage` (use `--usdidr` or `trader/prices.json` for IDR accounts).

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables, never in the chat.
