#!/usr/bin/env python3
"""Position sizing for trader-budget. Standard library only, no network.

Default mode: sizes ONE day trade from trader/plan.json (written by
trader-exit) to your budget and your max loss per trade, then writes one
manual IDX bracket order (entry, stop-loss, take-profit) to trader/orders.json.
It never places anything: trader-risk checks the order and trader-broker asks
you yes or no.

    python size.py                                   # trader/plan.json + trader/config.json
    python size.py --write                           # write trader/orders.json
    python size.py --limit                           # a limit order at the plan's entry
    python size.py --limit 9850 --write              # a limit order at Rp 9.850
    python size.py --now "2026-11-23 09:35" --json   # pin the clock (WIB)

How many shares. Whole lots only (100 shares per lot on IDX):

    shares = floor (in whole lots) of the smallest of
      max loss       max_loss_per_trade / risk per share (incl. fees)
      position cap   budget x max_position_pct / entry
      max order      max_order / entry
      cash           (budget minus the cash buffer) / entry
                     (and no more than the cash in trader/portfolio.json, if you have one)

The entry it sizes at: a limit order's limit price; for a market order the
plan's entry, or the price in trader/prices.json if that is fresh (under 15
minutes old) and higher, because a price that ran up since the plan means a
bigger loss at the same stop. Zero lots (the stop is too far away for your
max loss) is a plain refusal: no order is written. So is a reward:risk under
min_reward_risk (the price ran toward the target since the plan).

Weights mode (kept from v1): split a budget across a list of stocks by weight.

    python size.py --weights BBCA=40,BBRI=30,TLKM=30
    python size.py --targets my-weights.json --budget 10000000 --write
    python size.py --weights ... --whole-shares --prices trader/prices.json

Money that cannot be invested is reported as "left idle", never hidden.
"""

import argparse
import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import os
import sys

_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market  # noqa: E402

_IDX = market.load("idx")

# v2 defaults: the contract's config.example.json. Missing keys fall back to these.
DEFAULTS = {
    "market": "idx",
    "budget": None,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order": None,
    "min_order": None,
    "max_loss_per_trade": None,
    "max_daily_loss": None,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "require_stop": True,
    "no_entries_before": "09:15",
    "no_entries_after": "15:30",
    "flat_by": "15:45",
    "fractional": False,
    "broker": "manual",
    "paper": True,
    "blocked": [],
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
}
EPS = 1e-9
FRESH_MINUTES = 15
SETUP_WORDS = {"orb": "opening-range breakout", "flag": "flag", "bounce": "oversold bounce"}


class SizeError(Exception):
    pass


# ---------------------------------------------------------------- time

def parse_now(text, p=None):
    """ISO time -> naive UTC. A time without an offset is taken as market local time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise SizeError("--now wants a time like \"2026-11-23 09:35\" (WIB) or ...Z (UTC)")
    if dt.tzinfo is None:
        return market.local_to_utc(p or _IDX, dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_utc(text):
    """"2026-10-19T14:52:13Z" -> naive UTC, or None."""
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def utc_iso(now_utc=None):
    now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return now_utc.replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- inputs

def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise SizeError("no %s at %s" % (what, path))
    except json.JSONDecodeError as e:
        raise SizeError("%s is not valid JSON: %s" % (path, e))


def _place_label(p):
    prof = p or _IDX
    return prof.get("tz_label") or prof.get("timezone") or "WIB"


def load_config(path):
    raw = read_json(path, "config") if (path and os.path.exists(path)) else {}
    p = market.from_config(raw)
    return market.merge_config(raw, DEFAULTS, p=p)[0]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _lookup(mapping, sym, p=None):
    if not isinstance(mapping, dict):
        return None
    prof = p or _IDX
    want = market.base_symbol(prof, sym)
    if want in mapping:
        return mapping[want]
    for k, v in mapping.items():
        if market.base_symbol(prof, k) == want:
            return v
    return None


def parse_weights(data, p=None):
    """Accept a weights file, a {ticker: weight} dict or a list of rows.

    Returns [{"ticker", "name", "weight"}] with weight as a float."""
    if isinstance(data, dict) and "weights" in data:
        data = data["weights"]
    rows = []
    if isinstance(data, dict):
        for t, w in data.items():
            rows.append({"ticker": t, "name": "", "weight": w})
    elif isinstance(data, list):
        for i, r in enumerate(data):
            if not isinstance(r, dict):
                raise SizeError("weights[%d] is not an object" % i)
            t = r.get("ticker") or r.get("symbol")
            w = r.get("weight", r.get("weight_pct", r.get("pct")))
            if not t or w is None:
                raise SizeError("weights[%d] needs a ticker and a weight" % i)
            rows.append({"ticker": t, "name": r.get("name", ""), "weight": w})
    else:
        raise SizeError("weights must be a list or an object")
    prof = p or _IDX
    out = []
    for r in rows:
        try:
            w = float(r["weight"])
        except (TypeError, ValueError):
            raise SizeError("weight for %s is not a number: %r" % (r["ticker"], r["weight"]))
        out.append({"ticker": market.base_symbol(prof, r["ticker"]), "name": r["name"] or "", "weight": w})
    return out


def weights_from_arg(text, p=None):
    """BBCA=40,BBRI=30 -> {ticker: weight}"""
    prof = p or _IDX
    out = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SizeError("--weights wants TICKER=WEIGHT pairs, got %r" % part)
        t, w = part.split("=", 1)
        out[market.base_symbol(prof, t)] = w.strip()
    return out


def load_prices(path, p=None):
    if not path:
        return {}
    prof = p or _IDX
    data = read_json(path, "prices")
    prices = data.get("prices", data) if isinstance(data, dict) else {}
    out = {}
    for t, val in prices.items():
        try:
            out[market.base_symbol(prof, t)] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def price_time(doc, sym, p=None):
    """When this symbol's price is from: the quote's own time (detail[sym].time), else when it
    was fetched (detail[sym].fetched), else the file's as_of."""
    det = _lookup((doc or {}).get("detail"), sym, p) or {}
    for key in ("time", "fetched"):
        t = parse_utc(det.get(key))
        if t:
            return t
    return parse_utc((doc or {}).get("as_of"))


def fresh_price(doc, sym, now_utc, minutes=FRESH_MINUTES, p=None):
    """(price, fetched_utc, fresh) for sym from a prices.json doc, or (None, None, False)."""
    if not isinstance(doc, dict):
        return None, None, False
    px = _f(_lookup(doc.get("prices"), sym, p))
    if px is None or px <= 0:
        return None, None, False
    t = price_time(doc, sym, p=p)
    if t is None:
        return px, None, False
    age = (now_utc - t).total_seconds()
    return px, t, -60 <= age <= minutes * 60


# ---------------------------------------------------------------- money helpers

def shares_for(usd, per_share, lot=1):
    """Whole shares that fit in usd at per_share (or whole lots when lot > 1)."""
    lot_i = max(1, int(lot))
    u = market._to_decimal(usd)
    per = market._to_decimal(per_share) * lot_i
    if per <= 0 or u <= 0:
        return 0
    return int(u // per) * lot_i


def _px(x, p=None):
    return market.price(p or _IDX, x)


def _ord_price(x, p=None):
    dec = market.price_decimals(p)
    if dec > 0:
        return ("{:." + str(dec) + "f}").format(
            market._to_decimal(x).quantize(Decimal("10") ** -dec, rounding=ROUND_HALF_UP))
    f = float(x)
    return str(int(round(f))) if abs(f - round(f)) < 1e-9 else str(x)


def _num(x):
    """1250 -> "1250", 1118.13 -> "1118.13"."""
    x = round(float(x), 2)
    if abs(x - round(x)) < 0.005:
        return str(int(round(x)))
    return "%.2f" % x


def money(x, p=None):
    return market.money(p or _IDX, x)


# ---------------------------------------------------------------- plan mode (the default)

def size_trade(plan, cfg, budget=None, limit=None, price=None, cash=None, today=None):
    """Pure function: one plan + your rules -> the sizing (a dict). qty may be 0.

    limit  the limit price for a limit order (None = market)
    price  a FRESH latest price; a market order is sized at the higher of it and the plan's entry
    cash   the cash in trader/portfolio.json, if there is one
    today  market date (YYYY-MM-DD); a plan for another day is refused"""
    market_id = (cfg or {}).get("market") or (plan.get("market") if isinstance(plan, dict) else None) or "idx"
    p = market.load(market_id)
    c, cfg_notices = market.merge_config(cfg, DEFAULTS, p=p)
    dec = market.price_decimals(p)
    out_dec = max(2, dec)
    tol = float(market.price_tol(p))
    lot = int(p.get("lot", 1))
    buy_fee_pct, sell_fee_pct = market.fees(p, c)
    has_fees = buy_fee_pct > 0 or sell_fee_pct > 0
    if not isinstance(plan, dict):
        raise SizeError("the plan is not a JSON object")
    sym = market.base_symbol(p, plan.get("symbol"))
    if not sym:
        raise SizeError("the plan has no symbol (run trader-exit)")
    side = str(plan.get("side") or "buy").strip().lower()
    if side == "short":
        side = "sell"
    if side != "buy":
        if side != "sell" or not market.allows_short(p, c):
            raise SizeError("this pack sizes long (buy) day trades only; the plan says %r" % side)
    long = (side == "buy")
    if today and plan.get("date") and str(plan["date"]) != today:
        raise SizeError("the plan is for %s and today is %s (%s): make a new plan with trader-exit"
                        % (plan["date"], today, _place_label(p)))
    entry_plan, stop, target = _f(plan.get("entry")), _f(plan.get("stop")), _f(plan.get("target"))
    for name, v in (("entry", entry_plan), ("stop", stop), ("target", target)):
        if v is None or v <= 0:
            raise SizeError("the plan needs a positive %s (run trader-exit); a bracket order needs entry, "
                            "stop and target" % name)
    blocked = {market.base_symbol(p, b) for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s is on your blocked list" % sym)

    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("no budget: pass --budget or set \"budget\" in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct") or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct must be between 0 and 100")

    _norm = lambda x: float(x)
    if limit is not None:
        ref, ref_from = _norm(limit), "limit"
    elif price is not None and ((long and _norm(price) > _norm(entry_plan))
                                or (not long and _norm(price) < _norm(entry_plan))):
        ref, ref_from = _norm(price), "price"
    else:
        ref, ref_from = _norm(entry_plan), "plan"
    stop, target = _norm(stop), _norm(target)
    if long:
        if stop >= ref:
            raise SizeError("the stop %s is not below the entry %s; a long trade needs its stop underneath"
                            % (_px(stop, p), _px(ref, p)))
        if target <= ref:
            raise SizeError("the target %s is not above the entry %s: the move has already happened. "
                            "Skip it or make a new plan with trader-exit" % (_px(target, p), _px(ref, p)))
    else:
        if stop <= ref:
            raise SizeError("the stop %s is not above the entry %s; a short trade needs its stop above"
                            % (_px(stop, p), _px(ref, p)))
        if target >= ref:
            raise SizeError("the target %s is not below the entry %s: the move has already happened. "
                            "Skip it or make a new plan with trader-exit" % (_px(target, p), _px(ref, p)))
    d_entry = market._to_decimal(ref)
    d_stop = market._to_decimal(stop)
    d_target = market._to_decimal(target)
    d_risk = (d_entry - d_stop) if long else (d_stop - d_entry)
    d_reward = (d_target - d_entry) if long else (d_entry - d_target)
    risk = float(d_risk)
    d_buy = market._to_decimal(buy_fee_pct) / Decimal("100")
    d_sell = market._to_decimal(sell_fee_pct) / Decimal("100")
    risk_per_share_net = d_risk + (d_entry * d_buy + d_stop * d_sell if long else d_entry * d_sell + d_stop * d_buy)

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    available = budget - cash_buffer
    cash_note = "budget %s minus the %s cash buffer" % (money(budget, p), money(cash_buffer, p))
    if cash is not None and cash - cash_buffer < available - tol:
        available = cash - cash_buffer
        cash_note = "cash %s in trader/portfolio.json minus the %s buffer" % (money(cash, p), money(cash_buffer, p))
    available = max(round(available, 2), 0.0)

    limits = []
    max_loss = _f(c.get("max_loss_per_trade"))
    if max_loss:
        per_loss = risk_per_share_net if has_fees else risk
        per_lot_loss = per_loss * lot
        how_loss = "%s max loss / %s per lot%s" % (
            money(max_loss, p), money(per_lot_loss, p), " incl. fees" if has_fees else "")
        limits.append({"name": "max loss", "usd": max_loss, "per": float(per_loss),
                       "shares": shares_for(max_loss, per_loss, lot=lot), "how": how_loss})
    cap_pct = _f(c.get("max_position_pct"))
    if cap_pct:
        cap = round(budget * cap_pct / 100.0, 2)
        limits.append({"name": "position cap", "usd": cap, "per": ref, "shares": shares_for(cap, ref, lot=lot),
                       "how": "%s%% of %s = %s / %s" % (_num(cap_pct), money(budget, p), money(cap, p), _px(ref, p))})
    max_order = _f(c.get("max_order"))
    if max_order:
        limits.append({"name": "max order", "usd": max_order, "per": ref, "shares": shares_for(max_order, ref, lot=lot),
                       "how": "%s / %s" % (money(max_order, p), _px(ref, p))})
    d_entry_fee = d_buy if long else d_sell
    entry_fee_pct = buy_fee_pct if long else sell_fee_pct
    cash_per = d_entry * (Decimal("1") + d_entry_fee) if entry_fee_pct > 0 else d_entry
    cash_shares = shares_for(available, cash_per, lot=lot)
    if cash_shares > 0 and entry_fee_pct > 0:
        step = Decimal("1") if p.get("currency") == "IDR" else Decimal("0.01")
        d_avail = market._to_decimal(available)
        while cash_shares > 0:
            val = d_entry * cash_shares
            fee = (val * d_entry_fee).quantize(step, rounding=ROUND_HALF_UP)
            if val + fee <= d_avail:
                break
            cash_shares -= lot
    cash_how = "%s = %s / %s%s" % (cash_note, money(available, p), _px(ref, p),
                                   " incl. buy fee" if buy_fee_pct > 0 else "")
    limits.append({"name": "cash", "usd": available, "per": float(cash_per),
                   "shares": cash_shares, "how": cash_how})

    qty = max(0, min(l["shares"] for l in limits))
    bound = [l["name"] for l in limits if l["shares"] == qty]
    for l in limits:
        l["binds"] = l["name"] == bound[0]
    money_q = Decimal("10") ** -out_dec
    cost = round(float(d_entry * qty), out_dec)
    loss = float(((risk_per_share_net if has_fees else d_risk) * qty).quantize(money_q, rounding=ROUND_HALF_UP))
    refusal = None
    if qty == 0:
        if lot > 1:
            if bound[0] == "max loss":
                lot_risk = (risk_per_share_net if has_fees else market._to_decimal(risk)) * lot
                refusal = ("1 lot (%d shares) risks %s%s (entry %s minus stop %s), more than your %s max loss "
                           "per trade. No order. Skip this trade, or plan a closer stop with trader-exit."
                           % (lot, money(lot_risk, p), " incl. fees" if has_fees else "",
                              _px(ref, p), _px(stop, p), money(max_loss, p)))
            else:
                lot_cost = money(cash_per * lot, p) + " incl. buy fee" if (bound[0] == "cash" and buy_fee_pct > 0) else money(ref * lot, p)
                refusal = ("1 lot (%d shares) of %s costs %s, more than your %s limit (%s). No order."
                           % (lot, sym, lot_cost, bound[0],
                              limits[[l["name"] for l in limits].index(bound[0])]["how"]))
        elif bound[0] == "max loss":
            refusal = ("one share risks %s (entry %s minus stop %s), more than your %s max loss per trade. "
                       "No order. Skip this trade, or plan a closer stop with trader-exit."
                       % (_px(risk, p), _px(ref, p), _px(stop, p), money(max_loss, p)))
        else:
            refusal = ("one share of %s costs %s, more than your %s limit (%s). No order."
                       % (sym, _px(ref, p), bound[0], limits[[l["name"] for l in limits].index(bound[0])]["how"]))
    elif _f(c.get("min_reward_risk")) and (d_reward / d_risk) < market._to_decimal(c["min_reward_risk"]) - Decimal("1e-9"):
        refusal = ("reward:risk %.2f (target %s, entry %s, stop %s) is under your minimum %s, so trader-risk "
                   "would block it. No order. Skip it, or make a new plan with trader-exit."
                   % (float(d_reward / d_risk), _px(target, p), _px(ref, p), _px(stop, p), _num(c["min_reward_risk"])))
    elif cost < float(c.get("min_order") or 0) - tol:
        refusal = ("%d share%s of %s is %s, under your %s minimum order. No order."
                   % (qty, "" if qty == 1 else "s", sym, money(cost, p), money(c["min_order"], p)))
    out = {
        "symbol": sym, "side": side, "setup": plan.get("setup", ""), "date": plan.get("date"),
        "entry_time": plan.get("entry_time", ""), "entry_plan": _norm(entry_plan),
        "entry": ref, "entry_from": ref_from, "stop": stop, "target": target,
        "risk_per_share": risk, "reward_risk": round(float(d_reward / d_risk), 2),
        "stop_label": plan.get("stop_label", ""), "target_label": plan.get("target_label", ""),
        "budget": budget, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer, "cash_available": available,
        "max_loss_per_trade_usd": max_loss, "limits": limits, "qty": qty, "bound_by": bound[0],
        "cost": cost, "max_loss": loss, "flat_by": plan.get("flat_by") or c.get("flat_by"),
        "order_type": "limit" if limit is not None else "market", "refusal": refusal,
        "notices": cfg_notices,
    }
    out.update({"market": p["id"], "lot": lot, "lots": qty // lot,
                "buy_fee_pct": buy_fee_pct, "sell_fee_pct": sell_fee_pct})
    pc = _f(plan.get("prev_close"))
    if pc is not None and pc > 0:
        out["prev_close"] = pc
    return out


def bracket_order(s):
    """The one proposed manual bracket order plus why and plan."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    p = market.load(s.get("market") or "idx")
    o = {"symbol": s["symbol"], "side": s.get("side", "buy"), "qty": str(int(s["qty"])), "type": s["order_type"],
         "time_in_force": "day", "market": p["id"]}
    if s["order_type"] == "limit":
        o["limit_price"] = _ord_price(s["entry"], p)
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "day trade")
    bound_text = {"max loss": "%s max loss per trade" % money(s["max_loss_per_trade_usd"] or 0, p),
                  "position cap": "position cap", "max order": "max order",
                  "cash": "cash after the buffer"}[s["bound_by"]]
    lot = int(p.get("lot", 1))
    lots = s["qty"] // lot
    fee_note = " incl. fees" if (s.get("buy_fee_pct") or s.get("sell_fee_pct")) else ""
    why = ("%s on %s: %d lot%s (%d shares), bound by your %s (max loss%s %s at the stop)"
           % (setup, s["symbol"], lots, "" if lots == 1 else "s", s["qty"], bound_text,
              fee_note, money(s["max_loss"], p)))
    plan_info = {"entry": s["entry"], "stop": s["stop"], "target": s["target"],
                 "risk_per_share": s["risk_per_share"], "max_loss": s["max_loss"], "setup": s["setup"],
                 "entry_time": s["entry_time"], "flat_by": s["flat_by"]}
    if s.get("prev_close") is not None:
        plan_info["prev_close"] = s["prev_close"]
    o.update({
        "order_class": "bracket",
        "take_profit_limit_price": _ord_price(s["target"], p),
        "stop_loss_stop_price": _ord_price(s["stop"], p),
        "why": why,
        "plan": plan_info,
    })
    return o


def plan_report(s, order, notes=()):
    p = market.load(s.get("market") or "idx")
    lot = int(p.get("lot", 1))
    has_fees = bool(s.get("buy_fee_pct") or s.get("sell_fee_pct"))
    lines = []
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "setup")
    lines.append("%s buy, %s, entry %s%s" % (s["symbol"], setup, _px(s["entry_plan"], p),
                                            (" at " + s["entry_time"]) if s["entry_time"] else ""))
    lines.append("Stop %s%s. Target %s%s." % (_px(s["stop"], p), (": " + s["stop_label"]) if s["stop_label"] else "",
                                             _px(s["target"], p),
                                             (": " + s["target_label"]) if s["target_label"] else ""))
    for n in notes:
        lines.append(n)
    src = {"plan": "the plan's entry", "price": "the latest price, above the plan's entry",
           "limit": "your limit price"}[s["entry_from"]]
    lines.append("Sized at %s (%s). Risk %s a share (entry %s minus stop %s). Reward:risk %.2f."
                 % (_px(s["entry"], p), src, _px(s["risk_per_share"], p), _px(s["entry"], p), _px(s["stop"], p),
                    s["reward_risk"]))
    lines.append("")
    lines.append("Limits (whole lots of %d shares; the smallest one wins):" % lot)
    for l in s["limits"]:
        lots_n = l["shares"] // lot
        lines.append("  %-13s %-54s %3d lots (%d shares)%s"
                     % (l["name"], l["how"], lots_n, l["shares"], "  <- binds" if l["binds"] else ""))
    lines.append("")
    if order is None:
        lines.append("No order: " + s["refusal"])
        lines.append("Education and tooling, not financial advice.")
        return "\n".join(lines)
    lots_n = s["qty"] // lot
    fee_note = " incl. fees" if has_fees else ""
    lines.append("Size: %d lot%s (%d shares) of %s = %s at %s. Max loss%s at the stop: %s."
                 % (lots_n, "" if lots_n == 1 else "s", s["qty"], s["symbol"],
                    money(s["cost"], p), _px(s["entry"], p), fee_note, money(s["max_loss"], p)))
    lines.append("A stop is an order, not a promise: in a fast market it can fill below %s." % _px(s["stop"], p))
    lines.append("")
    how = "limit %s" % _px(order["limit_price"], p) if order["type"] == "limit" else "market"
    lines.append("Proposed manual IDX order (nothing has been placed):")
    lines.append("  buy %d lots (%s shares) %s, %s, day, take-profit %s, stop-loss %s"
                 % (s["qty"] // lot, order["qty"], order["symbol"], how,
                    _px(order["take_profit_limit_price"], p), _px(order["stop_loss_stop_price"], p)))
    if s["flat_by"]:
        lines.append("Flat by %s %s: anything still open then gets closed (trader-alerts rings, "
                     "trader-broker flatten)." % (s["flat_by"], _place_label(p)))
    lines.append("")
    lines.append("Next: trader-risk checks it, then trader-broker asks you yes or no.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- weights mode (v1)

def normalise(rows, blocked=(), top=None, p=None):
    """Drop blocked and non-positive weights, keep the top N, renormalise to 100."""
    prof = p or _IDX
    blocked = {market.base_symbol(prof, b) for b in (blocked or [])}
    dropped, keep, seen = [], [], set()
    for r in rows:
        if r["ticker"] in seen:
            raise SizeError("%s is listed twice in the weights" % r["ticker"])
        seen.add(r["ticker"])
        if r["ticker"] in blocked:
            dropped.append({"ticker": r["ticker"], "reason": "on your blocked list"})
        elif r["weight"] <= 0:
            dropped.append({"ticker": r["ticker"], "reason": "weight is zero or negative"})
        else:
            keep.append(dict(r))
    keep.sort(key=lambda r: -r["weight"])
    if top:
        for r in keep[top:]:
            dropped.append({"ticker": r["ticker"], "reason": "outside the top %d" % top})
        keep = keep[:top]
    total = sum(r["weight"] for r in keep)
    for r in keep:
        r["source_weight"] = r["weight"]
        r["weight"] = 100.0 * r["weight"] / total if total else 0.0
    return keep, dropped


def allocate(rows, investable, cap):
    """Exact (unrounded) dollars per ticker with the cap enforced.

    Proportional to weight; any stock over the cap is pinned at the cap and
    the rest of the money is shared over the others, repeated until no stock
    is over. Returns ({ticker: dollars}, set of capped tickers)."""
    alloc, capped = {}, set()
    active = [r for r in rows]
    money_left = investable
    while active:
        wsum = sum(r["weight"] for r in active)
        trial = {r["ticker"]: money_left * r["weight"] / wsum for r in active}
        over = [r for r in active if trial[r["ticker"]] > cap + EPS]
        if not over:
            alloc.update(trial)
            break
        for r in over:
            alloc[r["ticker"]] = cap
            capped.add(r["ticker"])
            money_left -= cap
        active = [r for r in active if r["ticker"] not in capped]
        if money_left <= EPS:
            for r in active:
                alloc[r["ticker"]] = 0.0
            break
    return alloc, capped


def round_to_unit(exact, capped, order, cap, unit):
    """Round to whole dollars (unit 1) or cents (unit 0.01) and keep the total.

    The total placed is the exact total rounded DOWN to the unit, so it never
    spends money you do not have. Each slice is rounded to the nearest unit,
    then the difference (usually one unit) goes to the biggest stock that is
    not capped, then the next, never pushing anyone over the cap."""
    def units(x):
        return int(math.floor(x / unit + EPS))

    cap_u = units(cap)
    total_u = units(sum(exact.values()))
    out = {}
    for t, v in exact.items():
        out[t] = cap_u if t in capped else int(math.floor(v / unit + 0.5 + EPS))
    diff = total_u - sum(out.values())
    takers = [t for t in order if t not in capped]
    guard = 0
    while diff != 0 and takers and guard < 100000:
        moved = False
        for t in takers:
            if diff == 0:
                break
            if diff > 0 and out[t] + 1 <= cap_u:
                out[t] += 1
                diff -= 1
                moved = True
            elif diff < 0 and out[t] > 0:
                out[t] -= 1
                diff += 1
                moved = True
        if not moved:
            break
        guard += 1
    return {t: round(u * unit, 2) for t, u in out.items()}


def whole_shares(dollars, prices, order, cap, cash, lot=1):
    """Whole shares (or whole lots when lot > 1): floor each slice, then buy one
    more unit at a time for the stock furthest below its slice while cash lasts
    and the cap holds."""
    lot = max(1, int(lot))
    shares = {}
    for t in order:
        lp = prices[t] * lot
        shares[t] = (int(math.floor(dollars[t] / lp + EPS)) * lot) if (dollars[t] > 0 and lp > 0) else 0
    spent = sum(shares[t] * prices[t] for t in order)
    left = cash - spent
    while True:
        best, gap = None, None
        for t in order:
            p = prices[t]
            lp = p * lot
            if lp <= 0 or lp > left + EPS or (shares[t] + lot) * p > cap + EPS:
                continue
            g = dollars[t] - shares[t] * p
            if best is None or g > gap + EPS:
                best, gap = t, g
        if best is None:
            break
        shares[best] += lot
        left -= prices[best] * lot
    return shares


def size(rows, cfg, budget=None, prices=None, whole=None, cents=False, top=None):
    """Weights mode. Pure function: weights + rules -> the full sizing result (a dict)."""
    c, cfg_notices = market.merge_config(cfg)
    prof = market.from_config(c)
    lot = int(prof.get("lot", 1))
    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("no budget: pass --budget or set \"budget\" in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct", 10))
    cap_pct = float(c.get("max_position_pct", 25))
    min_order = float(c.get("min_order", 5) or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct must be between 0 and 100")
    if not 0 < cap_pct <= 100:
        raise SizeError("max_position_pct must be above 0 and at most 100")
    if whole is None:
        whole = not c.get("fractional", True)
    prices = {market.base_symbol(prof, k): v for k, v in (prices or {}).items()}

    keep, dropped = normalise(rows, c.get("blocked"), top, p=prof)
    if not keep:
        raise SizeError("nothing to size: no weights left after the blocked list")

    cash_buffer = round(budget * buf_pct / 100.0, 2)
    investable = round(budget - cash_buffer, 2)
    cap = round(budget * cap_pct / 100.0, 2)
    unit = 0.01 if (cents or whole) else 1.0

    if whole:
        missing = [r["ticker"] for r in keep if not prices.get(r["ticker"])]
        if missing:
            raise SizeError("whole shares need a price for: %s (add them to trader/prices.json, "
                            "e.g. with trader-alerts: alerts.py quote %s --write)"
                            % (", ".join(missing), " ".join(missing)))

    while True:
        live = [dict(r) for r in keep]
        tot = sum(r["source_weight"] for r in live)
        for r in live:
            r["weight"] = 100.0 * r["source_weight"] / tot
        exact, capped = allocate(live, investable, cap)
        order = [r["ticker"] for r in sorted(live, key=lambda r: -exact[r["ticker"]])]
        dollars = round_to_unit(exact, capped, order, cap, unit)
        shares = None
        if whole:
            shares = whole_shares(dollars, prices, order, cap, sum(dollars.values()), lot=lot)
            dollars = {t: round(shares[t] * prices[t], 2) for t in order}
        small = [r for r in live if dollars[r["ticker"]] < min_order - EPS]
        if not small:
            break
        worst = min(small, key=lambda r: (r["source_weight"], r["ticker"]))
        if whole and shares is not None and shares[worst["ticker"]] == 0 and prices.get(worst["ticker"], 0) > 0:
            if lot > 1:
                reason = ("one lot (%d shares) costs %s, more than its slice; it cannot be bought in whole lots"
                          % (lot, money(prices[worst["ticker"]] * lot, prof)))
            else:
                reason = ("one share costs %s, more than its slice; it cannot be bought in whole shares"
                          % money(prices[worst["ticker"]], prof))
        else:
            reason = "its slice (%s) is under your %s minimum order" % (
                money(dollars[worst["ticker"]], prof), money(min_order, prof))
        dropped.append({"ticker": worst["ticker"], "reason": reason})
        keep = [r for r in keep if r["ticker"] != worst["ticker"]]
        if not keep:
            raise SizeError("every slice is under your minimum order; raise the budget or hold fewer stocks")

    positions = []
    for r in sorted(live, key=lambda r: -r["weight"]):
        t = r["ticker"]
        p = {"ticker": t, "name": r["name"], "weight": round(r["weight"], 2),
             "source_weight": r["source_weight"], "dollars": dollars[t],
             "capped": t in capped}
        if prices.get(t):
            p["price"] = prices[t]
            p["shares"] = shares[t] if whole else round(dollars[t] / prices[t], 4)
        positions.append(p)
    invested = round(sum(p["dollars"] for p in positions), 2)
    return {
        "market": prof["id"],
        "budget": budget, "cash_buffer_pct": buf_pct, "cash_buffer": cash_buffer,
        "investable": investable, "max_position_pct": cap_pct, "cap": cap,
        "min_order_usd": min_order, "whole_shares": bool(whole),
        "positions": positions, "invested": invested,
        "idle": round(investable - invested, 2), "dropped": dropped,
        "notices": cfg_notices,
    }


def orders_from(result, source=""):
    """Weights mode: proposed buy orders, one per position."""
    prof = market.load(result.get("market") or "idx")
    out = []
    for p in result["positions"]:
        if p["dollars"] <= 0:
            continue
        why = "%.2f%% of the split" % p["weight"]
        if source:
            why = "%s, weights from %s" % (why, source)
        if p["capped"]:
            why += "; capped at %s%% of the %s budget" % (_num(result["max_position_pct"]), money(result["budget"], prof))
        o = {"symbol": p["ticker"], "side": "buy"}
        if result["whole_shares"]:
            o["qty"] = str(int(p["shares"]))
        else:
            o["notional"] = _num(p["dollars"])
        o.update({"type": "market", "time_in_force": "day", "why": why})
        out.append(o)
    return out


def report(result, orders, source=""):
    """Weights mode table."""
    r = result
    prof = market.load(r.get("market") or "idx")
    lot = int(prof.get("lot", 1))
    lines = []
    if source:
        lines.append("Weights from: %s" % source)
    lines.append("Budget %s, cash buffer %s%% = %s, investing %s, cap %s%% = %s per stock"
                 % (money(r["budget"], prof), _num(r["cash_buffer_pct"]), money(r["cash_buffer"], prof),
                    money(r["investable"], prof), _num(r["max_position_pct"]), money(r["cap"], prof)))
    lines.append("")
    has_price = any("price" in pos for pos in r["positions"])
    head = "%-7s %-22s %8s %11s" % ("ticker", "name", "weight", "amount")
    if has_price:
        head += " %10s %10s" % ("price", "shares")
    lines.append(head + "  note")
    for pos in r["positions"]:
        row = "%-7s %-22s %7.2f%% %11s" % (pos["ticker"], (pos["name"] or "")[:22], pos["weight"], money(pos["dollars"], prof))
        if has_price:
            if lot > 1 and r.get("whole_shares") and "shares" in pos:
                qty_str = "%d lots (%d shares)" % (int(pos["shares"]) // lot, int(pos["shares"]))
            else:
                qty_str = pos.get("shares", "")
            row += " %10s %10s" % (money(pos["price"], prof) if "price" in pos else "", qty_str)
        if pos["capped"]:
            row += "  capped at %s%%" % _num(r["max_position_pct"])
        lines.append(row)
    lines.append("%-7s %-22s %8s %11s" % ("", "invested", "", money(r["invested"], prof)))
    lines.append("%-7s %-22s %8s %11s" % ("", "cash buffer", "", money(r["cash_buffer"], prof)))
    lines.append("%-7s %-22s %8s %11s" % ("", "left idle", "", money(r["idle"], prof)))
    if r["idle"] >= 1:
        lines.append("")
        idle_why = ("whole lots do not divide evenly" if lot > 1 else "whole shares do not divide evenly") if r["whole_shares"] else "every stock is at its cap; add stocks or raise max_position_pct"
        lines.append("Left idle %s: %s" % (money(r["idle"], prof), idle_why))
    for d in r["dropped"]:
        lines.append("Dropped %s: %s" % (d["ticker"], d["reason"]))
    lines.append("")
    lines.append("Proposed manual orders (nothing has been placed):")
    for o in orders:
        if "notional" in o:
            amount = "notional \"%s\"" % o["notional"]
        elif lot > 1:
            amount = "%d lots (%d shares)" % (int(o["qty"]) // lot, int(o["qty"]))
        else:
            amount = "qty \"%s\"" % o["qty"]
        lines.append("  %s %s %s, %s, %s" % (o["side"], o["symbol"], amount, o["type"], o["time_in_force"]))
    lines.append("")
    lines.append("These buys have no stop. trader-risk blocks them while \"require_stop\" is true and applies "
                 "your day-trade limits to every buy.")
    lines.append("Next: trader-risk checks every order, then trader-broker asks you yes or no for each one.")
    lines.append("Education and tooling, not financial advice.")
    return "\n".join(lines)


# ---------------------------------------------------------------- orders file

def write_orders(path, orders, cfg, source="", now_utc=None):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    doc = {
        "created_by": "trader-budget",
        "created_at": utc_iso(now_utc),
        "status": "proposed",
        "paper": bool(cfg.get("paper", True)),
        "note": ("Proposals only. Nothing is placed until trader-risk passes each order "
                 "and you say yes to it in the chat."),
        "source": source,
        "orders": orders,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- main

def run_plan(a, cfg, cfg_notices=()):
    p = market.from_config(cfg)
    now = parse_now(a.now, p=p)
    today = market.to_local(p, now).date().isoformat()
    plan = read_json(a.plan, "plan (run trader-exit first, or use --weights for a split)")
    limit = None
    if a.limit is not None:
        if a.limit == "plan":
            limit = _f((plan or {}).get("entry"))
        else:
            limit = _f(a.limit)
            if limit is None or limit <= 0:
                raise SizeError("--limit wants a price, like --limit 9875")
    sym = market.base_symbol(p, (plan or {}).get("symbol"))
    notes, price = list(cfg_notices), None
    ppath = a.prices or ("trader/prices.json" if os.path.exists("trader/prices.json") else None)
    if ppath and limit is None and sym:
        pdoc = read_json(ppath, "prices")
        px, t, fresh = fresh_price(pdoc, sym, now, p=p)
        if plan.get("prev_close") is None:
            pc = (_lookup(pdoc.get("detail"), sym, p) or {}).get("prev_close")
            if pc is not None:
                plan = dict(plan, prev_close=pc)
        if px is not None and fresh:
            price = px
            if px > (_f(plan.get("entry")) or 0):
                notes.append("%s last %s (as of %s %s) is above the plan's entry %s, so the risk "
                             "is bigger: sized at %s." % (sym, _px(px, p), market.to_local(p, t).strftime("%H:%M"),
                                                          _place_label(p), _px(plan.get("entry"), p), _px(px, p)))
        elif px is not None:
            notes.append("%s in %s is %s: not used (older than %d minutes). Sized at the plan's entry."
                         % (sym, ppath, ("from " + market.to_local(p, t).strftime("%Y-%m-%d %H:%M") + " " + _place_label(p))
                            if t else "undated", FRESH_MINUTES))
    cash = None
    if a.portfolio and os.path.exists(a.portfolio):
        pf = read_json(a.portfolio, "portfolio")
        cash = _f(pf.get("cash")) if isinstance(pf, dict) else None
    s = size_trade(plan, cfg, a.budget, limit, price, cash, today)
    order = bracket_order(s)
    if order and a.write:
        src = "trader/plan.json (%s %s %s)" % (s["symbol"], s["setup"] or "plan", s["date"] or today)
        write_orders(a.write, [order], cfg, src, now)
    if a.json:
        print(json.dumps({"sizing": s, "orders": [order] if order else [], "notes": notes}, indent=2))
    else:
        print(plan_report(s, order, notes))
        if order and a.write:
            print("Wrote 1 proposed bracket order to %s" % a.write)
    return 0 if order else 1


def run_weights(a, cfg, cfg_notices=()):
    for n in cfg_notices:
        print("note: " + n, file=sys.stderr)
    p = market.from_config(cfg)
    source = ""
    if a.weights:
        rows = parse_weights(weights_from_arg(a.weights, p=p), p=p)
    else:
        data = read_json(a.targets, "weights file")
        rows = parse_weights(data, p=p)
        if isinstance(data, dict):
            source = data.get("source", "")
    prices = load_prices(a.prices, p=p)
    if not prices and os.path.exists("trader/prices.json") and not a.prices:
        prices = load_prices("trader/prices.json", p=p)
    whole = True if a.whole_shares else None
    result = size(rows, cfg, a.budget, prices, whole, a.cents, a.top)
    orders = orders_from(result, source)
    if a.write:
        write_orders(a.write, orders, cfg, source, parse_now(a.now, p=p))
    if a.json:
        print(json.dumps({"result": result, "orders": orders}, indent=2))
    else:
        print(report(result, orders, source))
        if a.write:
            print("Wrote %d proposed orders to %s" % (len(orders), a.write))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Size a day trade to your budget and max loss (trader-budget).")
    ap.add_argument("--plan", default="trader/plan.json", help="the trade plan (default trader/plan.json)")
    ap.add_argument("--config", default="trader/config.json", help="rules (default trader/config.json)")
    ap.add_argument("--budget", type=float, help="override the budget in the config")
    ap.add_argument("--limit", nargs="?", const="plan", metavar="PRICE",
                    help="a limit order instead of market, at the plan's entry or at PRICE")
    ap.add_argument("--prices", help="prices JSON (default trader/prices.json if it exists)")
    ap.add_argument("--portfolio", default="trader/portfolio.json",
                    help="your account; its cash caps the size if it exists")
    ap.add_argument("--now", help="pretend it is this WIB time, e.g. \"2026-11-23 09:35\"")
    ap.add_argument("--write", nargs="?", const="trader/orders.json", metavar="PATH",
                    help="write the proposed order (default trader/orders.json)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of the report")
    g = ap.add_argument_group("weights mode (split a budget across a list)")
    g.add_argument("--weights", help="inline weights: BBCA=40,BBRI=30,TLKM=30")
    g.add_argument("--targets", help="a weights file: {\"weights\": [{\"ticker\", \"weight\"}]}")
    g.add_argument("--top", type=int, help="keep only the N biggest weights")
    g.add_argument("--whole-shares", action="store_true", help="whole shares only (needs --prices)")
    g.add_argument("--cents", action="store_true", help="keep fractional currency amounts instead of rounding to whole units")
    a = ap.parse_args(argv)
    try:
        raw_cfg = read_json(a.config, "config") if (a.config and os.path.exists(a.config)) else {}
        p = market.from_config(raw_cfg)
        cfg, cfg_notices = market.merge_config(raw_cfg, DEFAULTS, p=p)
        if a.weights or a.targets:
            return run_weights(a, cfg, cfg_notices)
        if a.top or a.whole_shares or a.cents:
            raise SizeError("--top, --whole-shares and --cents work with --weights or --targets")
        return run_plan(a, cfg, cfg_notices)
    except (SizeError, ValueError) as e:
        print("size.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
