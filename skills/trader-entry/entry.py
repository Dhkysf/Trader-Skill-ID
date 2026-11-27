#!/usr/bin/env python3
"""Entry Timer for trader-entry: watches a setup bar by bar and says the
moment to get in. Standard library only. Long side only. It never places an order.

    python entry.py check BBCA                          # opening-range breakout, 5-minute bars
    python entry.py check BBCA --now "2026-11-23 09:35" --offline BBCA.JK.json.gz
    python entry.py check BBCA --setup level --level 5540     # first close above a price
    python entry.py check BBCA --interval 1m --min-volume-x 1.5 --write
    python entry.py watch BBCA --every 30 --until 15:30 # one line per closed bar
    python entry.py watchlist                           # every hit in trader/watchlist.json

Setups (v2 plans longs only):
  orb    opening-range breakout. The range is the high and low of the first
         --or-minutes (default 15: the 09:00, 09:05 and 09:10 five-minute bars).
         It triggers on the first COMPLETED bar after the range that CLOSES
         above the range high. A wick above the high is not a trigger.
  level  the first completed bar that closes above --level (for example a
         20-day high from trader-scanner).
  --min-volume-x X  the trigger bar also needs at least X times the average
         volume of the opening-range bars.

A trigger's time is the trigger bar's CLOSE time (the 09:30 bar closes at
9:35 AM) and its price is that close. Only bars on the interval
grid count (Yahoo's live tick, e.g. 10:49:45, is dropped) and a bar counts only
once it has closed: now >= its start + the interval.

Statuses: triggered; waiting (not open yet, range still forming, or no close
above the level yet); expired (no trigger by no_entries_after, default 15:30);
no-data (the market is closed today or Yahoo sent no bars).

trader/config.json (optional): "no_entries_before" (09:15) and
"no_entries_after" (15:30), WIB.

watch wakes just after each bar closes (bars only change then), re-polls every
--every seconds (default 30) while Yahoo has not posted the new bar, prints one
line per closed bar and stops on a trigger (exit 0, writes trader/entry.json),
on expiry, at the close or at --until (exit 1). With --now or --offline it runs
on a simulated clock and replays the day without sleeping.

Data: Yahoo's free chart JSON (unofficial, can lag, bars not single trades)
  https://query2.finance.yahoo.com/v8/finance/chart/BBCA.JK?range=1d&interval=5m
  falls back to query1 on HTTP 429 or 5xx; a 429 gets one retry after a pause.
  --offline PATH reads a saved chart JSON (.json or .json.gz) instead, or
  PATH/<TICKER>.json when PATH is a folder. Without --now, an offline file is
  read as of its own time (meta.regularMarketTime).

Exit codes: check 0 = triggered, 1 = anything else or an error. watch 0 on a
trigger, 1 otherwise. watchlist 0 when at least one symbol triggered.
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

_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market  # noqa: E402

UA = "Mozilla/5.0 (compatible; trader-skill-id/0.1; +https://github.com/Dhkysf/Trader-Skill-ID)"
PAUSE = 0.5      # seconds between requests to the free endpoint
BACKOFF = 5.0    # seconds before the one retry after an HTTP 429
GRACE = 2        # seconds after a bar closes before watch asks for it
SETTLE = 60      # seconds a closed bar may wait for Yahoo's data to catch up
HOSTS = ("query2", "query1")
INTERVALS = {"1m": 60, "5m": 300}
DEFAULTS = {"no_entries_before": "09:15", "no_entries_after": "15:30"}
EPOCH = datetime.datetime(1970, 1, 1)

_IDX = market.load("idx")


class EntryError(Exception):
    pass


# ---------------------------------------------------------------- time

def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def utc_of(ts):
    """Unix seconds -> naive UTC, without the machine's time zone."""
    return EPOCH + datetime.timedelta(seconds=int(ts))


def ts_of(utc):
    return int((utc.replace(tzinfo=None) - EPOCH).total_seconds())


def iso(utc):
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tz_label(p):
    prof = p or _IDX
    return prof.get("tz_label") or prof.get("timezone") or "WIB"


def _place_label(p):
    return _tz_label(p)


def _exchange(p):
    return (p or _IDX).get("exchange") or "IDX"


def _px(val, p=None):
    return market.price(p or _IDX, val)


def _profile_defaults(p=None):
    cfg = dict(DEFAULTS)
    cfg["no_entries_before_break_min"] = 0
    for k, v in ((p or _IDX).get("defaults") or {}).items():
        if k in cfg:
            cfg[k] = v
    return cfg


def parse_now(text, p=None):
    """--now -> naive UTC. "2026-11-23 09:35" (or ...T09:35, or just 09:35 for
    today) is market local time; an offset or Z makes it absolute."""
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
        raise EntryError('--now wants a %s time like "2026-11-23 09:35" (or ...Z for UTC)' % _place_label(prof))
    if dt.tzinfo is None:
        return market.local_to_utc(prof, dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_hhmm(text, what, p=None):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise EntryError("%s wants a %s time like 15:30, not %r" % (what, _place_label(p), text))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def hm(t):
    """10:10, 09:45: the contract's wall-clock form."""
    return "%02d:%02d" % (t.hour, t.minute)


def short(t):
    """9:45, 10:10: for sentences."""
    return "%d:%02d" % (t.hour, t.minute)


def ampm(t):
    h = t.hour % 12 or 12
    return "%d:%02d %s" % (h, t.minute, "AM" if t.hour < 12 else "PM")


def trading_day(d, p=None):
    """(is_trading_day, reason). Weekends and the profile's holiday list."""
    prof = p or _IDX
    if market.is_trading_day(prof, d):
        return True, ""
    name = (prof.get("holidays") or {}).get(d.isoformat())
    return False, ("%s holiday: %s" % (_exchange(prof), name)) if name else "weekend"


def session(d, p=None):
    """(open_time, close_time) in market local time, or None if closed all day."""
    s = market.sessions(p or _IDX, d)
    return s[0] if s else None


def next_open(d, p=None):
    prof = p or _IDX
    nd = d + datetime.timedelta(days=1)
    for _ in range(15):
        ns = market.sessions(prof, nd)
        if ns:
            return "%s %s" % (nd.isoformat(), hm(ns[0][0]))
        nd += datetime.timedelta(days=1)
    return None


# ---------------------------------------------------------------- Yahoo

def yahoo_symbol(sym, p=None):
    return market.yahoo_symbol(p or _IDX, sym)


def chart_path(sym, rng, interval, p=None):
    return "/v8/finance/chart/%s?range=%s&interval=%s" % (yahoo_symbol(sym, p), rng, interval)


def chart_range(day, today, interval):
    """The smallest Yahoo range that still holds the session of `day`."""
    back = (today - day).days
    if back <= 0:
        return "1d"
    if back <= 6:
        return "5d"
    if interval == "1m":
        raise EntryError("Yahoo keeps 1-minute bars for about a week: use --interval 5m for %s" % day)
    if back <= 28:
        return "1mo"
    if back <= 58:
        return "60d"
    raise EntryError("Yahoo keeps 5-minute bars for about 60 days: %s is too far back" % day)


def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sleep(seconds):
    time.sleep(seconds)


def yahoo_get(path):
    """GET a Yahoo path: query2 first, query1 when query2 answers 429 or 5xx.
    An HTTP 429 gets one retry on the same host after BACKOFF seconds."""
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
                    raise EntryError("Yahoo has no chart at %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise EntryError("Yahoo answered HTTP %d for %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "could not connect: %s" % (e.reason,)
                break
            except OSError as e:
                last = "network error: %s" % (e,)
                break
    raise EntryError("Yahoo did not answer (%s on query2 and query1): wait a minute and try again" % last)


def parse_chart(text, sym, p=None):
    """Yahoo chart JSON v8 -> {symbol, meta, bars, prev_close, data_time}.
    Bars with a null close are dropped here; off-grid ticks later."""
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise EntryError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise EntryError("Yahoo has no data for %s: %s" % (sym, err.get("description") or "unknown ticker"))
    r = res[0] or {}
    meta = r.get("meta") or {}
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}

    def at(key, i):
        arr = q.get(key) or []
        return arr[i] if i < len(arr) else None

    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        c = at("close", i)
        if t is None or c is None:
            continue
        o, h, lo = at("open", i), at("high", i), at("low", i)
        bars.append({"t": int(t), "o": float(c if o is None else o), "h": float(c if h is None else h),
                     "l": float(c if lo is None else lo), "c": float(c), "v": int(at("volume", i) or 0)})
    prof = p or _IDX
    return {"symbol": market.base_symbol(prof, meta.get("symbol") or sym), "meta": meta, "bars": bars,
            "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
            "data_time": meta.get("regularMarketTime")}


def read_text(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def offline_file(path, sym, p=None):
    if os.path.isdir(path):
        prof = p or _IDX
        sym = market.base_symbol(prof, sym)
        ysym = yahoo_symbol(sym, prof)
        for name in (sym + ".json", sym + ".json.gz", ysym + ".json", ysym + ".json.gz"):
            fp = os.path.join(path, name)
            if os.path.exists(fp):
                return fp
        raise EntryError("no offline file for %s in %s (want %s.json)" % (sym, path, sym))
    if not os.path.exists(path):
        raise EntryError("no offline file %s" % path)
    return path


def get_chart(sym, interval, day=None, offline=None, today=None, p=None):
    """Bars for one ticker, from Yahoo (range=1d for today) or a saved file."""
    prof = p or _IDX
    sym = market.base_symbol(prof, sym)
    if offline:
        f = offline_file(offline, sym, prof)
        try:
            text = read_text(f)
        except (OSError, ValueError) as e:
            raise EntryError("could not read %s: %s" % (f, e))
    else:
        today = today or market.to_local(prof, utc_now()).date()
        text = yahoo_get(chart_path(sym, chart_range(day or today, today, interval), interval, prof))
    ch = parse_chart(text, sym, p=prof)
    if ch["symbol"] != sym:
        raise EntryError("the chart file holds %s, not %s" % (ch["symbol"], sym))
    gran = ch["meta"].get("dataGranularity")
    if gran and gran != interval:
        raise EntryError("%s has %s bars, not %s: use --interval %s" % (sym, gran, interval, gran))
    return ch


# ---------------------------------------------------------------- the rule

def read_config(path):
    doc = {}
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except ValueError as e:
            raise EntryError("%s is not valid JSON: %s" % (path, e))
    try:
        p = market.from_config(doc)
    except ValueError as e:
        raise EntryError(str(e))
    cfg = _profile_defaults(p)
    cfg["market"] = p["id"]
    for k in DEFAULTS:
        if doc.get(k):
            cfg[k] = doc[k]
    if doc.get("no_entries_before_break_min") is not None:
        cfg["no_entries_before_break_min"] = doc["no_entries_before_break_min"]
    for k in DEFAULTS:
        parse_hhmm(cfg[k], k, p=p)
    try:
        bmin = int(cfg["no_entries_before_break_min"])
    except (TypeError, ValueError):
        raise EntryError("no_entries_before_break_min must be a whole number >= 0")
    if bmin < 0:
        raise EntryError("no_entries_before_break_min must be >= 0")
    cfg["no_entries_before_break_min"] = bmin
    return cfg


def r2(x, dec=2):
    return None if x is None else round(float(x), dec) + 0.0   # + 0.0 turns -0.0 into 0.0


def early_cutoff(day, t, close_dt, open_t, std_close):
    """A cutoff on an early-close day moves up with the close."""
    at = datetime.datetime.combine(day, t)
    if at < close_dt:
        return at
    moved = at - (datetime.datetime.combine(day, std_close) - close_dt)
    return moved if moved.time() > open_t else close_dt


def evaluate(chart, now_utc, setup="orb", or_minutes=15, interval="5m", level=None,
             min_volume_x=None, cfg=None, p=None):
    """Pure function: the setup's status at now_utc from one session's bars."""
    try:
        prof = p or market.from_config(cfg)
    except ValueError as e:
        raise EntryError(str(e))
    eff_cfg = _profile_defaults(prof)
    for k, v in (cfg or {}).items():
        if v is not None:
            eff_cfg[k] = v
    delay_min = int(prof.get("data_delay_min") or 0)
    pdec = max(2, market.price_decimals(prof))
    cal_years = tuple(prof.get("calendar_years") or ())
    early_dates = (prof.get("early_close") or {}).get("dates") or {}

    if interval not in INTERVALS:
        raise EntryError("--interval is 5m or 1m")
    step = INTERVALS[interval]
    if or_minutes <= 0 or (or_minutes * 60) % step:
        raise EntryError("--or-minutes must be a whole number of %s bars" % interval)
    if setup not in ("orb", "level"):
        raise EntryError("--setup is orb or level")
    if setup == "level" and level is None:
        raise EntryError("--setup level needs --level PRICE (for example a 20-day high)")
    n_or = or_minutes * 60 // step
    local = market.to_local(prof, now_utc)
    day = local.date()
    prev_close = chart.get("prev_close")
    prior_day, prior_close = None, None
    for b in chart["bars"]:
        if b["t"] % step:
            continue
        bt = market.to_local(prof, utc_of(b["t"]))
        if bt.date() < day and (prior_day is None or bt.date() >= prior_day):
            prior_day = bt.date()
            prior_close = b["c"]
    if prior_close is not None:
        prev_close = prior_close
    res = {"symbol": market.base_symbol(prof, chart["symbol"]), "setup": setup, "side": "buy", "date": day.isoformat(),
           "interval": interval, "or_minutes": or_minutes, "now": local.strftime("%Y-%m-%d %H:%M:%S"), "status": "waiting",
           "phase": "", "reason": "", "opening_range": None, "level": None, "trigger": None,
           "last": None, "forming": None, "min_volume_x": min_volume_x,
           "prev_close": prev_close, "calendar_known": day.year in cal_years, "_bars": []}
    res.update(market=prof["id"], tz_label=_tz_label(prof), data_delay_min=delay_min)
    dt = chart.get("data_time")
    res["data_time"] = market.to_local(prof, utc_of(dt)).strftime("%Y-%m-%d %H:%M:%S") if dt else None
    ok, why = trading_day(day, prof)
    if not ok:
        res.update(status="no-data", phase="closed", reason="the %s is closed today (%s)" % (_exchange(prof), why),
                   next_open=next_open(day, prof))
        return res
    sess = market.sessions(prof, day)
    windows = [(datetime.datetime.combine(day, o), datetime.datetime.combine(day, c)) for o, c in sess]
    open_dt, close_dt = windows[0][0], windows[-1][1]
    std_raw = prof["sessions"][market._WEEKDAYS[day.weekday()]]
    std_close = datetime.time.fromisoformat(std_raw[-1][1])
    early = sess[-1][1] != std_close
    before = datetime.datetime.combine(day, parse_hhmm(eff_cfg["no_entries_before"], "no_entries_before", p=prof))
    cutoff = early_cutoff(day, parse_hhmm(eff_cfg["no_entries_after"], "no_entries_after", p=prof),
                          close_dt, sess[0][0], std_close)
    break_min = int(eff_cfg.get("no_entries_before_break_min") or 0)
    break_buf = datetime.timedelta(minutes=break_min)
    breaks = [(windows[i][1], windows[i + 1][0]) for i in range(len(windows) - 1)]
    or_end = open_dt + datetime.timedelta(minutes=or_minutes)
    res.update(opens=hm(sess[0][0]), closes=hm(sess[-1][1]), early_close=early_dates.get(day.isoformat()),
               no_entries_before=hm(before), no_entries_after=hm(cutoff))

    by_slot = {}
    for b in chart["bars"]:
        if b["t"] % step:
            continue                       # Yahoo's live tick (10:49:45) is not a bar
        et = market.to_local(prof, utc_of(b["t"]))
        if et.date() != day or not any(so <= et < sc for so, sc in windows):
            continue
        slot = int((et - open_dt).total_seconds()) // step
        by_slot[slot] = dict(b, et=et, end=et + datetime.timedelta(seconds=step), slot=slot)
    bars, pending = [], None
    now_ts = ts_of(now_utc)
    top = max(by_slot) if by_slot else -1
    for slot in sorted(by_slot):
        b = by_slot[slot]
        end_ts = b["t"] + step
        if end_ts <= now_ts:
            # Closed by the clock. On live data it counts once Yahoo has caught up: its last
            # trade is at or after the close, a later bar exists, or a minute has passed.
            if dt is None or dt >= end_ts or slot < top or now_ts >= end_ts + SETTLE:
                bars.append(b)
            else:
                pending = b
                res["forming"] = {"bar_start": hm(b["et"]), "closes": ampm(b["end"]), "price": r2(b["c"], pdec)}
                res["lag_note"] = ("Yahoo's last trade is %s, before the %s bar's close: it counts once Yahoo "
                                   "catches up (a minute at most)" % (market.to_local(prof, utc_of(dt)).strftime("%H:%M:%S"),
                                                                       short(b["et"])))
        elif b["et"] <= local:
            res["forming"] = {"bar_start": hm(b["et"]), "closes": ampm(b["end"]), "price": r2(b["c"], pdec)}
    res["_bars"] = bars
    res["bars_closed"] = len(bars)

    if local < open_dt:
        res.update(phase="pre-open", reason="the %s opens at %s%s" % (
            _exchange(prof), short(open_dt),
            " and the %d-minute range is set at %s" % (or_minutes, short(or_end)) if setup == "orb" else ""))
        return res

    or_bars = [b for b in bars if b["slot"] < n_or]
    avg_vol = (sum(b["v"] for b in or_bars) / float(len(or_bars))) if or_bars else None
    if or_bars:
        res["opening_range"] = {"high": r2(max(b["h"] for b in or_bars), pdec), "low": r2(min(b["l"] for b in or_bars), pdec),
                                "minutes": or_minutes, "bars": len(or_bars), "of": n_or,
                                "complete": local >= or_end, "avg_volume": int(round(avg_vol))}
    if setup == "orb":
        if local < or_end:
            res.update(phase="forming", reason="%d of %d range bars closed; the range is set at %s" % (
                len(or_bars), n_or, short(or_end)))
            return res
        if not or_bars:
            res.update(status="no-data", phase="open", reason="Yahoo sent no bars for the opening range")
            return res
        lvl = max(b["h"] for b in or_bars)
    else:
        lvl = float(level)
    res["level"] = r2(lvl, pdec)

    first_slot = n_or if setup == "orb" else 0
    trig, thin, pre_break = None, [], []
    for b in bars:
        if b["slot"] < first_slot or b["end"] < before or b["end"] > cutoff:
            continue
        if break_min > 0 and any(bs - break_buf < b["end"] <= bs for bs, _ in breaks):
            if b["c"] > lvl:
                pre_break.append(b)
            continue
        if b["c"] > lvl:
            vx = (b["v"] / avg_vol) if avg_vol else None
            if min_volume_x and (vx is None or vx < min_volume_x):
                thin.append(b)
                continue
            trig = b
            break
    last = bars[-1] if bars else None
    if last:
        res["last"] = {"bar_start": hm(last["et"]), "close": r2(last["c"], pdec),
                       "vs_level_pct": r2(100.0 * (last["c"] / lvl - 1))}

    if trig:
        vx = (trig["v"] / avg_vol) if avg_vol else None
        res.update(status="triggered", phase="open" if local < close_dt else "after-close",
                   reason="the %s bar closed above %s" % (short(trig["et"]), "the range high" if setup == "orb" else "the level"))
        res["trigger"] = {"time": ampm(trig["end"]), "close_time": hm(trig["end"]), "bar_start": hm(trig["et"]),
                          "bar_index": trig["slot"], "price": r2(trig["c"], pdec), "close": trig["c"],
                          "volume": trig["v"], "volume_x": r2(vx), "pct_over": r2(100.0 * (trig["c"] / lvl - 1))}
        res["minutes_since"] = int((local - trig["end"]).total_seconds() // 60)
        if dt and utc_of(dt) < market.local_to_utc(prof, trig["end"]):
            res["data_note"] = ("Yahoo's last trade is %s, before this bar closed: its close can still move a cent or two"
                                % market.to_local(prof, utc_of(dt)).strftime("%H:%M:%S"))
        return res
    for bs, be in breaks:
        if bs <= local < be:
            res.update(status="waiting", phase="lunch-break", next_session=hm(be),
                       reason="market on lunch break, next session at %s" % hm(be))
            return res
    if not bars:
        res.update(status="no-data", phase="open", reason="Yahoo sent no bars for %s yet" % day.isoformat())
        return res
    what = "close above the range high %s" % _px(lvl, prof) if setup == "orb" else "close above %s" % _px(lvl, prof)
    if local >= cutoff and not (pending and pending["end"] <= cutoff):
        res.update(status="expired", phase="after-close" if local >= close_dt else "after-cutoff",
                   reason="no %s by %s, the last time for a new entry%s" % (
                       what, short(cutoff), " (early close today)" if early else ""))
        return res
    res["phase"] = "open"
    if last["c"] > lvl and last in thin:
        res["reason"] = "the %s bar closed above at %s but on %.2fx the range's volume, under your %.2fx" % (
            short(last["et"]), _px(last["c"], prof), last["v"] / avg_vol if avg_vol else 0, min_volume_x)
    elif last["c"] > lvl and last["end"] < before:
        res["reason"] = "the %s bar closed above at %s, but no entries before %s (config)" % (
            short(last["et"]), _px(last["c"], prof), short(before))
    elif last["c"] > lvl and last in pre_break:
        res["reason"] = "the %s bar closed above at %s, but within %d min of the lunch break" % (
            short(last["et"]), _px(last["c"], prof), break_min)
    else:
        gap = lvl - last["c"]
        res["reason"] = "last close %s (%s bar), %s %s %s (%+.2f%%)" % (
            _px(last["c"], prof), short(last["et"]), _px(abs(gap), prof), "under" if gap >= 0 else "over",
            "the range high %s" % _px(lvl, prof) if setup == "orb" else "the level %s" % _px(lvl, prof),
            100.0 * (last["c"] / lvl - 1))
    return res


def public(res):
    """The result without the internal bar list, ready for JSON."""
    return {k: v for k, v in res.items() if not k.startswith("_")}


def entry_doc(res, now_utc):
    """trader/entry.json, the contract shape (plus a plain-words reason)."""
    t = res.get("trigger") or {}
    orr = res.get("opening_range")
    prof = market.load(res["market"]) if res.get("market") else _IDX
    doc = {"created_by": "trader-entry", "symbol": market.base_symbol(prof, res["symbol"]), "setup": res["setup"], "side": "buy",
           "date": res["date"], "status": res["status"], "time": t.get("time"), "bar_start": t.get("bar_start"),
           "bar_index": t.get("bar_index"), "price": t.get("price"), "level": res.get("level"),
           "interval": res["interval"],
           "opening_range": {"high": orr["high"], "low": orr["low"], "minutes": orr["minutes"]} if orr else None,
           "source": "yahoo", "checked_at": iso(now_utc), "reason": res.get("reason")}
    if res.get("market"):
        doc["market"] = res["market"]
    if res.get("prev_close") is not None:
        doc["prev_close"] = res["prev_close"]
    return doc


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------- words

LABEL = {"triggered": "TRIGGERED", "waiting": "WAITING", "expired": "EXPIRED", "no-data": "NO DATA"}
PHASE_LABEL = {"pre-open": "NOT OPEN YET", "forming": "RANGE FORMING", "lunch-break": "LUNCH BREAK", "closed": "MARKET CLOSED"}
SHORT = {"pre-open": "not open", "forming": "forming", "lunch-break": "lunch", "closed": "closed"}


def setup_name(res, p=None):
    if res["setup"] == "orb":
        return "opening-range breakout (%d-minute range)" % res["or_minutes"]
    return "close above %s" % _px(res["level"], p) if res["level"] is not None else "close above a level"


def describe(res):
    """Plain lines for a person."""
    p = market.load(res["market"]) if res.get("market") else _IDX
    delay_min = int(p.get("data_delay_min") or 0)
    when = datetime.datetime.strptime(res["now"], "%Y-%m-%d %H:%M:%S")
    bars = "5-minute" if res["interval"] == "5m" else "1-minute"
    lag_tag = "data about %d min late" % delay_min if delay_min > 0 else "can lag"
    head = "%s  %s %s %s  %s on %s bars (Yahoo, free, %s)" % (
        res["symbol"], when.strftime("%a %Y-%m-%d"), when.strftime("%H:%M"), _tz_label(p),
        setup_name(res, p), bars, lag_tag)
    if res.get("data_time") and res["data_time"] <= res["now"] and res["data_time"][:10] == res["date"]:
        head += ", data to %s" % res["data_time"][11:]
    out = [head]
    orr = res.get("opening_range")
    if orr:
        start = datetime.datetime.strptime(res["opens"], "%H:%M")
        end = start + datetime.timedelta(minutes=orr["minutes"])
        out.append("Opening range %s-%s: high %s, low %s (%d of %d bars%s)." % (
            short(start), short(end), _px(orr["high"], p), _px(orr["low"], p), orr["bars"], orr["of"],
            "" if orr["complete"] else ", still forming"))
    label = PHASE_LABEL.get(res["phase"]) or LABEL.get(res["status"], res["status"].upper())
    t = res.get("trigger")
    if t:
        delay_note = ("; data about %d min late" % delay_min) if delay_min > 0 else ""
        out.append("TRIGGERED %s at %s: the %s bar (bar %d%s) closed above %s %s (%+.2f%%%s)." % (
            t["time"], _px(t["price"], p), short(datetime.datetime.strptime(t["bar_start"], "%H:%M")),
            t["bar_index"], delay_note,
            "the range high" if res["setup"] == "orb" else "the level", _px(res["level"], p), t["pct_over"],
            (", %.2fx the range's volume" % t["volume_x"]) if res.get("min_volume_x") and t.get("volume_x") else ""))
        step = INTERVALS[res["interval"]] // 60
        if res.get("minutes_since", 0) > step and res.get("last"):
            out.append("That was %d minutes ago; the last close is %s (%s bar). A late entry is a different "
                       "trade: the price, the stop distance and the odds have moved." % (
                           res["minutes_since"], _px(res["last"]["close"], p), res["last"]["bar_start"]))
        if res.get("data_note"):
            out.append(res["data_note"] + ".")
        if res.get("minutes_since", 0) > step:
            out.append("Nothing was placed.")
        else:
            out.append("This is the moment to get in, if you take the trade. Nothing was placed.")
        out.append("Next: set the stop and target BEFORE you buy: /trader-exit "
                   "(exit.py plan --from trader/entry.json).")
    else:
        out.append("%s  %s." % (label, res["reason"]))
        f = res.get("forming")
        if res.get("lag_note") and res["status"] == "waiting":
            out.append(res["lag_note"] + ".")
        elif f and res["status"] == "waiting" and res["phase"] in ("open", "forming"):
            out.append("The %s bar is still forming (%s so far, closes %s); it does not count until it closes." % (
                f["bar_start"].lstrip("0"), _px(f["price"], p), f["closes"]))
        if res["status"] == "expired":
            out.append("No entry on this setup today. Nothing was placed.")
        if res.get("next_open"):
            out.append("Next open: %s %s." % (res["next_open"], _place_label(p)))
    if res.get("early_close"):
        out.append("Early close today (%s): no new entries after %s." % (
            res["early_close"], res["no_entries_after"]))
    cal_note = market.calendar_note(p, res["date"]) if res.get("date") else None
    if cal_note:
        out.append(cal_note)
    return out


def bar_line(b, res):
    """One watch line for a bar that just closed."""
    p = market.load(res["market"]) if res.get("market") else _IDX
    delay_min = int(p.get("data_delay_min") or 0)
    start = short(b["et"])
    orr = res.get("opening_range") or {}
    lvl = res.get("level")
    t = res.get("trigger")
    n_or = orr.get("of") or 0
    if res["setup"] == "orb" and b["slot"] < n_or:
        seen = [x for x in res["_bars"] if x["slot"] <= b["slot"]]
        note = "range so far %s to %s" % (_px(min(x["l"] for x in seen), p), _px(max(x["h"] for x in seen), p))
        if b["slot"] == n_or - 1:
            note = "opening range set: high %s, low %s" % (_px(orr["high"], p), _px(orr["low"], p))
    elif t and t["bar_index"] == b["slot"]:
        delay_note = ("; data about %d min late" % delay_min) if delay_min > 0 else ""
        note = "TRIGGERED: closed above %s (%+.2f%%%s). Get in now if you take it: %s, %s" % (
            _px(lvl, p), t["pct_over"], delay_note, t["time"], _px(t["price"], p))
    elif lvl is None:
        note = ""
    elif b["c"] > lvl:
        note = "above %s" % _px(lvl, p)
        if res["setup"] == "level" or b["slot"] >= n_or:
            avg = orr.get("avg_volume")
            if res.get("min_volume_x") and avg:
                note += ", but volume %.2fx is under %.2fx" % (b["v"] / float(avg), res["min_volume_x"])
            elif b["end"] < datetime.datetime.combine(b["et"].date(), parse_hhmm(res["no_entries_before"], "x", p=p)):
                note += ", but no entries before %s" % res["no_entries_before"]
    else:
        note = "%s under %s" % (_px(lvl - b["c"], p), _px(lvl, p))
    return "%5s bar  closed %s  %s" % (start, _px(b["c"], p), note)


# ---------------------------------------------------------------- watch

class SimClock(object):
    """A clock that moves only when it sleeps: replays a day without waiting."""

    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += datetime.timedelta(seconds=max(1, int(round(seconds))))


def watch_loop(provider, clock, sleep, emit, opts, every=30, until=None, max_errors=5, on_trigger=None):
    """Poll bar by bar until a trigger (0), expiry, the close or --until (1).
    provider(now_utc) -> chart, clock() -> naive UTC, sleep(seconds), emit(line).
    It sleeps in steps of at most `every` seconds and re-reads the clock each time,
    so a computer that dozed off catches up as soon as it wakes."""
    prof = market.from_config((opts or {}).get("cfg"))
    tz_lbl = _tz_label(prof)
    delay_min = int(prof.get("data_delay_min") or 0)
    pdec = max(2, market.price_decimals(prof))
    delay = delay_min * 60
    step = INTERVALS[opts.get("interval", "5m")]
    printed, errors, said_preopen, said_delay, said_break, said_cal, first = -1, 0, False, False, None, False, True
    next_fetch = None
    while True:
        now = clock()
        if next_fetch is not None and now < next_fetch:
            sleep(max(1, min(every, (next_fetch - now).total_seconds())))
            continue
        local = market.to_local(prof, now)
        day = local.date()
        cal_note = market.calendar_note(prof, day)
        if not said_cal:
            if cal_note:
                emit(cal_note)
            said_cal = True
        sess = market.sessions(prof, day)
        if not sess:
            emit("%s: market closed today (%s). Nothing to watch." % (day.isoformat(), trading_day(day, prof)[1]))
            return 1, None
        if delay_min > 0 and not said_delay:
            emit("%s data is about %d min late: each bar is checked about %d min after it closes." % (
                _exchange(prof), delay_min, delay_min))
            said_delay = True
        open_dt = datetime.datetime.combine(day, sess[0][0])
        close_dt = datetime.datetime.combine(day, sess[-1][1])
        if local < open_dt + datetime.timedelta(seconds=step):
            if not said_preopen:
                emit("%s %s  %s: watching from the first bar's close at %s." % (
                    local.strftime("%H:%M"), tz_lbl,
                    "not open yet" if local < open_dt else "open, no bar closed yet",
                    short(open_dt + datetime.timedelta(seconds=step))))
                said_preopen = True
            next_fetch = market.local_to_utc(prof, open_dt) + datetime.timedelta(seconds=step + delay + GRACE)
            continue
        try:
            chart = provider(now)
            errors = 0
        except EntryError as e:
            errors += 1
            emit("%s %s  could not read bars: %s" % (local.strftime("%H:%M:%S"), tz_lbl, e))
            if errors >= max_errors:
                emit("Stopping after %d failed reads in a row." % errors)
                return 1, None
            next_fetch = now + datetime.timedelta(seconds=every)
            continue
        res = evaluate(chart, now, **opts)
        bars = res["_bars"]
        lines = describe(res)
        fresh = first
        if first:
            emit(lines[0])
            if len(lines) > 1 and lines[1].startswith("Opening range"):
                emit(lines[1])
            if bars and not res.get("trigger"):
                emit(bar_line(bars[-1], res))
            printed = bars[-1]["slot"] if bars else -1
            first = False
        else:
            for b in bars:
                if b["slot"] > printed:
                    emit(bar_line(b, res))
                    printed = b["slot"]
        if res["status"] == "triggered":
            for line in lines[1:]:
                if line.startswith("Opening range") or (line.startswith("TRIGGERED") and not fresh) or line == cal_note:
                    continue
                emit(line)
            if on_trigger:
                on_trigger(res, now)
            return 0, res
        if res["status"] == "expired" or local >= close_dt:
            emit("EXPIRED  %s." % (res["reason"] or "the market closed without a trigger"))
            return 1, res
        if until and local >= until:
            emit("Stopped at --until %s without a trigger. %s." % (short(until), res["reason"]))
            return 1, res
        if res["phase"] == "lunch-break":
            be = datetime.datetime.combine(day, parse_hhmm(res["next_session"], "next_session", p=prof))
            if said_break != res["next_session"]:
                emit("LUNCH BREAK  %s." % res["reason"])
                said_break = res["next_session"]
            nxt = be + datetime.timedelta(seconds=step + GRACE)
            if until and until < nxt:
                nxt = until
            next_fetch = market.local_to_utc(prof, nxt)
            continue
        # sleep until just after the next bar is expected; poll every `every` seconds if Yahoo is behind
        feed_local = local - datetime.timedelta(seconds=delay)
        feed_slot = int((feed_local - open_dt).total_seconds() // step)
        expected_last, next_slot = -1, None
        for so_t, sc_t in sess:
            s_first = int((datetime.datetime.combine(day, so_t) - open_dt).total_seconds() // step)
            s_last = int(((datetime.datetime.combine(day, sc_t) - open_dt).total_seconds() - 1) // step)
            if feed_slot - 1 >= s_first:
                expected_last = min(feed_slot - 1, s_last)
            if next_slot is None and feed_slot <= s_last:
                next_slot = max(feed_slot, s_first)
        behind = expected_last >= 0 and ((not bars) or bars[-1]["slot"] < expected_last)
        if behind:
            wait = every
        else:
            nxt = open_dt + datetime.timedelta(seconds=((next_slot if next_slot is not None else feed_slot) + 1) * step + delay + GRACE)
            wait = (nxt - local).total_seconds()
        cutoff = datetime.datetime.combine(day, parse_hhmm(res.get("no_entries_after") or "15:30", "cutoff", p=prof))
        for stop_at in (until, cutoff, close_dt):
            if stop_at and stop_at > local:
                wait = min(wait, (stop_at - local).total_seconds())
        next_fetch = now + datetime.timedelta(seconds=max(1, wait))


# ---------------------------------------------------------------- commands

def _opts(a, cfg):
    if a.side in ("sell", "short"):
        raise EntryError("v2 plans longs only: no short entries. Watch for a buy (--side buy) instead.")
    if a.setup == "orb" and a.level is not None:
        raise EntryError("--level is for --setup level (an orb's level is its range high)")
    if a.min_volume_x is not None and a.min_volume_x <= 0:
        raise EntryError("--min-volume-x must be above 0")
    if a.level is not None and a.level <= 0:
        raise EntryError("--level must be a price above 0")
    return {"setup": a.setup, "or_minutes": a.or_minutes, "interval": a.interval, "level": a.level,
            "min_volume_x": a.min_volume_x, "cfg": cfg}


def _load(a, sym, now, p=None):
    """(chart, now). An offline file without --now is read as of its own time."""
    prof = p or _IDX
    real_today = market.to_local(prof, utc_now()).date()
    if a.offline and now is None:
        ch = get_chart(sym, a.interval, offline=a.offline, p=prof)
        return ch, (utc_of(ch["data_time"]) if ch.get("data_time") else utc_now())
    now = now or utc_now()
    return get_chart(sym, a.interval, market.to_local(prof, now).date(), a.offline, real_today, p=prof), now


def cmd_check(a):
    cfg = read_config(a.config)
    p = market.from_config(cfg)
    opts = _opts(a, cfg)
    sym = market.base_symbol(p, a.symbol)
    chart, now = _load(a, sym, parse_now(a.now, p=p) if a.now else None, p=p)
    res = evaluate(chart, now, **opts)
    if a.write:
        write_json(a.write, entry_doc(res, now))
    if a.json:
        print(json.dumps(public(res), indent=2))
    else:
        for line in describe(res):
            print(line)
        if a.write:
            print("Wrote %s (status %s)." % (a.write, res["status"]))
    return 0 if res["status"] == "triggered" else 1


def cmd_watch(a):
    cfg = read_config(a.config)
    p = market.from_config(cfg)
    opts = _opts(a, cfg)
    sym = market.base_symbol(p, a.symbol)
    if a.every <= 0:
        raise EntryError("--every must be above 0 seconds")
    start = parse_now(a.now, p=p) if a.now else None
    if a.offline or start is not None:
        if start is None:
            start = _load(a, sym, None, p=p)[1]
        clock = SimClock(start)
        now_fn, sleep_fn = clock.now, clock.sleep
    else:
        now_fn, sleep_fn = utc_now, _sleep
    real_today = market.to_local(p, utc_now()).date()

    def provider(now):
        return get_chart(sym, a.interval, market.to_local(p, now).date(), a.offline, real_today, p=p)

    until = None
    if a.until:
        t = parse_hhmm(a.until, "--until", p=p)
        until = datetime.datetime.combine(market.to_local(p, now_fn()).date(), t)

    def on_trigger(res, now):
        write_json(a.out, entry_doc(res, now))
        print("Wrote %s." % a.out, flush=True)

    def emit(line):
        print(line, flush=True)

    code, _ = watch_loop(provider, now_fn, sleep_fn, emit, opts, every=a.every, until=until,
                         on_trigger=on_trigger)
    return code


def cmd_watchlist(a):
    cfg = read_config(a.config)
    p = market.from_config(cfg)
    delay_min = int(p.get("data_delay_min") or 0)
    opts = _opts(a, cfg)
    if not os.path.exists(a.watchlist):
        raise EntryError("no watchlist at %s: run /trader-scanner first (it writes the hits there)" % a.watchlist)
    try:
        with open(a.watchlist, encoding="utf-8") as fh:
            doc = json.load(fh)
    except ValueError as e:
        raise EntryError("%s is not valid JSON: %s" % (a.watchlist, e))
    hits = [h for h in (doc.get("hits") or []) if isinstance(h, dict) and h.get("symbol")]
    if not hits:
        raise EntryError("no hits in %s: the scanner found nothing to watch" % a.watchlist)
    if a.offline and not os.path.isdir(a.offline):
        raise EntryError("watchlist --offline wants a folder of <TICKER>.json files")
    now = parse_now(a.now, p=p) if a.now else None
    rows = []
    for i, h in enumerate(hits):
        sym = market.base_symbol(p, h["symbol"])
        o = dict(opts)
        if a.setup == "level" and o["level"] is None:
            o["level"] = h.get("level")
        try:
            if a.setup == "level" and o["level"] is None:
                raise EntryError("needs a level: --level PRICE or a \"level\" in the watchlist")
            if i and not a.offline:
                _sleep(PAUSE)
            chart, when = _load(a, sym, now, p=p)
            rows.append((sym, evaluate(chart, when, **o), None))
        except EntryError as e:
            rows.append((sym, None, str(e)))
    if a.json:
        print(json.dumps([{"symbol": s, "result": public(r) if r else None, "error": e} for s, r, e in rows], indent=2))
    else:
        print("%-6s  %-9s  %-8s  %-8s  %-9s  %-9s  %s" % ("SYMBOL", "STATUS", "TIME", "PRICE", "LEVEL", "LAST", "VS LEVEL"))
        for s, r, e in rows:
            if e:
                print("%-6s  error: %s" % (s, e))
                continue
            t = r.get("trigger") or {}
            last = r.get("last") or {}
            status = SHORT.get(r["phase"], r["status"]) if r["status"] != "triggered" else "triggered"
            extra = ("  (data about %d min late)" % delay_min) if (t and delay_min > 0) else ""
            print("%-6s  %-9s  %-8s  %-8s  %-9s  %-9s  %s%s" % (
                s, status[:9], t.get("time") or "-", _px(t["price"], p) if t else "-",
                _px(r["level"], p) if r.get("level") is not None else "-",
                _px(last["close"], p) if last else "-",
                ("%+.2f%%" % last["vs_level_pct"]) if last.get("vs_level_pct") is not None else "-",
                extra))
        n = sum(1 for _, r, _ in rows if r and r["status"] == "triggered")
        print("%d of %d triggered. Pick one, then: entry.py check <TICKER> --write, and /trader-exit." % (n, len(rows)))
        print("Free Yahoo bars, unofficial and can lag. Nothing was placed.")
    return 0 if any(r and r["status"] == "triggered" for _, r, _ in rows) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Entry Timer (trader-entry): watches a setup bar by bar.")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--setup", choices=["orb", "level"], default="orb")
        p.add_argument("--or-minutes", type=int, default=15, help="opening range length (default 15)")
        p.add_argument("--interval", choices=["5m", "1m"], default="5m")
        p.add_argument("--level", type=float, help="the price to close above (--setup level)")
        p.add_argument("--min-volume-x", type=float, help="trigger bar volume vs the range bars' average")
        p.add_argument("--side", default="buy", choices=["buy", "long", "sell", "short"], help="v2: buy only")
        p.add_argument("--now", help='pretend it is this WIB time, e.g. "2026-11-23 09:35"')
        p.add_argument("--offline", metavar="PATH", help="saved Yahoo chart JSON (.json/.json.gz) or a folder")
        p.add_argument("--config", default="trader/config.json")

    p = sub.add_parser("check", help="the setup's status right now")
    p.add_argument("symbol")
    common(p)
    p.add_argument("--write", nargs="?", const="trader/entry.json", metavar="PATH",
                   help="save the result (default trader/entry.json)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("watch", help="poll bar by bar until it triggers or expires")
    p.add_argument("symbol")
    common(p)
    p.add_argument("--every", type=float, default=30, help="seconds between polls while Yahoo is behind")
    p.add_argument("--until", help="stop at this WIB time (HH:MM)")
    p.add_argument("--out", default="trader/entry.json", help="where a trigger is written")
    p = sub.add_parser("watchlist", help="check every hit in trader/watchlist.json")
    common(p)
    p.add_argument("--watchlist", default="trader/watchlist.json")
    p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"check": cmd_check, "watch": cmd_watch, "watchlist": cmd_watchlist}[a.cmd](a)
    except EntryError as e:
        print("entry.py: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("entry.py: stopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
