---
name: trader-core
description: >-
  Shared market profiles, trading calendars, DST clock conversions, and tick
  rounding for all Trader-Skill-ID skills. Reads the selected market profile
  (default "us") from JSON data files under markets/ so US stocks, IDX, and
  forex share one clock and session layer without duplicating rules.
---

# trader-core

`trader-core` is the shared market-rules and clock module imported by the other
skills in this pack (`trader-scanner`, `trader-entry`, `trader-exit`,
`trader-timemachine`, and the remaining pipeline skills). It is not a
standalone trading command.

## Configuration

Set `"market"` in `trader/config.json` inside your working folder to choose the
active market profile. When omitted or empty, it defaults to `"us"`.

```json
{
  "market": "us"
}
```

## Available profiles

| profile | market | timezone | currency | status |
| --- | --- | --- | --- | --- |
| `us` | US Equities (NYSE/Nasdaq) | `us_eastern` (UTC-5 / UTC-4) | `USD` | active |
| `idx` | Indonesia Stock Exchange (IDX/BEI) | `asia_jakarta` (UTC+7, WIB) | `IDR` | active |

Planned profiles: `forex`.

## How other skills import it

Each skill script adds `<script dir>/../trader-core` to `sys.path` and imports
`market`. This works from any working directory, both in this repository
(`skills/trader-*/`) and when copied into a workspace's `.agents/skills/`
folder:

```python
_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market
```

## API summary (`market.py`)

- `load(name="us")` - load and cache a market profile from `markets/<name>.json`. Raises `ValueError` listing available profiles for unknown names.
- `utc_offset(p, utc)` - hours from UTC for profile `p` at `utc` (naive or aware).
- `to_local(p, utc)` - convert UTC datetime to naive local wall-clock datetime.
- `local_to_utc(p, local)` - convert naive local wall-clock datetime to naive UTC.
- `is_trading_day(p, d)` - `True` if `d` has scheduled sessions and is not a holiday.
- `sessions(p, d)` - list of `(open_time, close_time)` `datetime.time` tuples for `d` (`[]` on holidays/weekends; early-close applied).
- `round_tick(p, price, mode="nearest")` - round `price` to `p`'s tick size as a `Decimal` (`"down"`, `"up"`, or `"nearest"`).
- `tick_size(p, price)` - return the tick size (`Decimal`) for `price` (supports tiered `tick_table` or flat `tick`).
- `valid_tick(p, price)` - `True` if `price` is `>= min_price`, `> 0`, and a valid tick multiple.
- `round_lot(p, shares)` - round `shares` down to a whole multiple of `p["lot"]`.
- `ar_limits(p, reference_price, day=None)` - return `(lowest, highest)` auto-rejection `Decimal` prices rounded to valid ticks, or `None`.

## Profile data (`markets/*.json`)

All market hours, holidays, early-close dates, DST rules (`nth_sunday: -1`
supported for last Sunday of the month), tick size, lot size, currency, Yahoo
symbol suffix, and data delay live in `markets/<name>.json` with source URLs
and `checked` dates.
