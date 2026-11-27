#!/usr/bin/env python3
"""Shared market profiles and clock helpers for Trader-Skill-ID. Standard library only."""

import datetime
import hashlib
import json
import os
import sys
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

MARKETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "markets")
_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CACHE = {}
_ROUND_MODES = {"down": ROUND_FLOOR, "up": ROUND_CEILING, "nearest": ROUND_HALF_UP}


def available():
    """Sorted list of available market profile names."""
    if not os.path.isdir(MARKETS_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(MARKETS_DIR) if f.endswith(".json"))


def load(name="idx"):
    """Load and cache a market profile by name (default: 'idx')."""
    key = (name or "idx").strip().lower()
    if key in _CACHE:
        return _CACHE[key]
    avail = available()
    if key not in avail:
        raise ValueError("unknown market %r; available: %s" % (name, ", ".join(avail)))
    path = os.path.join(MARKETS_DIR, key + ".json")
    with open(path, encoding="utf-8") as fh:
        profile = json.load(fh)
    _CACHE[key] = profile
    return profile


def _nth_sunday(year, month, n):
    """Return the n-th Sunday of (year, month), or the last Sunday when n == -1."""
    if n == -1:
        if month < 12:
            d = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        else:
            d = datetime.date(year, 12, 31)
        return d - datetime.timedelta(days=(d.weekday() + 1) % 7)
    if n < 1:
        raise ValueError("nth_sunday must be >= 1 or -1, got %r" % (n,))
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def _as_naive_utc(utc):
    if utc.tzinfo is not None:
        return utc.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return utc


def utc_offset(p, utc):
    """Hours from UTC for profile `p` at UTC datetime `utc`."""
    naive = _as_naive_utc(utc)
    dst = p.get("dst")
    if not dst:
        return p["utc_offset_std"]
    y = naive.year
    s = dst["start"]
    e = dst["end"]
    start = datetime.datetime.combine(_nth_sunday(y, s["month"], s["nth_sunday"]),
                                      datetime.time(s["utc_hour"], 0))
    end = datetime.datetime.combine(_nth_sunday(y, e["month"], e["nth_sunday"]),
                                    datetime.time(e["utc_hour"], 0))
    return p["utc_offset_dst"] if start <= naive < end else p["utc_offset_std"]


def to_local(p, utc):
    """UTC datetime (aware or naive) -> naive local wall-clock datetime."""
    naive = _as_naive_utc(utc)
    return naive + datetime.timedelta(hours=utc_offset(p, naive))


def local_to_utc(p, local):
    """Naive local wall-clock datetime -> naive UTC datetime."""
    naive = local.replace(tzinfo=None)
    std = p["utc_offset_std"]
    dst = p.get("utc_offset_dst", std)
    offs = (dst, std) if dst != std else (std,)
    for off in offs:
        utc = naive - datetime.timedelta(hours=off)
        if utc_offset(p, utc) == off:
            return utc
    return naive - datetime.timedelta(hours=std)


def _as_date(d):
    return d.date() if isinstance(d, datetime.datetime) else d


def _parse_hm(text):
    h, m = text.split(":")
    return datetime.time(int(h), int(m))


def is_trading_day(p, d):
    """True if `d` (date or datetime) has scheduled sessions and is not a holiday."""
    d = _as_date(d)
    return bool(p["sessions"].get(_WEEKDAYS[d.weekday()])) and d.isoformat() not in p.get("holidays", {})


def calendar_note(p, day):
    """Return a warning string when day.year is outside calendar_years, else None."""
    years = p.get("calendar_years") or ()
    if not years:
        return None
    d = datetime.date.fromisoformat(day) if isinstance(day, str) else _as_date(day)
    if d.year in years:
        return None
    return (
        "%s holidays for %d are not in markets/%s.json yet: holidays count as trading days. Add the official list."
        % (p.get("exchange", "IDX"), d.year, p["id"])
    )


def sessions(p, d):
    """List of (open_time, close_time) tuples for `d`, [] on holidays/weekends, early close applied."""
    d = _as_date(d)
    if not is_trading_day(p, d):
        return []
    raw = p["sessions"].get(_WEEKDAYS[d.weekday()], [])
    out = [(_parse_hm(o), _parse_hm(c)) for o, c in raw]
    early = p.get("early_close") or {}
    if d.isoformat() in early.get("dates", {}):
        cut = _parse_hm(early["time"])
        out = [(o, min(c, cut)) for o, c in out if o < cut]
    return out


def _to_decimal(price):
    if isinstance(price, Decimal):
        return price
    if isinstance(price, float):
        return Decimal(repr(price))
    return Decimal(str(price))


def tick_size(p, price):
    """Return the tick size (as Decimal) for `price` under profile `p`."""
    d = _to_decimal(price)
    table = p.get("tick_table")
    if table:
        for entry in table:
            if entry["below"] is None or d < Decimal(str(entry["below"])):
                return Decimal(str(entry["tick"]))
    return Decimal(str(p["tick"]))


def round_tick(p, price, mode="nearest"):
    """Round `price` to the profile's tick size using mode 'down', 'up', or 'nearest'."""
    rounding = _ROUND_MODES.get(mode)
    if rounding is None:
        raise ValueError("unknown round_tick mode %r; expected down, up, or nearest" % (mode,))
    d = _to_decimal(price)
    step = tick_size(p, d)
    return (d / step).to_integral_value(rounding=rounding) * step


def valid_tick(p, price):
    """True if `price` is >= min_price (if set), > 0, and a valid tick multiple."""
    d = _to_decimal(price)
    min_p = p.get("min_price")
    if min_p is not None and d < Decimal(str(min_p)):
        return False
    if d <= 0:
        return False
    return (d % tick_size(p, d)) == 0


def round_lot(p, shares):
    """Round `shares` down to a whole multiple of the profile's lot size."""
    lot = int(p.get("lot", 1))
    if shares < 0:
        raise ValueError("shares must be >= 0")
    return (int(shares) // lot) * lot


def ar_limits(p, reference_price, day=None):
    """Return (lowest, highest) auto-rejection prices as Decimals rounded to valid ticks, or None."""
    rules = p.get("auto_rejection")
    if not rules:
        return None
    if day is None:
        utc_now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        d = to_local(p, utc_now).date()
    elif isinstance(day, str):
        d = datetime.date.fromisoformat(day)
    else:
        d = _as_date(day)
    day_s = d.isoformat()
    rule = None
    for r in sorted(rules, key=lambda x: x["effective_from"], reverse=True):
        if r["effective_from"] <= day_s:
            rule = r
            break
    if rule is None:
        raise ValueError("no auto_rejection rule for %s" % day_s)
    if rule.get("valid_until") and day_s > rule["valid_until"]:
        print(
            "Warning: auto_rejection rule expired %s; check the current ARA/ARB rule on idx.co.id and update markets/idx.json"
            % rule["valid_until"],
            file=sys.stderr,
        )
    ref = _to_decimal(reference_price)
    if ref <= 0:
        raise ValueError("reference_price must be > 0")
    band = None
    for b in rule["bands"]:
        if b["max_price"] is None or ref <= Decimal(str(b["max_price"])):
            band = b
            break
    if "down_abs" in band:
        raw_low = ref - Decimal(str(band["down_abs"]))
    else:
        raw_low = ref * (Decimal("100") - Decimal(str(band["down_pct"]))) / Decimal("100")
    if "up_abs" in band:
        raw_high = ref + Decimal(str(band["up_abs"]))
    else:
        raw_high = ref * (Decimal("100") + Decimal(str(band["up_pct"]))) / Decimal("100")
    min_p = p.get("min_price")
    if min_p is not None:
        raw_low = max(raw_low, Decimal(str(min_p)))
    return (round_tick(p, raw_low, "up"), round_tick(p, raw_high, "down"))


_CURRENCY_PREFIX = {"USD": "$"}


def from_config(cfg_or_path=None):
    """Load the market profile named in a config dict or JSON file (default: 'idx')."""
    if isinstance(cfg_or_path, dict):
        return load(cfg_or_path.get("market") or "idx")
    path = cfg_or_path or "trader/config.json"
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict):
            return load(doc.get("market") or "idx")
    return load("idx")


def price_decimals(p):
    """Number of decimal places for prices in profile `p` (default: 0 for IDR, else 2)."""
    val = (p or {}).get("price_decimals")
    if val is not None:
        return int(val)
    return 0 if (p or {}).get("currency", "IDR") == "IDR" else 2


def price_tol(p, price=None):
    """Tick-based comparison tolerance as Decimal: min(0.005, tick / 2)."""
    prof = p or {}
    if price is not None and (prof.get("tick_table") or prof.get("tick") is not None):
        tick = tick_size(prof, price)
    elif prof.get("tick_table"):
        tick = min(Decimal(str(e["tick"])) for e in prof["tick_table"])
    elif prof.get("tick") is not None:
        tick = Decimal(str(prof["tick"]))
    else:
        tick = Decimal("10") ** -price_decimals(prof)
    return min(Decimal("0.005"), tick / Decimal("2"))


def money(p, amount):
    """Format a money amount using profile `p`'s currency (IDR 0 dp, others 2 dp; never strips zeros)."""
    ccy = (p or {}).get("currency", "IDR")
    if ccy == "IDR":
        n = int(_to_decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if n == 0:
            return "Rp 0"
        sign = "-" if n < 0 else ""
        return "%sRp %s" % (sign, "{:,}".format(abs(n)).replace(",", "."))
    d = _to_decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if d == 0:
        d = Decimal("0.00")
    s = "{:,.2f}".format(d)
    prefix = _CURRENCY_PREFIX.get(ccy)
    return (prefix + s) if prefix is not None else ("%s %s" % (ccy, s))


def price(p, x):
    """Format a price `x` with profile `p`'s price_decimals (always fixed places; IDR as Rp)."""
    ccy = (p or {}).get("currency", "IDR")
    dec = price_decimals(p)
    if ccy == "IDR" and dec == 0:
        return money(p, x)
    step = Decimal("1") if dec <= 0 else Decimal("10") ** -dec
    d = _to_decimal(x).quantize(step, rounding=ROUND_HALF_UP)
    if d == 0:
        d = Decimal("0").quantize(step)
    s = ("{:,." + str(dec) + "f}").format(d) if dec > 0 else "{:,}".format(int(d))
    if dec > 2:
        return s
    prefix = _CURRENCY_PREFIX.get(ccy)
    return (prefix + s) if prefix is not None else ("%s %s" % (ccy, s))


def fees(p, cfg=None):
    """Return (buy_fee_pct, sell_fee_pct) as floats from profile `p`, overridden by `cfg`."""
    pf = (p or {}).get("fees") or {}
    c = cfg or {}
    cf = c.get("fees") if isinstance(c.get("fees"), dict) else {}
    out = []
    for key in ("buy_fee_pct", "sell_fee_pct"):
        val = None
        for src in (c, cf, pf):
            if src.get(key) is not None:
                val = float(src[key])
                break
        val = 0.0 if val is None else val
        if val < 0:
            raise ValueError("%s must be >= 0, got %r" % (key, val))
        out.append(val)
    return out[0], out[1]


MONEY_LIMIT_ALIASES = (
    ("max_loss_per_trade", "max_loss_per_trade_usd"),
    ("max_daily_loss", "max_daily_loss_usd"),
    ("max_order", "max_order_usd"),
    ("min_order", "min_order_usd"),
)


def base_symbol(p, sym):
    """Normalize `sym` to uppercase and strip profile `p`'s yahoo_suffix (e.g. '.JK')."""
    s = str(sym or "").strip().upper()
    suf = ((p or {}).get("yahoo_suffix") or "").upper()
    if suf and len(s) > len(suf) and s.endswith(suf):
        return s[:-len(suf)]
    return s


def yahoo_symbol(p, sym):
    """Format `sym` for Yahoo Finance using profile `p`'s suffix (e.g. '.JK' for IDX)."""
    s = str(sym).strip().upper()
    suf = (p or {}).get("yahoo_suffix") or ""
    if suf:
        return s if s.endswith(suf.upper()) else s + suf
    return s.replace(".", "-")


def merge_config(cfg, defaults=None):
    """Merge user config over optional defaults, resolving *_usd aliases.
    Returns (merged_dict, notices). If both new and old keys are set, new wins."""
    raw = cfg or {}
    out = dict(defaults or {})
    out.update(raw)
    notices = []
    for new_key, old_key in MONEY_LIMIT_ALIASES:
        has_new = new_key in raw
        has_old = old_key in raw
        if has_new and has_old:
            out[new_key] = raw[new_key]
            notices.append("config sets both %s and %s: using %s" % (new_key, old_key, new_key))
        elif has_old:
            out[new_key] = raw[old_key]
        out.pop(old_key, None)
    return out, notices


ORDER_FIELDS = ("symbol", "side", "qty", "notional", "type", "time_in_force", "limit_price",
                "stop_price", "trail_price", "trail_percent", "extended_hours", "client_order_id",
                "order_class", "take_profit_limit_price", "stop_loss_stop_price",
                "stop_loss_limit_price", "advanced_instructions", "market")


def order_fingerprint(order):
    """Short sha256 identifying the exact order checked by trader-risk and shown by trader-broker."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}
    if not core.get("stop_loss_stop_price"):
        plan = order.get("plan")
        if isinstance(plan, dict) and plan.get("stop") is not None:
            core["plan_stop"] = plan["stop"]
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
