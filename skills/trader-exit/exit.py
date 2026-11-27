#!/usr/bin/env python3
"""Exit Planner for trader-exit: sets the stop and the target BEFORE you
enter, so you know when to get out. Standard library only. Long side only.
It never places an order.

    python exit.py plan                                     # from trader/entry.json: or-mid stop, 2R target
    python exit.py plan --stop or-mid --target 1R --write
    python exit.py plan --symbol BBCA --entry 9875 --or-high 9850 --or-low 9700
    python exit.py plan --stop atr:1.5 --offline BBCA.JK.json.gz  # ATR needs the session's bars
    python exit.py plan --symbol BBRI --entry 4100 --setup level --stop pct:1
    python exit.py show                                     # the current trader/plan.json

Stops (a long's stop rounds DOWN to the IDX tick, away from the entry):
  or-mid     the opening-range midpoint (the default for an orb entry)
  or-low     the opening-range low
  price:X    your price
  pct:X      X percent under the entry
  atr:K      K times the 14-bar ATR under the entry, on the session's bars up
             to the entry bar (--offline FILE or Yahoo). With fewer than 14
             bars by then it averages all of them and says so.
  A level setup has no opening-range default: give a stop.

Targets (round down to the IDX tick):
  2R (default), 1R, 1.5R ...   entry + R x risk, where risk = entry - stop
  price:X                      your price

Refused, with the reason: a stop at or above the entry, a target at or below
it, a risk under 2 ticks or 0.05% of the price, an entry.json that has not
triggered (unless you give --entry), or a short (v2 plans longs only).

flat_by (default 15:45 WIB, or "flat_by" in trader/config.json): out by then,
win or lose. "min_reward_risk" in the config (default 1.0) only warns here;
trader-risk enforces it.

A stop is a plan, not a guarantee: a gap or a fast market can fill past it.
Exit codes: plan 0 = a plan, 1 = refused or an error. show 0 = a plan exists.
"""

import argparse
import datetime
import gzip
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP

_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market  # noqa: E402

UA = "Mozilla/5.0 (compatible; trader-skill-id/0.1; +https://github.com/Dhkysf/Trader-Skill-ID)"
BACKOFF = 5.0
HOSTS = ("query2", "query1")
INTERVALS = {"1m": 60, "5m": 300}
DEFAULTS = {"flat_by": "15:45", "min_reward_risk": 1.0}
ATR_BARS = 14
MIN_RISK_PCT = Decimal("0.05")     # risk under 0.05% of the price is inside the spread's noise
CENT = Decimal("0.01")
EPOCH = datetime.datetime(1970, 1, 1)
NOTE = "A stop is a plan, not a guarantee: a gap or a fast market can fill past it."

_IDX = market.load("idx")


class PlanError(Exception):
    pass


# ---------------------------------------------------------------- time

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def _tz_label(p):
    prof = p or _IDX
    return prof.get("tz_label") or prof.get("timezone") or "WIB"


def _place_label(p):
    return _tz_label(p)


def _money(x, p=None, symbol=None):
    return market.price(p or _IDX, float(x), symbol=symbol)


def _raw_money(x, p=None, symbol=None):
    return "%s %s" % (market.quote_currency(p or _IDX, symbol=symbol), num(x))


def parse_now(text, p=None):
    """--now -> naive UTC. A time without an offset is market local time."""
    if not text:
        return utc_now()
    prof = p or _IDX
    t = text.strip()
    tz_suf = " " + _tz_label(prof).upper()
    if t.upper().endswith(tz_suf):
        t = t[:-len(tz_suf)].strip()
    if re.match(r"^\d{1,2}:\d{2}$", t):
        t = "%s %s" % (market.to_local(prof, utc_now()).date().isoformat(), t.zfill(5))
    t = t.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise PlanError('--now wants a %s time like "2026-11-23 09:35" (or ...Z for UTC)' % _place_label(prof))
    if dt.tzinfo is None:
        return market.local_to_utc(prof, dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_hhmm(text, what, p=None):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise PlanError("%s wants a %s time like 15:45, not %r" % (what, _place_label(p), text))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def parse_clock(text, what):
    """10:15 AM, 10:15, 3:05 PM -> time."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])?\s*$", str(text))
    if not m:
        raise PlanError("%s wants a time like 10:15 AM, not %r" % (what, text))
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        if not 1 <= h <= 12:
            raise PlanError("%s wants a time like 10:15 AM, not %r" % (what, text))
        h = h % 12 + (12 if m.group(3).upper() == "PM" else 0)
    if h > 23 or mi > 59:
        raise PlanError("%s wants a time like 10:15 AM, not %r" % (what, text))
    return datetime.time(h, mi)


def hm(t):
    return "%02d:%02d" % (t.hour, t.minute)


def ampm(t):
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


# ---------------------------------------------------------------- money math (Decimal)

def D(x, what="a number"):
    try:
        if isinstance(x, float):
            return Decimal(repr(x))
        s = re.sub(r"^(?:\$|idr\s*|rp\.?\s*)", "", str(x).strip(), flags=re.IGNORECASE).replace(",", "")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        raise PlanError("%s is not a number: %r" % (what, x))


def num(x):
    """1, 1.5, 2.25: a Decimal without trailing zeros."""
    s = format(D(x).normalize(), "f")
    return s


def ratio(x):
    """reward:risk for people: 1.0, 1.5, 1.37."""
    s = "%.2f" % float(x)
    return s[:-1] if s.endswith("0") else s


WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def parse_stop(text):
    t = str(text).strip().lower()
    if t in ("or-mid", "or_mid", "mid", "or-midpoint"):
        return "or_mid", None
    if t in ("or-low", "or_low", "low"):
        return "or_low", None
    if t in ("or-high", "or_high", "high"):
        return "or_high", None
    m = re.match(r"^(price|pct|atr):\s*(?:\$|idr\s*|rp\.?\s*)?([0-9][0-9,]*\.?[0-9]*)$", t)
    if not m:
        raise PlanError("--stop is or-mid, or-low, price:X, pct:X or atr:K (got %r)" % text)
    kind, val = m.group(1), D(m.group(2), "--stop")
    if val <= 0:
        raise PlanError("--stop %s needs a number above 0" % kind)
    if kind == "pct" and val >= 100:
        raise PlanError("--stop pct:X needs X under 100")
    return kind, val


def parse_target(text):
    t = str(text).strip()
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*[Rr]$", t)
    if m:
        r = D(m.group(1), "--target")
        if r <= 0:
            raise PlanError("--target needs an R multiple above 0, like 1R or 2R")
        return "r", r
    m = re.match(r"^price:\s*(?:\$|idr\s*|rp\.?\s*)?([0-9][0-9,]*\.?[0-9]*)$", t.lower())
    if m:
        return "price", D(m.group(1), "--target")
    raise PlanError("--target is 2R, 1R, 1.5R ... or price:X (got %r)" % text)


def r_label(r):
    n = int(r) if r == r.to_integral_value() else None
    return "%sR (%s times the risk)" % (num(r), WORDS.get(n, num(r)))


def _tick_below(p, x):
    """Tick size immediately below `x` (handles IDX tick-table boundaries)."""
    d = market._to_decimal(x)
    table = p.get("tick_table")
    if table:
        for entry in table:
            if entry["below"] is None or d <= Decimal(str(entry["below"])):
                return Decimal(str(entry["tick"]))
    return market.tick_size(p, d)


def compute(entry, stop_rule, stop_param, target_rule, target_param, or_high=None, or_low=None,
            atr=None, atr_bars=None, p=None, side="buy", symbol=None):
    """The stop, the target and the risk, in exact ticks. Raises PlanError with the reason."""
    prof = p or _IDX
    is_short = str(side or "buy").lower() in ("sell", "short")
    e = market.round_tick(prof, D(entry, "entry"), "nearest", symbol=symbol)
    if e <= 0:
        raise PlanError("the entry price must be above %s" % _raw_money(0, prof, symbol=symbol))
    detail = ""
    if stop_rule in ("or_mid", "or_low", "or_high"):
        if or_high is None or or_low is None:
            raise PlanError("an %s stop needs the opening range (--or-high and --or-low)" % stop_rule.replace("_", "-"))
        oh = market.round_tick(prof, D(or_high, "--or-high"), "nearest", symbol=symbol)
        ol = market.round_tick(prof, D(or_low, "--or-low"), "nearest", symbol=symbol)
        if oh <= ol:
            raise PlanError("the opening-range high %s must be above its low %s" % (_money(oh, prof, symbol=symbol), _money(ol, prof, symbol=symbol)))
        if stop_rule == "or_mid":
            raw = (oh + ol) / 2
            label = "opening-range midpoint"
            detail = "(%s + %s) / 2 = %s" % (_money(oh, prof, symbol=symbol), _money(ol, prof, symbol=symbol), _raw_money(raw, prof, symbol=symbol))
        elif stop_rule == "or_high":
            raw, label = oh, "opening-range high"
        else:
            raw, label = ol, "opening-range low"
    elif stop_rule == "price":
        raw, label = stop_param, "your price"
    elif stop_rule == "pct":
        raw = e * (1 + stop_param / 100) if is_short else e * (1 - stop_param / 100)
        label = "%s%% %s the entry" % (num(stop_param), "above" if is_short else "under")
        detail = "%s x (1 %s %s%%) = %s" % (_money(e, prof, symbol=symbol), "+" if is_short else "-", num(stop_param), _raw_money(raw, prof, symbol=symbol))
    elif stop_rule == "atr":
        if atr is None:
            raise PlanError("an atr stop needs the session's bars")
        a = D(round(atr, 6))
        raw = e + stop_param * a if is_short else e - stop_param * a
        label = "%s x ATR(%d) %s the entry" % (num(stop_param), atr_bars, "above" if is_short else "under")
        detail = "ATR %s over the %d bars to the entry%s" % (
            _raw_money(a.quantize(Decimal("0.0001")), prof, symbol=symbol), atr_bars,
            " (fewer than 14 so far)" if atr_bars < ATR_BARS else "")
    else:
        raise PlanError("unknown stop rule %r" % stop_rule)
    round_dir = "up" if is_short else "down"
    stop = market.round_tick(prof, raw, round_dir, symbol=symbol)
    if stop != D(raw):
        detail = (detail + (", rounded %s" % round_dir) if detail else "%s rounded %s" % (_raw_money(raw, prof, symbol=symbol), round_dir))
    if is_short:
        if stop <= e:
            raise PlanError("the stop %s (%s) is at or below the entry %s: a short's stop goes above the entry"
                            % (_money(stop, prof, symbol=symbol), label, _money(e, prof, symbol=symbol)))
        risk = stop - e
    else:
        if stop >= e:
            raise PlanError("the stop %s (%s) is at or above the entry %s: a long's stop goes under the entry"
                            % (_money(stop, prof, symbol=symbol), label, _money(e, prof, symbol=symbol)))
        if stop <= 0:
            raise PlanError("the stop works out to %s: pick a stop above %s" % (_money(stop, prof, symbol=symbol), _raw_money(0, prof, symbol=symbol)))
        risk = e - stop
    t1 = _tick_below(prof, e) if not prof.get("pairs") else market.tick_size(prof, e, symbol=symbol)
    t2 = _tick_below(prof, e - t1) if not prof.get("pairs") else t1
    min_tick_risk = t1 + t2
    if risk < min_tick_risk:
        raise PlanError("the stop is %s %s the entry, less than 2 ticks (%s at %s): too tight. Widen it."
                        % (_money(risk, prof, symbol=symbol), "above" if is_short else "under",
                           _money(min_tick_risk, prof, symbol=symbol), _money(e, prof, symbol=symbol)))
    floor_risk = e * MIN_RISK_PCT / 100
    if risk < floor_risk:
        pdec = market.price_decimals(prof, symbol=symbol) if prof.get("pairs") else market.price_decimals(prof)
        floor_q = Decimal("10") ** -max(2, pdec)
        raise PlanError("the stop is %s %s the entry, less than 0.05%% of the price (%s on %s): too tight to "
                        "survive the spread, normal wiggle would stop you out. Widen it."
                        % (_money(risk, prof, symbol=symbol), "above" if is_short else "under",
                           _money(floor_risk.quantize(floor_q, rounding=ROUND_HALF_UP), prof, symbol=symbol),
                           _money(e, prof, symbol=symbol)))
    if target_rule == "r":
        raw_target = e - target_param * risk if is_short else e + target_param * risk
        target = market.round_tick(prof, raw_target, round_dir, symbol=symbol)
        t_label = r_label(target_param)
    else:
        target = market.round_tick(prof, target_param, round_dir, symbol=symbol)
        t_label = None
    if is_short:
        if target >= e or target <= 0:
            raise PlanError("the target %s is at or above the entry %s (or <= 0): a short's target goes below it"
                            % (_money(target, prof, symbol=symbol), _money(e, prof, symbol=symbol)))
        rr = ((e - target) / risk).quantize(CENT, rounding=ROUND_HALF_UP)
    else:
        if target <= e:
            raise PlanError("the target %s is at or below the entry %s: a long's target goes above it"
                            % (_money(target, prof, symbol=symbol), _money(e, prof, symbol=symbol)))
        rr = ((target - e) / risk).quantize(CENT, rounding=ROUND_HALF_UP)
    if t_label is None:
        t_label = "your price (%sR)" % ratio(rr)
    return {"entry": e, "stop": stop, "stop_label": label, "stop_detail": detail, "target": target,
            "target_r": target_param if target_rule == "r" else rr, "target_label": t_label,
            "risk": risk, "reward_risk": rr}


def ar_warnings(p, stop, target, prev_close, day):
    """Auto-rejection warnings for markets with ARA/ARB limits."""
    if not p or not p.get("auto_rejection") or prev_close is None:
        return []
    pc = D(prev_close, "prev_close")
    if pc <= 0:
        return []
    try:
        arb, ara = market.ar_limits(p, pc, day=day)
    except ValueError as e:
        if "no auto_rejection rule" in str(e):
            day_s = day.isoformat() if hasattr(day, "isoformat") else str(day)
            return ["no ARA/ARB rule for %s in markets/%s.json; band not checked" % (day_s, p["id"])]
        raise
    out = []
    if D(stop) < arb:
        out.append("ARB lock: a stop there may not fill (stop %s is below today's ARB %s from previous close %s)."
                   % (_money(stop, p), _money(arb, p), _money(pc, p)))
    if D(target) > ara:
        out.append("Target %s is above today's ARA %s (from previous close %s): price cannot trade above ARA today."
                   % (_money(target, p), _money(ara, p), _money(pc, p)))
    return out


def _holds_through_lunch(p, day, entry_time, flat_by_t, now_local):
    """Return (break_start, break_end) if the plan holds across a mid-day break, else None."""
    sess = market.sessions(p, day)
    if len(sess) < 2:
        return None
    bs, be = sess[0][1], sess[1][0]
    if entry_time is not None:
        if entry_time < be and flat_by_t > bs:
            return bs, be
        return None
    if day == now_local.date() and now_local.time() >= be:
        return None
    return (bs, be) if flat_by_t > bs else None


# ---------------------------------------------------------------- bars for ATR (same reader as trader-entry)

def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sleep(seconds):
    time.sleep(seconds)


def yahoo_get(path):
    """query2 first, query1 on 429 or 5xx; one retry after a pause on 429."""
    last = "no answer"
    for host in HOSTS:
        url = "https://%s.finance.yahoo.com%s" % (host, path)
        for attempt in (0, 1):
            try:
                return _open_url(url)
            except urllib.error.HTTPError as e:
                code, body = e.code, None
                try:
                    if code == 404:     # Yahoo says why in the body: an unknown ticker
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = None
                finally:
                    e.close()
                if code == 404:
                    if body:
                        return body
                    raise PlanError("Yahoo has no chart at %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise PlanError("Yahoo answered HTTP %d for %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "could not connect: %s" % (e.reason,)
                break
            except OSError as e:
                last = "network error: %s" % (e,)
                break
    raise PlanError("Yahoo did not answer (%s on query2 and query1): wait a minute and try again" % last)


def read_text(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_chart(sym, interval, day, offline=None, p=None):
    prof = p or _IDX
    base = market.base_symbol(prof, sym)
    ysym = market.yahoo_symbol(prof, base)
    if offline:
        path = offline
        if os.path.isdir(offline):
            for name in (base + ".json", base + ".json.gz", ysym + ".json", ysym + ".json.gz"):
                fp = os.path.join(offline, name)
                if os.path.exists(fp):
                    path = fp
                    break
        if not os.path.exists(path):
            raise PlanError("no offline file %s" % path)
        try:
            text = read_text(path)
        except (OSError, ValueError) as e:
            raise PlanError("could not read %s: %s" % (path, e))
    else:
        back = (market.to_local(prof, utc_now()).date() - day).days
        rng = "1d" if back <= 0 else "5d" if back <= 6 else "1mo" if back <= 28 else "60d"
        if interval == "1m" and back > 6:
            raise PlanError("Yahoo keeps 1-minute bars for about a week")
        text = yahoo_get("/v8/finance/chart/%s?range=%s&interval=%s" % (ysym, rng, interval))
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise PlanError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise PlanError("Yahoo has no data for %s: %s" % (sym, err.get("description") or "unknown ticker"))
    r = res[0] or {}
    meta = r.get("meta") or {}
    if market.base_symbol(prof, meta.get("symbol") or ysym) != base:
        raise PlanError("the chart file holds %s, not %s" % (meta.get("symbol"), sym))
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}

    def at(key, i):
        arr = q.get(key) or []
        return arr[i] if i < len(arr) else None

    bars = []
    prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    prior_day, prior_close = None, None
    step = INTERVALS.get(interval, 300)
    for i, t in enumerate(r.get("timestamp") or []):
        c = at("close", i)
        if t is None or c is None:
            continue
        h, lo = at("high", i), at("low", i)
        bars.append({"t": int(t), "h": float(c if h is None else h), "l": float(c if lo is None else lo),
                     "c": float(c)})
        if day and int(t) % step == 0:
            bt = market.to_local(prof, utc_of(int(t)))
            if bt.date() < day and (prior_day is None or bt.date() >= prior_day):
                prior_day = bt.date()
                prior_close = float(c)
    if prior_close is not None:
        prev_close = prior_close
    return {"bars": bars, "data_time": meta.get("regularMarketTime"), "prev_close": prev_close}


def session_bars(chart, day, interval, upto_slot=None, now_utc=None, p=None):
    """Closed, on-grid bars of one session, oldest first (the live tick is dropped)."""
    prof = p or _IDX
    step = INTERVALS[interval]
    sess = market.sessions(prof, day)
    if not sess:
        return []
    windows = [(datetime.datetime.combine(day, o), datetime.datetime.combine(day, c)) for o, c in sess]
    open_dt = windows[0][0]
    if now_utc is None and chart.get("data_time"):
        now_utc = utc_of(chart["data_time"])
    local = market.to_local(prof, now_utc) if now_utc else None
    out = {}
    for b in chart["bars"]:
        if b["t"] % step:
            continue
        et = market.to_local(prof, utc_of(b["t"]))
        if et.date() != day or not any(so <= et < sc for so, sc in windows):
            continue
        if local and et + datetime.timedelta(seconds=step) > local:
            continue
        slot = int((et - open_dt).total_seconds()) // step
        if upto_slot is not None and slot > upto_slot:
            continue
        out[slot] = b
    return [out[k] for k in sorted(out)]


def atr_of(bars, n=ATR_BARS):
    """Average true range of the last n bars (all of them if fewer). The first
    bar of the session uses its own high - low (no overnight gap)."""
    trs, prev = [], None
    for b in bars:
        tr = b["h"] - b["l"]
        if prev is not None:
            tr = max(tr, abs(b["h"] - prev), abs(b["l"] - prev))
        trs.append(tr)
        prev = b["c"]
    use = trs[-n:]
    return sum(use) / len(use), len(use)


# ---------------------------------------------------------------- plan

def read_json(path, what):
    if not path or not os.path.exists(path):
        raise PlanError("no %s at %s" % (what, path))
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise PlanError("%s is not valid JSON: %s" % (path, e))


def read_config(path):
    doc = {}
    if path and os.path.exists(path):
        doc = read_json(path, "config")
    try:
        p = market.from_config(doc)
    except ValueError as e:
        raise PlanError(str(e))
    cfg = dict(DEFAULTS)
    for k, v in (p.get("defaults") or {}).items():
        if k in cfg and v is not None:
            cfg[k] = v
    for k in DEFAULTS:
        if doc.get(k) is not None:
            cfg[k] = doc[k]
    cfg["market"] = p["id"]
    return cfg


def resolve_flat_by(day, explicit, cfg, entry_time, p=None):
    """(HH:MM, note)."""
    prof = p or _IDX
    default_flat = (prof.get("defaults") or {}).get("flat_by") or DEFAULTS["flat_by"]
    t = parse_hhmm(explicit or cfg.get("flat_by") or default_flat, "--flat-by" if explicit else "flat_by", p=prof)
    note = ""
    tw = market.trading_day_window(prof, day) if day else []
    if tw:
        close_dt = tw[-1][1]
        close_t = close_dt.time()
        at = datetime.datetime.combine(day, t)
        std_raw = prof["sessions"].get(market._WEEKDAYS[day.weekday()]) or prof["sessions"].get(market._WEEKDAYS[(day - datetime.timedelta(days=1)).weekday()]) or []
        std_close = datetime.time.fromisoformat(std_raw[-1][1]) if std_raw else close_t
        if at >= close_dt:
            if explicit:
                raise PlanError("--flat-by %s is at or after the %s close on %s" % (hm(t), ampm(close_t), day))
            if close_t != std_close:
                moved = at - (datetime.datetime.combine(day, std_close) - close_dt)
                if moved.time() <= tw[0][0].time():
                    raise PlanError("flat_by %s in the config is at or after the close" % hm(t))
                t = moved.time()
                early_dates = (prof.get("early_close") or {}).get("dates") or {}
                note = "moved up for the early close (%s)" % early_dates.get(day.isoformat(), "")
            else:
                raise PlanError("flat_by %s in the config is at or after the close" % hm(t))
    if entry_time and entry_time >= t:
        raise PlanError("the entry at %s is at or after your flat-by %s: there is no time left to hold it"
                        % (ampm(entry_time), hm(t)))
    return hm(t), note


def gather(a, p=None, cfg=None):
    """The entry facts, from trader/entry.json or the flags."""
    prof = p or _IDX
    if a.symbol and a.from_path:
        raise PlanError("use --from or --symbol, not both")
    if a.side in ("sell", "short"):
        if not market.allows_short(prof, cfg):
            raise PlanError("v2 plans longs only: no stops above a short entry. Plan a buy instead.")
        side = "sell"
    else:
        side = "buy"
    if a.symbol:
        if a.entry is None:
            raise PlanError("--symbol needs --entry PRICE")
        if (a.or_high is None) != (a.or_low is None):
            raise PlanError("give both --or-high and --or-low, or neither")
        info = {"symbol": a.symbol.upper(), "side": side, "entry": a.entry, "setup": a.setup or ("orb" if a.or_high is not None else "level"),
                "date": a.date, "entry_time": a.time, "entry_bar": a.entry_bar, "interval": a.interval or "5m",
                "or_high": a.or_high, "or_low": a.or_low, "or_minutes": a.or_minutes,
                "prev_close": getattr(a, "prev_close", None), "source": "flags"}
    else:
        path = a.from_path or "trader/entry.json"
        doc = read_json(path, "entry (run /trader-entry first, or give --symbol and --entry)")
        doc_side = str(doc.get("side") or "buy").lower()
        if doc_side not in ("buy", "long"):
            if not market.allows_short(prof, cfg):
                raise PlanError("%s is a %s: v2 plans longs only" % (path, doc.get("side")))
            side = "sell"
        if doc.get("status") != "triggered" and a.entry is None:
            raise PlanError("%s says %s is %s, not triggered: plan once it triggers, or give --entry PRICE to plan ahead"
                            % (path, doc.get("symbol"), doc.get("status") or "unknown"))
        orr = doc.get("opening_range") or {}
        info = {"symbol": str(doc.get("symbol") or "").upper(), "side": side, "entry": a.entry if a.entry is not None else doc.get("price"),
                "setup": a.setup or doc.get("setup") or "orb", "date": a.date or doc.get("date"),
                "entry_time": a.time or (doc.get("time") if a.entry is None else None),
                "entry_bar": a.entry_bar if a.entry_bar is not None else (doc.get("bar_index") if a.entry is None else None),
                "interval": a.interval or doc.get("interval") or "5m",
                "or_high": a.or_high if a.or_high is not None else orr.get("high"),
                "or_low": a.or_low if a.or_low is not None else orr.get("low"),
                "or_minutes": orr.get("minutes") or a.or_minutes,
                "prev_close": getattr(a, "prev_close", None) if getattr(a, "prev_close", None) is not None else doc.get("prev_close"),
                "source": path}
        if not info["symbol"] or info["entry"] is None:
            raise PlanError("%s has no symbol or price" % path)
    if info["interval"] not in INTERVALS:
        raise PlanError("interval is 5m or 1m")
    return info


def build_plan(a, now_utc):
    cfg = read_config(a.config)
    p = market.from_config(cfg)
    info = gather(a, p=p, cfg=cfg)
    info["symbol"] = market.base_symbol(p, info["symbol"])
    if p.get("pairs"):
        try:
            market.require_pair(p, info["symbol"])
        except ValueError as e:
            raise PlanError(str(e))
    side = info.get("side", "buy")
    stop_text = a.stop
    if not stop_text:
        if info["setup"] != "orb":
            raise PlanError("a %s setup has no opening-range stop to default to: give --stop price:X, pct:X or atr:K"
                            % info["setup"])
        stop_text = "or-mid"
    stop_rule, stop_param = parse_stop(stop_text)
    target_rule, target_param = parse_target(a.target or "2R")
    day = None
    if info["date"]:
        try:
            day = datetime.date.fromisoformat(str(info["date"]))
        except ValueError:
            raise PlanError("date wants YYYY-MM-DD, not %r" % info["date"])
    else:
        day = market.to_local(p, now_utc).date()
    entry_time = parse_clock(info["entry_time"], "the entry time") if info["entry_time"] else None
    atr = atr_n = None
    prev_close = info.get("prev_close")
    if stop_rule == "atr" or (p.get("auto_rejection") and prev_close is None and a.offline):
        chart = load_chart(info["symbol"], info["interval"], day, a.offline, p=p)
        if prev_close is None:
            prev_close = chart.get("prev_close")
        if stop_rule == "atr":
            bars = session_bars(chart, day, info["interval"], info["entry_bar"],
                                parse_now(a.now, p=p) if a.now else None, p=p)
            if len(bars) < 3:
                raise PlanError("an atr stop needs at least 3 closed %s bars of %s on %s by the entry; found %d"
                                % (info["interval"], info["symbol"], day, len(bars)))
            atr, atr_n = atr_of(bars)
    c = compute(info["entry"], stop_rule, stop_param, target_rule, target_param, info["or_high"], info["or_low"],
                atr, atr_n, p=p, side=side, symbol=info["symbol"])
    flat_by, flat_note = resolve_flat_by(day, a.flat_by, cfg, entry_time, p=p)
    orr = None
    if info["or_high"] is not None and info["or_low"] is not None:
        oh_val = market.round_tick(p, D(info["or_high"]), "nearest", symbol=info["symbol"])
        ol_val = market.round_tick(p, D(info["or_low"]), "nearest", symbol=info["symbol"])
        orr = {"high": float(oh_val), "low": float(ol_val),
               "minutes": int(info["or_minutes"] or 15)}
    plan = {"created_by": "trader-exit", "symbol": info["symbol"], "side": side, "date": day.isoformat(),
            "setup": info["setup"], "entry": float(c["entry"]),
            "entry_time": ampm(entry_time) if entry_time else None,
            "entry_bar": info["entry_bar"], "interval": info["interval"], "opening_range": orr,
            "stop": float(c["stop"]), "stop_rule": stop_rule, "stop_label": c["stop_label"],
            "target": float(c["target"]), "target_r": float(c["target_r"]), "target_label": c["target_label"],
            "risk_per_share": float(c["risk"]), "reward_risk": float(c["reward_risk"]), "flat_by": flat_by,
            "stop_detail": c["stop_detail"], "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), "note": NOTE,
            "market": p["id"]}
    if prev_close is not None:
        pc = D(prev_close, "prev_close")
        if pc > 0:
            plan["prev_close"] = float(pc)
    pip = market.pip_size(p, info["symbol"])
    if pip is not None:
        t_dist = (c["entry"] - c["target"]) if side == "sell" else (c["target"] - c["entry"])
        plan["pip_size"] = float(pip)
        plan["risk_pips"] = float((c["risk"] / pip).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        plan["target_pips"] = float((t_dist / pip).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    if atr is not None:
        plan["atr"] = round(atr, max(4, market.price_decimals(p)))
        plan["atr_bars"] = atr_n
    warnings = []
    if flat_note:
        warnings.append("Flat-by %s: %s." % (flat_by, flat_note))
    mrr = cfg.get("min_reward_risk")
    try:
        if mrr is not None and c["reward_risk"] < D(mrr):
            warnings.append("Reward:risk %s is under your min_reward_risk %s in the config: trader-risk checks that."
                            % (ratio(c["reward_risk"]), num(D(mrr))))
    except PlanError:
        pass
    warnings.extend(ar_warnings(p, c["stop"], c["target"], prev_close, day))
    now_local = market.to_local(p, now_utc)
    lunch = _holds_through_lunch(p, day, entry_time, parse_hhmm(flat_by, "flat_by", p=p), now_local)
    if lunch:
        warnings.append("Plan holds through the lunch break (%s-%s): the price can gap after the lunch break."
                        % (hm(lunch[0]), hm(lunch[1])))
    today = now_local.date()
    if day != today:
        warnings.append("This plan is for %s, not today (%s)." % (day.isoformat(), today.isoformat()))
    cal_note = market.calendar_note(p, day) or market.calendar_note(p, today)
    if cal_note:
        warnings.append(cal_note)
    return plan, warnings


def describe(plan, p=None):
    prof = p or (market.load(plan["market"]) if plan.get("market") else _IDX)
    day = datetime.date.fromisoformat(plan["date"])
    setup = {"orb": "opening-range breakout", "level": "close above a level"}.get(plan["setup"], plan["setup"])
    e = D(plan["entry"])
    risk = D(plan["risk_per_share"])
    pct = (risk / e * 100).quantize(CENT, rounding=ROUND_HALF_UP)
    when = ""
    if plan.get("entry_time"):
        when = " at %s" % plan["entry_time"]
        if plan.get("entry_bar") is not None:
            when += " (bar %d)" % plan["entry_bar"]
    sym = plan["symbol"]
    side_word = "short" if plan.get("side") == "sell" else "long"
    pip_s = (" (%.1f pips)" % plan["risk_pips"]) if plan.get("risk_pips") is not None else ""
    t_pip_s = (" (%.1f pips)" % plan["target_pips"]) if plan.get("target_pips") is not None else ""
    out = ["Exit plan: %s %s, %s, %s on %s bars" % (
        sym, side_word, day.strftime("%a %Y-%m-%d"), setup, "5-minute" if plan["interval"] == "5m" else "1-minute")]
    out.append("  Entry         %s%s" % (_money(plan["entry"], prof, symbol=sym), when))
    out.append("  Stop          %s  %s%s%s" % (_money(plan["stop"], prof, symbol=sym), plan["stop_label"], pip_s,
                                               (": " + plan["stop_detail"]) if plan.get("stop_detail") else ""))
    out.append("  Target        %s  %s%s" % (_money(plan["target"], prof, symbol=sym), plan["target_label"], t_pip_s))
    out.append("  Risk a share  %s (%s%% of the entry)%s" % (_money(plan["risk_per_share"], prof, symbol=sym), pct, pip_s))
    out.append("  Reward:risk   %s" % ratio(plan["reward_risk"]))
    out.append("  Flat by       %s %s, win or lose: no overnight hold" % (plan["flat_by"], _tz_label(prof)))
    out.append("Set before the entry. If price hits the stop, you are out; never move it further away.")
    out.append(NOTE)
    return out


def cmd_plan(a):
    cfg = read_config(a.config)
    p = market.from_config(cfg)
    now = parse_now(a.now, p=p)
    plan, warnings = build_plan(a, now)
    if a.write:
        d = os.path.dirname(a.write)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.write, "w", encoding="utf-8") as fh:
            json.dump(plan, fh, indent=2)
            fh.write("\n")
    if a.json:
        print(json.dumps(dict(plan, warnings=warnings), indent=2))
        return 0
    for line in describe(plan, p=p):
        print(line)
    for w in warnings:
        print("Note: " + w)
    if a.write:
        print("Wrote %s." % a.write)
    print("Next: /trader-timemachine replays it, then /trader-budget sizes it to your max loss. Nothing was placed.")
    return 0


def cmd_show(a):
    if not os.path.exists(a.plan):
        print("No plan at %s yet. Make one: exit.py plan --write" % a.plan)
        return 1
    plan = read_json(a.plan, "plan")
    for k in ("symbol", "date", "entry", "stop", "target", "risk_per_share", "reward_risk", "flat_by"):
        if plan.get(k) is None:
            raise PlanError("%s is missing %r: make a new plan with exit.py plan --write" % (a.plan, k))
    p = market.load(plan["market"]) if plan.get("market") else market.from_config(getattr(a, "config", None))
    plan = dict(plan, symbol=market.base_symbol(p, plan["symbol"]))
    if a.json:
        print(json.dumps(plan, indent=2))
        return 0
    for line in describe(dict({"setup": "orb", "interval": "5m", "stop_label": "", "target_label": ""}, **plan), p=p):
        print(line)
    today_d = market.to_local(p, parse_now(a.now, p=p)).date()
    today = today_d.isoformat()
    if plan["date"] != today:
        print("Note: this plan is for %s, not today (%s)." % (plan["date"], today))
    cal_note = market.calendar_note(p, plan["date"]) or market.calendar_note(p, today_d)
    if cal_note:
        print("Note: " + cal_note)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Exit Planner (trader-exit): the stop and target before the entry.")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="set the stop and target")
    p.add_argument("--from", dest="from_path", metavar="PATH", help="entry.json to plan from (default trader/entry.json)")
    p.add_argument("--symbol")
    p.add_argument("--entry", type=float, help="entry price (or a plan-ahead price with --from)")
    p.add_argument("--or-high", type=float)
    p.add_argument("--or-low", type=float)
    p.add_argument("--or-minutes", type=int, default=15)
    p.add_argument("--setup", choices=["orb", "level"])
    p.add_argument("--date", help="session date YYYY-MM-DD (default: the entry's, or today)")
    p.add_argument("--time", help="entry time, e.g. 10:15 AM")
    p.add_argument("--entry-bar", type=int)
    p.add_argument("--interval", choices=["5m", "1m"])
    p.add_argument("--side", default="buy", choices=["buy", "long", "sell", "short"], help="v2: buy only")
    p.add_argument("--stop", help="or-mid (orb default), or-low, price:X, pct:X, atr:K")
    p.add_argument("--target", help="2R (default), 1R, 1.5R, price:X")
    p.add_argument("--flat-by", help="HH:MM market time (default: config flat_by, 15:45)")
    p.add_argument("--prev-close", type=float, help="previous close for ARA/ARB checks")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--offline", metavar="PATH", help="saved Yahoo chart JSON for an atr stop")
    p.add_argument("--now", help='pretend it is this WIB time, e.g. "2026-11-23 09:35"')
    p.add_argument("--write", nargs="?", const="trader/plan.json", metavar="PATH",
                   help="save the plan (default trader/plan.json)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("show", help="print the current plan")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--config", default="trader/config.json")
    p.add_argument("--now")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"plan": cmd_plan, "show": cmd_show}[a.cmd](a)
    except PlanError as e:
        print("exit.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
