---
name: trader-broker
description: >-
  Order Executor. Sends approved orders to your broker, paper trading by
  default, never without your yes. Shows each order as a plain ticket (a
  bracket shows its stop-loss, take-profit and the max loss at the stop)
  plus the exact JSON for Alpaca's place_stock_order, records your yes word
  for word, then the agent's own permission prompt asks again. Builds the
  sell ticket that closes a day trade by your flat-by time, records fills,
  and logs each trade's max loss so trader-risk can hold the daily limit.
  Covers setting up Alpaca's official MCP server in Antigravity (paper by
  default, keys in env vars, never in chat), Interactive Brokers MCP,
  and setting order tools to `ask` in Antigravity permissions. Use when the user
  says "place the order", "buy it", "execute", "send it to my broker",
  "close my position", "flatten", "get me out", "connect Alpaca", "set up
  paper trading", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches the market only after three
separate gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user approved the agent's own permission prompt**, which appears
   because the order tool is set to `ask` in Antigravity permissions.

Two yeses from the user, one PASS from the rules. No yes, no order.

`<skill-dir>` is the folder that holds this SKILL.md (`skills/trader-broker` in this repo, `.agents/skills/trader-broker` in a workspace). Commands below use `python` (use `python3` on macOS/Linux).

```bash
python "<skill-dir>/ticket.py" show                     # every ticket, READY or not
python "<skill-dir>/ticket.py" approve --index 1 --reply "yes"
python "<skill-dir>/ticket.py" result --index 1 --status placed --broker-id ID --filled-qty 8 --filled-price 364.20
python "<skill-dir>/ticket.py" fill --symbol TSLA --side sell --qty 8 --price 370.04
python "<skill-dir>/ticket.py" flatten --symbol TSLA --qty 8
python "<skill-dir>/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, builds the flatten ticket, and keeps the log in
`trader/state/broker.json`. `--now "2026-10-19 10:15"` pins the clock (New York time).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (trader-budget writes it; `flatten` replaces it) |
| `trader/state/risk.json` | trader-risk's verdicts; only a PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time for `flatten` |

## Setup A: Alpaca (official MCP server, Antigravity)

Alpaca's own server is github.com/alpacahq/alpaca-mcp-server (MIT). It runs on
the user's computer as a local stdio MCP server in Antigravity. It trades on a
**paper** account unless told otherwise. Checked against its source on
2026-10-20 (version 2.4.0).

1. The user makes an Alpaca account and creates **paper trading** API keys in
   the Alpaca dashboard. Paper keys are separate from live keys.
2. The user installs `uv` (it provides `uvx`), from docs.astral.sh/uv.
3. Edit `~/.gemini/config/mcp_config.json` (`%USERPROFILE%\.gemini\config\mcp_config.json`
   on Windows), or open it via **Agent Panel (...) > MCP Servers > Manage MCP
   Servers > View raw config**. Add this block (also in
   `mcp_config.example.json` here) and type your own keys into the file:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "paste your paper key here, in this file only",
        "ALPACA_SECRET_KEY": "paste your paper secret here, in this file only",
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,stock-data"
      }
    }
  }
}
```

   The `env` block hands the keys to the server as environment variables.
   **Keys never go in the chat.** Never ask for them, never read this file
   back into the conversation, and if the user pastes a key anyway, tell them
   to delete that message and make new keys in the Alpaca dashboard.
   `ALPACA_PAPER_TRADE` is already true by default; writing it makes it
   visible. `ALPACA_TOOLSETS` is optional and hides the tools they do not need.
4. Reload or restart Antigravity so the `alpaca` MCP server connects.
5. **Set the tool permissions** in Antigravity Settings (Permissions) or via
   `/permissions` in `agy` (check `https://antigravity.google/docs/permissions`
   for the current UI/config layout; precedence is `Deny > Ask > Allow`, rule
   format `mcp(server/tool)`):
   - **`ask`** (never `allow`): `mcp(alpaca/place_stock_order)` and every other
     tool that places, changes, cancels or closes anything
     (`mcp(alpaca/cancel_order_by_id)`, `mcp(alpaca/replace_order_by_id)`,
     `mcp(alpaca/close_position)`, `mcp(alpaca/update_account_config)`).
   - **`deny`** (unless the user has a reason and changes it themselves):
     `mcp(alpaca/close_all_positions)`, `mcp(alpaca/cancel_all_orders)`,
     `mcp(alpaca/place_option_order)`, `mcp(alpaca/place_crypto_order)`,
     `mcp(alpaca/exercise_options_position)`,
     `mcp(alpaca/do_not_exercise_options_position)`.
   - **`allow`** (read-only tools are fine): `mcp(alpaca/get_account_info)`,
     `mcp(alpaca/get_all_positions)`, `mcp(alpaca/get_open_position)`,
     `mcp(alpaca/get_orders)`, `mcp(alpaca/get_clock)`,
     `mcp(alpaca/get_stock_snapshot)`, `mcp(alpaca/get_stock_latest_quote)`.
   - **Never use Turbo mode in a trading workspace.** (Turbo mode runs
     commands and MCP tools without prompting unless explicitly denied.)
6. Check it: ask the agent for the Alpaca account info (read only) and confirm
   in the Alpaca dashboard that it is the paper account.

**Bracket orders on Alpaca.** `place_stock_order` takes
`take_profit_limit_price` and `stop_loss_stop_price` (and an optional
`stop_loss_limit_price`). When either is there, the server sets
`order_class` to "bracket" by itself; trader-budget writes it anyway so the
ticket shows it. A bracket is whole shares only, with `time_in_force` day or
gtc. After the entry fills, the stop-loss and the take-profit wait at the
broker as two orders that cancel each other. They are day orders too, so they
end at the close: one more reason to be flat by then.

## Setup B: Interactive Brokers (remote MCP)

Interactive Brokers publishes a remote MCP endpoint: `https://api.ibkr.com/v1/api/mcp`.
Check Antigravity's MCP docs (`https://antigravity.google/docs/mcp`) and IBKR's
authentication requirements before adding it to `~/.gemini/config/mcp_config.json`,
and sign in through IBKR's own flow (never in the chat).
The agent can draft trade instructions that are sent to the user's IBKR account
for their review and approval, and never submits orders directly to the market.
So with IBKR the final yes happens in IBKR as well. Set `"broker": "ibkr"` in
`trader/config.json`. Set its tools that draft orders to `ask` too.

## Steps: the entry

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order
   per question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this
   order (for example "sure", "yes to all", or a yes that names a different
   stock or amount). Ask again. Never turn a reply into a yes yourself.
4. Only after "Recorded your yes", call `place_stock_order` with exactly the
   JSON the ticket printed. Antigravity's permission prompt appears: approve or deny.
5. Record what happened: `ticket.py result --index N --status placed
   --broker-id <id> --filled-qty Q --filled-price P` (the fill from the
   response or `get_open_position`), or `--status denied`, or `--status failed`
   with `--note`. A failed order is not retried without a new check and a new yes.
   The log keeps the entry's max loss for trader-risk's daily limit.

## Steps: while it is open, and out by the close

- trader-alerts watches the stop, the target and the flat-by time
  (`alerts.py add --from-plan`). The bracket's own orders do the stopping.
- When the stop-loss or the take-profit fills, record it:
  `ticket.py fill --symbol TSLA --side sell --qty 8 --price 358.32`.
- By `flat_by` (15:55 New York), anything still open gets closed:
  1. Ask Alpaca how many shares are held: `get_open_position` (read only).
  2. `ticket.py flatten --symbol TSLA --qty 8` writes a market sell for those
     shares to `trader/orders.json`.
  3. `/trader-risk`. A sell that only closes what the user holds is never
     blocked by the daily limits or the entry window.
  4. `ticket.py show`, then the user's yes for that one order, as above.
  5. The bracket's stop-loss and take-profit still hold those shares, so
     Alpaca rejects a new sell until they are canceled: `get_orders` (status
     open, nested true) shows them; `cancel_order_by_id` each one (`ask`).
     Then `place_stock_order` with the ticket, then `result`.

## Example: the reel

```
ORDER 1 of 1, PAPER account, Alpaca
  BUY 8 TSLA, market, good for today
  stop-loss 358.32
  take-profit 370.04
  max loss about $46.88 if the stop fills at 358.32 (it can fill worse in a fast market)
  why: opening-range breakout on TSLA: 8 shares, bound by your $50 max loss per trade (8 x 5.86 = $46.88 at the stop)
  READY: trader-risk PASS, waiting for your yes
  The agent will call place_stock_order with exactly:
    {"symbol": "TSLA", "side": "buy", "qty": "8", "type": "market", "time_in_force": "day",
     "order_class": "bracket", "take_profit_limit_price": "370.04", "stop_loss_stop_price": "358.32"}
```

The user replies "yes". The agent records it, calls `place_stock_order`, and
the permission prompt asks to approve or deny that JSON. Approving sends it to
the paper account. The `why` and the plan stay in the file; they are never sent.

## What it never does

- Never places an order without all three gates, and never two orders on one yes.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats API keys or passwords.
- Never switches `ALPACA_PAPER_TRADE` or `"paper"` to live. The user does that themselves.
- Never calls `close_all_positions`, `cancel_all_orders`, option or crypto order tools on its own.
- Never promises a fill price: a market order and a stop fill at whatever the market gives.

## IDX (manual orders)

IDX orders are **manual**: there is no Indonesian broker API or MCP server.
When `"market": "idx"` is set in `trader/config.json`, `ticket.py show`
prints a manual instruction (for example: `BUY 3 lots (300 shares) BBCA at
Rp 9.875, stop Rp 9.700, target Rp 10.200, max loss incl. fees Rp 64.219.
Enter it in your broker app yourself.`) with no Alpaca or MCP JSON.
Explicit per-order `"yes"` (`ticket.py approve`), the `trader-risk` PASS
fingerprint, `ticket.py result`, and `ticket.py fill` journalling all still
apply. On IDX, fills deduct the buy/sell fee from cash (from `markets\idx.json`
or your config's `buy_fee_pct` / `sell_fee_pct`), add the buy fee to the lot's
cost basis, and accept `--fee AMOUNT` to use the real fee from your broker app.

## Safety

- Education and tooling, not financial advice. A PASS is a rules check, not a recommendation.
- Paper trading by default (`"paper": true`). Going live is the user's own decision, in their own config.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user approved the agent's own permission prompt because the order tool is set to `ask` in Antigravity
  permissions. Never set an order tool to `allow`.
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or `~/.gemini/config/mcp_config.json`, never in the chat.
