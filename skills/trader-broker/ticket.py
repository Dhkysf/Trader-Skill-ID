#!/usr/bin/env python3
"""Order tickets and the decision log for trader-broker. Standard library only.

This tool never talks to a broker and never places anything. It does its
work around the one moment that matters, your yes:

  show      renders each proposed order as a plain manual ticket.
            An order is READY only if trader-risk passed THIS
            exact order today (matched by fingerprint) and nobody has decided
            on it yet.
  approve   records your explicit yes for ONE order, with your reply word for
            word. It refuses "yes to all", "sure", "ok", a yes that names a
            different stock or amount, and any order that is not READY.
  decline   records a no.
  result    records what happened after you entered it in your broker app:
            placed (with the broker's order id), denied, or failed.
  fill      records a fill in trader/portfolio.json (cash and shares).
  flatten   builds a sell ticket that closes a symbol's open position by
            flat_by. It still goes through trader-risk and your yes.
  log       prints today's decisions.

    python ticket.py show                     # every order, READY or not
    python ticket.py show --index 1 --json    # one ticket as JSON
    python ticket.py approve --index 1 --reply "yes"
    python ticket.py result --index 1 --status placed --broker-id 61e6...
    python ticket.py fill --symbol BBCA --side buy --qty 300 --price 9875
    python ticket.py flatten --symbol BBCA --qty 300
    python ticket.py log

Everything is written to trader/state/broker.json (append only). Dates are
WIB dates; --now "2026-11-23 09:35" pins the clock.
"""

import argparse
import datetime
from decimal import Decimal, ROUND_HALF_UP
import json
import os
import re
import sys

_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market  # noqa: E402

_IDX = market.load("idx")

ORDER_FIELDS = market.ORDER_FIELDS
TIF_WORDS = {"day": "good for today", "gtc": "good until canceled", "opg": "at the open",
             "cls": "at the close", "ioc": "immediate or cancel", "fok": "fill or kill"}
YES_WORDS = ("yes", "y")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later",
               "hold", "unless", "if"}
UPPER_ALLOW = {"SELL", "LOTS", "GOOD", "FINE", "THIS", "THAT", "ONLY", "JUST", "DONE", "PASS",
               "PLAN", "CASH", "LIVE", "REAL"}
ORDINARY_LOWER = {"beli", "jual", "gas", "please", "lot", "lots", "buy", "sell", "yes", "siap"}


class TicketError(Exception):
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
        raise TicketError("--now wants a time like \"2026-11-23 09:35\" (WIB) or ...Z (UTC)")
    if dt.tzinfo is None:
        return market.local_to_utc(p or _IDX, dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def local_iso(now_utc, p=None):
    """naive UTC -> "2026-11-23T09:35:00+07:00" (market wall clock with its offset)."""
    p = p or _IDX
    off = market.utc_offset(p, now_utc)
    return "%s%+03d:00" % (market.to_local(p, now_utc).replace(microsecond=0).isoformat(), off)


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise TicketError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise TicketError("%s is not valid JSON: %s" % (path, e))


def write_json(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def rec_day(rec):
    """The trading day a decision belongs to: its "date" (the day it was made under), else the day of "at"."""
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


# ---------------------------------------------------------------- the order

fingerprint = market.order_fingerprint


def _str_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        return str(int(f)) if f == int(f) else repr(f)
    return str(v)


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _money(v, p=None):
    return market.money(p or _IDX, v)


def _px(v, p=None):
    return market.price(p or _IDX, v)


def is_bracket(order):
    oc = str(order.get("order_class") or "").lower()
    legs = order.get("take_profit_limit_price") is not None or order.get("stop_loss_stop_price") is not None
    return oc == "bracket" or (not oc and legs)


def max_loss(order, p=None, cfg=None, rv=None):
    """(amount, stop) lost if the stop fills exactly at the stop, or (None, stop)."""
    out_dec = max(2, market.price_decimals(p))
    stop = _f(order.get("stop_loss_stop_price")) or _f((order.get("plan") or {}).get("stop"))
    if rv and _f(rv.get("max_loss")) is not None:
        return round(_f(rv["max_loss"]), out_dec), _f(rv.get("stop")) or stop
    q = _f(order.get("qty"))
    if not stop or not q:
        return None, stop
    plan = order.get("plan") or {}
    buy_pct, sell_pct = market.fees(p, cfg) if p else (0.0, 0.0)
    has_fees = buy_pct > 0 or sell_pct > 0
    if str(order.get("type", "market")) == "limit" and _f(order.get("limit_price")):
        entry = _f(order["limit_price"])
    elif _f(plan.get("max_loss")) is not None:
        return round(_f(plan["max_loss"]), out_dec), stop
    else:
        entry = _f(plan.get("entry"))
    if not entry:
        return None, stop
    d_e, d_s, d_q = market._to_decimal(entry), market._to_decimal(stop), market._to_decimal(q)
    d_rps = abs(d_e - d_s)
    if has_fees:
        is_sell = str(order.get("side") or "buy").lower() == "sell"
        e_pct, s_pct = (sell_pct, buy_pct) if is_sell else (buy_pct, sell_pct)
        d_rps += (d_e * market._to_decimal(e_pct) / Decimal("100")
                  + d_s * market._to_decimal(s_pct) / Decimal("100"))
    step = Decimal("10") ** -out_dec
    return float((d_rps * d_q).quantize(step, rounding=ROUND_HALF_UP)), stop


def plain_parts(order, p=None, cfg=None, rv=None):
    """The ticket in plain words, one part per line."""
    prof = p or _IDX
    side = str(order.get("side", "")).upper()
    sym = market.base_symbol(prof, order.get("symbol")) or "?"
    typ = str(order.get("type", "market"))
    lot = int(prof.get("lot", 1))
    q = _f(order.get("qty"))
    if lot > 1 and q is not None and abs(q - round(q)) < 1e-9 and int(round(q)) % lot == 0:
        lots = int(round(q)) // lot
        qty_s = "%d lot%s (%d shares)" % (lots, "" if lots == 1 else "s", int(round(q)))
    else:
        qty_s = "%s shares" % _str_num(order.get("qty"))
    plan = order.get("plan") or {}
    entry = _f(order.get("limit_price")) if typ == "limit" else _f(plan.get("entry"))
    entry_s = ("at %s" % _px(entry, prof)) if entry else "at market"
    bits = ["%s %s %s %s" % (side, qty_s, sym, entry_s)]
    stop = _f(order.get("stop_loss_stop_price")) or _f(plan.get("stop"))
    target = _f(order.get("take_profit_limit_price")) or _f(plan.get("target"))
    if stop:
        bits.append("stop %s" % _px(stop, prof))
    if target:
        bits.append("target %s" % _px(target, prof))
    loss, _ = max_loss(order, p=prof, cfg=cfg, rv=rv)
    if loss is not None:
        bits.append("max loss incl. fees %s" % _money(loss, prof))
    return ["%s. Enter it in your broker app yourself." % ", ".join(bits)]


def plain(order, p=None, cfg=None, rv=None):
    return " / ".join(plain_parts(order, p=p, cfg=cfg, rv=rv))


def amount_numbers(order, p=None, cfg=None, rv=None):
    nums = []
    for k in ("notional", "qty", "limit_price", "stop_loss_stop_price", "take_profit_limit_price",
              "stop_loss_limit_price"):
        if order.get(k) is not None:
            v = _f(order[k])
            if v is not None:
                nums.append(v)
    plan = order.get("plan") or {}
    for k in ("entry", "stop", "target"):
        v = _f(plan.get(k))
        if v is not None:
            nums.append(v)
    lot = int((p or _IDX).get("lot", 1))
    q = _f(order.get("qty"))
    if q is not None and lot > 1:
        nums.append(q / lot)
    loss, _ = max_loss(order, p=p, cfg=cfg, rv=rv)
    if loss is not None:
        nums.append(loss)
        nums.append(float(round(loss)))
    return nums


def _universe_symbols(path, prof):
    if not path or not os.path.isfile(path):
        return set()
    syms = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            code = s.split("|", 1)[0].split(",", 1)[0].strip()
            if code:
                syms.add(market.base_symbol(prof, code))
    return syms


def parse_yes(reply, order, batch_symbols=(), p=None, cfg=None, universe_path="trader/universe.txt", rv=None):
    """Is this reply an explicit yes for THIS one order? Returns (ok, why)."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    if "?" in raw:
        return False, "the reply is a question, not a yes"
    words = re.findall(r"[a-z']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "only a reply that starts with \"yes\" counts (not ok, sure, go, do it)"
    if BATCH_WORDS & set(words):
        return False, "a yes covers one order at a time, not a batch"
    if DOUBT_WORDS & set(words[1:]):
        return False, "the reply has a condition or a doubt in it; ask again"
    prof = p or _IDX
    sym = market.base_symbol(prof, order.get("symbol"))
    upper4 = {market.base_symbol(prof, tok) for tok in re.findall(r"\b[A-Z]{4}(?:\.[A-Z]{2})?\b", raw)} - {sym} - UPPER_ALLOW
    others = ({market.base_symbol(prof, s) for s in batch_symbols if s} | _universe_symbols(universe_path, prof)) - {sym}
    tokens = {market.base_symbol(prof, tok)
              for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9.\-]{0,8}\b", raw)
              if tok.isupper() or tok.lower() not in ORDINARY_LOWER}
    named = (tokens & others) | upper4
    if named:
        return False, "the reply names %s, but this order is for %s" % (", ".join(sorted(named)), sym)
    if market.price_decimals(prof) == 0:
        nums = [float(n.replace(".", "").replace(",", "")) if re.match(r"^\d{1,3}(?:\.\d{3})+$", n)
                else float(n.replace(",", ""))
                for n in re.findall(r"\d{1,3}(?:\.\d{3})+|\d[\d,]*(?:\.\d+)?", raw)]
    else:
        nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if nums:
        want = amount_numbers(order, p=p, cfg=cfg, rv=rv)
        tol = float(market.price_tol(prof))
        bad = [n for n in nums if not any(abs(n - w) < tol for w in want)]
        if bad:
            return False, "the reply says %s, which does not match this order (%s)" % (
                ", ".join(_str_num(n) for n in bad), plain(order, p=p, cfg=cfg, rv=rv))
    return True, "explicit yes for %s" % plain(order, p=p, cfg=cfg, rv=rv)


# ---------------------------------------------------------------- state

def load_state(path):
    return read_json(path, "broker state", required=False) or {"orders": []}


def latest(state, fp, today):
    """The latest decision recorded today for this fingerprint, or None."""
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and rec_day(rec) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "trader-risk has not checked these orders (run check.py)"
    if risk.get("date") != today:
        return None, "the risk check is from %s, not today; run check.py again" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, "this exact order was not in the last risk check (it changed or is new); run check.py again"


def status_of(order, risk, state, today):
    """(ready, label, risk_result)"""
    fp = fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NOT READY: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "BLOCKED by trader-risk: " + "; ".join(rv.get("reasons", [])), rv
    rec = latest(state, fp, today)
    if rec:
        st = rec.get("status")
        if st == "approved":
            return False, "APPROVED by you at %s, waiting for manual entry and result" % rec.get("at"), rv
        return False, "DONE: %s at %s" % (st, rec.get("at")), rv
    return True, "READY: trader-risk PASS, waiting for your yes", rv


def kind_of(order, rv):
    """entry or exit, as trader-risk saw it (older checks: a buy is an entry)."""
    if rv and rv.get("kind"):
        return rv["kind"]
    return "entry" if str(order.get("side", "")).lower() == "buy" else "exit"


# ---------------------------------------------------------------- rendering

def render(order, idx, total, cfg, risk, state, today):
    p = market.from_config(cfg)
    ready, label, rv = status_of(order, risk, state, today)
    paper = cfg.get("paper", True)
    acct = "PAPER account" if paper else "LIVE ACCOUNT, REAL MONEY"
    where = "manual (%s)" % market.display_name(p)
    lines = ["ORDER %d of %d, %s, %s" % (idx, total, acct, where)]
    for part in plain_parts(order, p=p, cfg=cfg, rv=rv):
        lines.append("  " + part)
    if order.get("why"):
        lines.append("  why: " + order["why"])
    lines.append("  " + label)
    for w in (rv or {}).get("warnings", []):
        lines.append("  note: " + w)
    lines.append("  %s orders are manual: no broker API or MCP tool is called." % market.display_name(p))
    if ready:
        lines.append("  Reply \"yes\" to confirm this one order, or \"no\" to skip it.")
    return "\n".join(lines), ready


def ticket_json(order, idx, cfg, risk, state, today):
    p = market.from_config(cfg)
    ready, label, rv = status_of(order, risk, state, today)
    loss, stop = max_loss(order, p=p, cfg=cfg, rv=rv)
    return {"index": idx, "ready": ready, "status": label, "plain": plain(order, p=p, cfg=cfg, rv=rv),
            "fingerprint": fingerprint(order), "paper": bool(cfg.get("paper", True)),
            "broker": "manual", "manual": True, "market": p.get("id", "idx"),
            "why": order.get("why", ""), "max_loss": loss, "stop": stop}


# ---------------------------------------------------------------- fills -> portfolio

def apply_fill(portfolio_path, cfg, symbol, side, qty, price, date, p=None, fee=None):
    """Record a filled order in trader/portfolio.json: cash and shares, with a
    cost-basis lot per buy (fees from market.fees, config wins; buy fee goes into lot cost)."""
    pf = read_json(portfolio_path, "portfolio", required=False)
    if pf is None:
        budget = cfg.get("budget")
        if not budget:
            raise TicketError("no %s yet and no budget in the config to start it from" % portfolio_path)
        pf = {"cash": float(budget), "positions": []}
    prof = p or market.from_config(cfg)
    symbol = market.base_symbol(prof, symbol)
    qty, price = float(qty), float(price)
    if qty <= 0 or price <= 0:
        raise TicketError("a fill needs a positive qty and price")
    if fee is None:
        pct = market.fees(p, cfg)[0 if side == "buy" else 1]
        step = Decimal("1") if (p or {}).get("currency") == "IDR" else Decimal("0.01")
        fee = float((market._to_decimal(qty) * market._to_decimal(price) * market._to_decimal(pct) / 100)
                    .quantize(step, rounding=ROUND_HALF_UP))
    elif fee < 0:
        raise TicketError("--fee wants the broker's fee, 0 or more")
    cost = round(qty * price, 2)
    pos = None
    for pr in pf.setdefault("positions", []):
        if market.base_symbol(prof, pr.get("ticker") or pr.get("symbol")) == symbol:
            pos = pr
    if side == "buy":
        if pos is None:
            pos = {"ticker": symbol, "shares": 0.0, "lots": []}
            pf["positions"].append(pos)
        else:
            pos["ticker"] = symbol
        lots = pos.setdefault("lots", [])
        lots.append({"id": "%s-%d" % (symbol, len(lots) + 1), "date": date, "shares": qty, "cost": round(cost + fee, 2)})
        pos["shares"] = round(float(pos.get("shares", 0)) + qty, 6)
        pf["cash"] = round(float(pf.get("cash", 0)) - cost - fee, 2)
    else:
        if pos is None or float(pos.get("shares", 0)) + 1e-9 < qty:
            raise TicketError("cannot record selling %s %s: the portfolio holds %s"
                              % (_str_num(qty), symbol, pos.get("shares", 0) if pos else 0))
        left = qty
        for lot in sorted(pos.get("lots", []), key=lambda l: l.get("date", "")):
            if left <= 1e-9:
                break
            take = min(left, float(lot["shares"]))
            per = float(lot["cost"]) / float(lot["shares"]) if float(lot["shares"]) else 0
            lot["cost"] = round(float(lot["cost"]) - per * take, 2)
            lot["shares"] = round(float(lot["shares"]) - take, 6)
            left -= take
        pos["lots"] = [l for l in pos.get("lots", []) if float(l["shares"]) > 1e-9]
        pos["shares"] = round(float(pos["shares"]) - qty, 6)
        if pos["shares"] <= 1e-9:
            pf["positions"].remove(pos)
        pf["cash"] = round(float(pf.get("cash", 0)) + cost - fee, 2)
    write_json(portfolio_path, pf)
    return pf, fee


def log_fill(state_path, now, today, symbol, side, qty, price, p=None, fee=None):
    """A fill in the log."""
    state = load_state(state_path)
    prof = p or _IDX
    sym = market.base_symbol(prof, symbol)
    px_s = _px(price, prof)
    entry = {
        "at": local_iso(now, p=p), "date": today, "status": "filled", "symbol": sym, "side": side,
        "qty": _str_num(float(qty)), "price": float(price),
        "plain": "%s %s %s at %s" % (side.upper(), _str_num(float(qty)), sym, px_s)}
    if fee is not None:
        entry["fee"] = fee
    state.setdefault("orders", []).append(entry)
    write_json(state_path, state)


# ---------------------------------------------------------------- commands

def _clock(a, p=None):
    p = p or _IDX
    now = parse_now(getattr(a, "now", None), p=p)
    today = getattr(a, "today", None) or market.to_local(p, now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", today):
        raise TicketError("--today wants a date like 2026-11-23")
    return now, today


def _load(a):
    doc = read_json(a.orders, "orders file (run trader-budget, or ticket.py flatten, first)")
    orders = doc.get("orders", doc) if isinstance(doc, dict) else doc
    if not isinstance(orders, list) or not orders:
        raise TicketError("no orders in %s" % a.orders)
    cfg = read_json(a.config, "config", required=False) or {}
    p = market.from_config(cfg)
    risk = read_json(a.risk, "risk check", required=False)
    state = load_state(a.state)
    now, today = _clock(a, p=p)
    return orders, cfg, risk, state, today, now


def _pick(orders, index):
    if index is None:
        raise TicketError("say which order: --index N")
    if not 1 <= index <= len(orders):
        raise TicketError("there is no order %d (there are %d)" % (index, len(orders)))
    return orders[index - 1]


def cmd_show(a):
    orders, cfg, risk, state, today, now = _load(a)
    picks = [(a.index, _pick(orders, a.index))] if a.index else list(enumerate(orders, 1))
    if a.json:
        out = [ticket_json(o, i, cfg, risk, state, today) for i, o in picks]
        print(json.dumps(out[0] if a.index else out, indent=2))
        return 0 if any(t["ready"] for t in out) else 1
    blocks, any_ready = [], False
    for i, o in picks:
        text, ready = render(o, i, len(orders), cfg, risk, state, today)
        blocks.append(text)
        any_ready = any_ready or ready
    print("\n\n".join(blocks))
    print("\nOne order at a time: a yes covers one ticket, never the batch. Education and tooling, "
          "not financial advice.")
    return 0 if any_ready else 1


def cmd_approve(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    p = market.from_config(cfg)
    ready, label, rv = status_of(order, risk, state, today)
    if not ready:
        raise TicketError("order %d is not ready: %s" % (a.index, label))
    ok, why = parse_yes(a.reply, order, [o.get("symbol", "") for o in orders], p=p, cfg=cfg,
                        universe_path=os.path.join(os.path.dirname(a.orders) or "trader", "universe.txt"), rv=rv)
    if not ok:
        print("Not recorded: %s. Ask the user again with the ticket for order %d." % (why, a.index))
        return 1
    loss, stop = max_loss(order, p=p, cfg=cfg, rv=rv)
    plain_s = plain(order, p=p, cfg=cfg, rv=rv)
    rec = {"at": local_iso(now, p=p), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": market.base_symbol(p, order.get("symbol")), "side": order.get("side"),
           "qty": order.get("qty"), "kind": kind_of(order, rv), "max_loss": loss, "stop": stop,
           "plain": plain_s, "status": "approved", "reply": a.reply,
           "paper": bool(cfg.get("paper", True)), "broker": "manual"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded your yes for order %d: %s" % (a.index, plain_s))
    print("Enter this order in your broker app yourself, then record the outcome: "
          "ticket.py result --index %d --status placed|denied|failed" % a.index)
    return 0


def cmd_decline(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    p = market.from_config(cfg)
    rv, _ = risk_verdict(risk, fingerprint(order), today)
    plain_s = plain(order, p=p, cfg=cfg, rv=rv)
    rec = {"at": local_iso(now, p=p), "date": today, "index": a.index, "fingerprint": fingerprint(order),
           "symbol": market.base_symbol(p, order.get("symbol")), "side": order.get("side"),
           "plain": plain_s, "status": "declined", "reply": a.reply or "no"}
    state.setdefault("orders", []).append(rec)
    write_json(a.state, state)
    print("Recorded: you said no to order %d (%s). Nothing was sent." % (a.index, plain_s))
    return 0


def cmd_result(a):
    orders, cfg, risk, state, today, now = _load(a)
    order = _pick(orders, a.index)
    fp = fingerprint(order)
    rec = latest(state, fp, today)
    if not rec or rec.get("status") != "approved":
        raise TicketError("order %d has no yes recorded today; a result can only follow an approval" % a.index)
    p = market.from_config(cfg)
    sym = market.base_symbol(p, rec.get("symbol"))
    new = {"at": local_iso(now, p=p), "date": today, "index": a.index, "fingerprint": fp, "symbol": sym,
           "side": rec["side"], "plain": rec["plain"], "status": a.status}
    for k in ("qty", "kind", "max_loss", "stop"):
        if rec.get(k) is not None:
            new[k] = rec[k]
    if a.broker_id:
        new["broker_order_id"] = a.broker_id
    if a.note:
        new["note"] = a.note
    state["orders"].append(new)
    write_json(a.state, state)
    print("Recorded order %d as %s." % (a.index, a.status))
    if a.status == "placed" and a.filled_qty and a.filled_price:
        _, fee = apply_fill(a.portfolio, cfg, sym, rec["side"], a.filled_qty, a.filled_price, today, p, a.fee)
        shown = fee if (fee or a.fee is not None) else None
        log_fill(a.state, now, today, sym, rec["side"], a.filled_qty, a.filled_price, p=p, fee=shown)
        print("Added the fill to %s%s." % (a.portfolio, (" (fee %s)" % _money(fee, p)) if shown is not None else ""))
    elif a.status == "placed":
        print("When it fills, record it: ticket.py fill --symbol %s --side %s --qty Q --price P"
              % (sym, rec["side"]))
        if rec.get("kind") == "entry" and is_bracket(order):
            print("When the stop-loss or the take-profit fills later, record that sell the same way.")
    return 0


def cmd_fill(a):
    cfg = read_json(a.config, "config", required=False) or {}
    p = market.from_config(cfg)
    now = parse_now(a.now, p=p)
    date = a.date or market.to_local(p, now).date().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise TicketError("--date wants a date like 2026-10-19")
    sym = market.base_symbol(p, a.symbol)
    pf, fee = apply_fill(a.portfolio, cfg, sym, a.side, a.qty, a.price, date, p, a.fee)
    shown = fee if (fee or a.fee is not None) else None
    log_fill(a.state, now, date, sym, a.side, a.qty, a.price, p=p, fee=shown)
    fee_s = (", fee %s" % _money(fee, p)) if shown is not None else ""
    print("Recorded %s %s %s at %s on %s in %s%s. Cash now %s." % (a.side, a.qty, sym,
                                                                  _money(a.price, p), date, a.portfolio,
                                                                  fee_s, _money(pf["cash"], p)))
    return 0


def cmd_flatten(a):
    cfg = read_json(a.config, "config", required=False) or {}
    p = market.from_config(cfg)
    sym = market.base_symbol(p, a.symbol)
    now, today = _clock(a, p=p)
    source = "your broker app"
    if a.qty is not None:
        qty = _f(a.qty)
        if qty is None or qty <= 0:
            raise TicketError("--qty wants the number of shares you hold, like --qty 300")
    else:
        pf = read_json(a.portfolio, "portfolio", required=False) or {}
        qty = sum(_f(pos.get("shares", pos.get("qty"))) or 0 for pos in pf.get("positions", [])
                  if market.base_symbol(p, pos.get("ticker") or pos.get("symbol")) == sym)
        source = a.portfolio
        if qty <= 1e-9:
            raise TicketError("nothing to flatten: no %s shares in %s. Check your broker app "
                              "and pass --qty if you do hold some" % (sym, a.portfolio))
    plan = read_json(a.plan, "plan", required=False) or {}
    tz = p.get("tz_label") or p.get("timezone") or "WIB"
    default_flat = (p.get("defaults") or {}).get("flat_by") or "15:45"
    flat_by = (plan.get("flat_by") if market.base_symbol(p, plan.get("symbol")) == sym else None) \
        or cfg.get("flat_by") or default_flat
    order = {"symbol": sym, "side": "sell", "qty": _str_num(qty), "type": "market", "time_in_force": "day",
             "market": p["id"],
             "why": "flat by %s %s: closes the %s day trade before the close (qty from %s)"
             % (flat_by, tz, sym, source)}
    old = read_json(a.orders, "orders", required=False)
    replaced = len(old.get("orders", [])) if isinstance(old, dict) else 0
    doc = {"created_by": "trader-broker", "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "proposed",
           "paper": bool(cfg.get("paper", True)),
           "note": "Flatten ticket. Nothing is placed until trader-risk passes it and you say yes in the chat.",
           "source": "ticket.py flatten %s on %s" % (sym, today), "orders": [order]}
    write_json(a.orders, doc)
    print("Flatten %s: %s (flat by %s %s)." % (sym, plain(order, p=p, cfg=cfg), flat_by, tz))
    print("Wrote it to %s%s." % (a.orders, (" (it replaced %d earlier proposal%s)"
                                             % (replaced, "" if replaced == 1 else "s")) if replaced else ""))
    print("Next:")
    print("  1. trader-risk: check.py. A sell that only closes what you hold is never blocked by the daily")
    print("     limits or the entry window.")
    print("  2. ticket.py show, then the user's yes for this one order.")
    print("  3. Enter the sell in your broker app yourself, then record the fill with ticket.py result/fill.")
    return 0


def cmd_log(a):
    cfg = read_json(a.config, "config", required=False) or {}
    p = market.from_config(cfg)
    state = load_state(a.state)
    now, today = _clock(a, p=p)
    rows = [r for r in state.get("orders", []) if a.all or rec_day(r) == today]
    if not rows:
        print("No decisions recorded%s." % ("" if a.all else " today"))
        return 1
    for r in rows:
        extra = (" id " + r["broker_order_id"]) if r.get("broker_order_id") else ""
        reply = (' reply "%s"' % r["reply"]) if r.get("reply") and r["status"] in ("approved", "declined") else ""
        loss = (" max loss %s" % _money(r["max_loss"], p)) if r.get("max_loss") is not None and r["status"] == "placed" else ""
        idx = ("#%s" % r["index"]) if r.get("index") is not None else "  "
        print("%s  %s %-9s %s%s%s%s" % (r.get("at"), idx, r.get("status"), r.get("plain"), reply, loss, extra))
    placed = sum(1 for r in rows if r.get("status") == "placed")
    print("%d placed%s." % (placed, "" if a.all else " today"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Order tickets and your yes (trader-broker). Never places orders.")
    sub = ap.add_subparsers(dest="cmd")

    def clock(p):
        p.add_argument("--now", help="pretend it is this WIB time, e.g. \"2026-11-23 09:35\"")
        p.add_argument("--today", help="YYYY-MM-DD (default: today in WIB)")

    def common(p):
        p.add_argument("--orders", default="trader/orders.json")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--risk", default="trader/state/risk.json")
        p.add_argument("--state", default="trader/state/broker.json")
        clock(p)

    p = sub.add_parser("show", help="render the tickets")
    common(p)
    p.add_argument("--index", type=int)
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve", help="record the user's explicit yes for one order")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply", required=True, help="the user's reply, word for word")
    p = sub.add_parser("decline", help="record a no")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--reply")
    p = sub.add_parser("result", help="record the outcome after entering the order in your broker app")
    common(p)
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--status", required=True, choices=["placed", "denied", "failed"])
    p.add_argument("--broker-id")
    p.add_argument("--note")
    p.add_argument("--filled-qty")
    p.add_argument("--filled-price")
    p.add_argument("--fee", type=float, help="the real fee from your broker app (default: from the market's fees)")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p = sub.add_parser("fill", help="record a fill in trader/portfolio.json")
    p.add_argument("--symbol", required=True)
    p.add_argument("--side", required=True, choices=["buy", "sell"])
    p.add_argument("--qty", required=True)
    p.add_argument("--price", required=True)
    p.add_argument("--fee", type=float, help="the real fee from your broker app (default: from the market's fees)")
    p.add_argument("--date", help="YYYY-MM-DD (default: today in WIB)")
    p.add_argument("--now")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--state", default="trader/state/broker.json")
    p = sub.add_parser("flatten", help="a sell ticket that closes a symbol's position by flat_by")
    p.add_argument("--symbol", required=True)
    p.add_argument("--qty", help="shares you hold (default: trader/portfolio.json)")
    p.add_argument("--orders", default="trader/orders.json", help="where the ticket is written")
    p.add_argument("--portfolio", default="trader/portfolio.json")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p = sub.add_parser("log", help="today's decisions")
    p.add_argument("--state", default="trader/state/broker.json")
    p.add_argument("--config", default="trader/config.json")
    clock(p)
    p.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"show": cmd_show, "approve": cmd_approve, "decline": cmd_decline, "result": cmd_result,
                "fill": cmd_fill, "flatten": cmd_flatten, "log": cmd_log}[a.cmd](a)
    except (TicketError, ValueError) as e:
        print("ticket.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
