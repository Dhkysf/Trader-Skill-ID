#!/usr/bin/env python3
"""Shared market profiles and clock helpers for Trader-Skill-ID. Standard library only."""

import datetime
import json
import os
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


def load(name="us"):
    """Load and cache a market profile by name (default: 'us')."""
    key = (name or "us").strip().lower()
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


def round_tick(p, price, mode="nearest"):
    """Round `price` to the profile's tick size using mode 'down', 'up', or 'nearest'."""
    rounding = _ROUND_MODES.get(mode)
    if rounding is None:
        raise ValueError("unknown round_tick mode %r; expected down, up, or nearest" % (mode,))
    if isinstance(price, Decimal):
        d = price
    elif isinstance(price, float):
        d = Decimal(repr(price))
    else:
        d = Decimal(str(price))
    step = Decimal(str(p["tick"]))
    return (d / step).to_integral_value(rounding=rounding) * step


_CURRENCY_PREFIX = {"USD": "$"}


def from_config(cfg_or_path=None):
    """Load the market profile named in a config dict or JSON file (default: 'us')."""
    if isinstance(cfg_or_path, dict):
        return load(cfg_or_path.get("market") or "us")
    path = cfg_or_path or "trader/config.json"
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict):
            return load(doc.get("market") or "us")
    return load("us")


def money(p, amount):
    """Format `amount` using profile `p`'s currency."""
    val = float(amount)
    s = "{:,.2f}".format(val)
    if s.endswith(".00"):
        s = s[:-3]
    if s == "-0":
        s = "0"
    ccy = (p or {}).get("currency", "USD")
    prefix = _CURRENCY_PREFIX.get(ccy)
    return (prefix + s) if prefix is not None else ("%s %s" % (ccy, s))


MONEY_LIMIT_ALIASES = (
    ("max_loss_per_trade", "max_loss_per_trade_usd"),
    ("max_daily_loss", "max_daily_loss_usd"),
    ("max_order", "max_order_usd"),
    ("min_order", "min_order_usd"),
)


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
