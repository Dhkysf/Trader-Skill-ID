---
name: trader-broker
description: >
  Build manual order tickets for Indonesian stocks (IDX) and spot forex,
  record your explicit "yes" confirmation, and log paper or manual fills in
  trader/state/broker.json. Reads trader/orders.json and requires a matching
  PASS from trader-risk in trader/state/risk.json before showing any ticket.
  Use when the user says "build ticket", "fill", "close my position",
  "flatten", "get me out", "buat tiket", "catat fill", "tutup posisi", or
  "konfirmasi order". Not financial advice.
argument-hint: "[order number]"
---

# trader-broker

Builds manual order tickets from `trader/orders.json`, checks the `trader-risk`
PASS fingerprint in `trader/state/risk.json`, records your explicit per-order
`"yes"`, and logs paper or manual fills in `trader/state/broker.json`. No skill
places an order by itself; you enter the ticket in your broker app yourself.
Not financial advice.

## Commands

```powershell
python "<skill-dir>/ticket.py" show
python "<skill-dir>/ticket.py" approve --index 1 --reply "yes"
python "<skill-dir>/ticket.py" decline --index 1
python "<skill-dir>/ticket.py" result --index 1 --status placed --filled-qty 300 --filled-price 9875
python "<skill-dir>/ticket.py" fill --symbol BBCA --side sell --qty 300 --price 10200
python "<skill-dir>/ticket.py" flatten --symbol BBCA --qty 300
python "<skill-dir>/ticket.py" log
```

All commands read `trader/config.json`, `trader/orders.json`,
`trader/state/risk.json`, and `trader/state/broker.json` in the current folder.
`--now "2026-11-23 09:35"` pins the clock (WIB).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/orders.json` | the proposed orders (`trader-budget` writes it; `flatten` replaces it) |
| `trader/state/risk.json` | `trader-risk` verdicts; only a matching PASS from today is READY |
| `trader/state/broker.json` | every yes, no, placed, failed, and filled, with each entry's max loss |
| `trader/portfolio.json` | cash and shares, updated by `fill` and by `result --filled-qty` |
| `trader/plan.json` | the flat-by time for `flatten` |

## Safety rules

1. **Risk PASS required.** `ticket.py show` and `approve` check that
   `trader/state/risk.json` has `status: "PASS"` and a matching fingerprint for
   the current `trader/orders.json`. If you edit `orders.json`, re-run `trader-risk`.
2. **Explicit per-order `"yes"`.** Nothing is confirmed without your explicit
   `"yes"` for that order number via `approve --index N --reply "yes"`.
3. **Manual / paper default.** `ticket.py` prints the exact IDX ticket (symbol,
   side, lot-aligned shares, entry, stop-loss, take-profit) for you to enter in
   your broker app, then logs fills when you run `result` or `fill`.
4. **Flatten.** `flatten --symbol BBCA --qty 300` builds a sell ticket to close
   an open position before `flat_by` (15:45 WIB). Still requires `trader-risk`
   and your `"yes"`.

## What it never does

- Never places an order by itself, and never confirms two orders on one `"yes"`.
- Never places orders from a scheduled or background task: nobody is there to say `"yes"`.
- Never asks for, reads, stores, or repeats API keys or passwords.
- Never promises a fill price: a market order and a stop fill at whatever the market gives.

## Example

```text
ORDER 1 of 1, MANUAL / PAPER, IDX
  BUY BBCA 300 shares (3 lots) @ Rp 9.875
  Stop-loss:   Rp 9.700
  Take-profit: Rp 10.200
  Time in force: day
Enter this ticket in your broker app yourself, then log the fill with:
  python "<skill-dir>/ticket.py" fill --symbol BBCA --side buy --qty 300 --price 9875
```

## Notes

- Broker keys live in environment variables, never in the chat.
- Always confirm each order with `"yes"` before logging a fill.
- For forex, use only a broker licensed in Indonesia (check the official Bappebti list before depositing).
- Not financial advice.
