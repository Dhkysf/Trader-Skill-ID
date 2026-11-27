#!/usr/bin/env python3
"""Time Machine for trader-timemachine. Standard library only.

Replays a planned day trade before you risk any money: 10,000 simulated runs of
the rest of the session from your entry, plus the same rule on every past
session in the data.

    python timemachine.py run                           # trader/plan.json, 10,000 replays, seed 19
    python timemachine.py run --write                   # also save trader/timemachine.json
    python timemachine.py run --until 15:45             # stop each replay at your flat-by time
    python timemachine.py run --seed 7 --replays 20000 --json
    python timemachine.py run --symbol BBCA --date 2026-11-26 --entry 5875 \\
        --stop 5825 --target 5975 --entry-time "09:25 AM"
    python timemachine.py chart                         # ASCII fan chart of the replays
    python timemachine.py chart --from trader/timemachine.json

How the replays work:
  1. Fetch 60 days of 5-minute bars (Yahoo v8 chart, range=60d interval=5m;
     one request). Keep only FULL sessions before the plan's date (Mon-Thu 64
     bars, Fri 52 bars in WIB). Half days, gaps and today are left out.
  2. The pool: for every bar slot of the day, each past session's bar as
     ratios to the previous bar's close: (open, high, low, close) / prev close.
  3. One replay starts at the entry price and walks the rest of the session.
     For each bar i it picks a slot j = i + randint(-window, window), kept in
     the same session, then one past bar from pool[j] (random.choice), and
     scales it to the current price. The stop is checked before the target in
     every bar, so a bar that touches both counts as the stop (the conservative
     call).
  4. Outcomes: "target" or "stop" (whichever was touched first), or "neither"
     when the trade is still open at --until (default 15:50, the close).
     "green" = target first, or above the entry at --until (below for a sell).
     R = the target's R at the target, -1 at the stop, otherwise
     (price at --until - entry) / risk. A gap through the stop still counts
     -1R here; a real fill can be worse.
  5. The price at --until: median and the 5th to 95th percentile of all
     replays (pct(a, q) = sorted a at index int(q * n)). The fan chart uses a
     second run of 2,000 paths with the same seed. The histogram has 24 bins
     between the 1st and 99th percentile.
  6. History: the plan's own rule (an opening-range breakout with the same
     opening range, stop rule and target R) re-run on every one of those past
     full sessions, first close beyond the range = entry, same stop-first rule.

The verdict line looks at the replays that hit one side (target or stop) and
compares the target's share of them, target / (target + stop), with the share
that breaks even at the plan's target R: 1 / (1 + R), so 50 % at 1R and 33 % at
2R. The gap, in percentage points:
  less than 5 points    "Close to a coin flip" (1R) / "Close to break-even" (other R)
  5 to 15 points        "Leans toward the target" / "Leans toward the stop"
  15 points or more     "Strongly toward the target" / "Strongly toward the stop"
Below it: a note when more than 40 % of the replays hit neither (the price at
--until decides those), and the average R when its sign goes against the lean.

5-minute bars only: Yahoo keeps 60 days of 5-min bars but only about 7 days of
1-min bars, too few sessions for a fair pool. The run refuses with a plain
message when there are fewer than 20 full sessions or the entry bar is not in
the data. Same plan, same data and same --seed give the same numbers on any
machine. A simulation built from the stock's own recent bars is not a
prediction: earnings, news and halts can do what the last 60 days never did.

Data: https://query2.finance.yahoo.com/v8/finance/chart/<T>.JK?range=60d&interval=5m
(unofficial and free, can lag; falls back to query1 on 429 or 5xx).
--offline FILE reads a saved chart JSON (.json or .json.gz) instead.
Times are WIB wall-clock; --now "2026-11-23 09:35" pins the clock.
"""

import argparse
import datetime
import gzip
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market  # noqa: E402

UA = "Mozilla/5.0 (compatible; trader-skill-id/0.1; +https://github.com/Dhkysf/Trader-Skill-ID)"
PAUSE = 0.5          # seconds between requests: be polite to free endpoints
BACKOFF = 5.0        # seconds to wait once after a 429
HOSTS = ("query2", "query1")
_IDX = market.load("idx")
INTERVAL = 300       # 5-minute bars, in seconds
MIN_SESSIONS = 20
SAMPLE_PATHS = 160
BAND_PATHS = 2000
BAND_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
HIST_BINS = 24
COIN_FLIP = 0.05     # verdict thresholds, see the docstring
STRONG = 0.15
MANY_NEITHER = 0.40
EPOCH = datetime.datetime(1970, 1, 1)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_SLOT_CACHE = {}


def _tz_label(p=None):
    prof = p or _IDX
    return prof.get("tz_label") or prof.get("timezone") or "WIB"


def _place_label(p=None):
    return _tz_label(p)


def _px(x, p=None):
    return market.price(p or _IDX, x)


def _delay_notice(p=None):
    prof = p or _IDX
    delay = int(prof.get("data_delay_min") or 0)
    if delay > 0:
        return "%s data from Yahoo is about %d minutes late. Check your broker app before acting." % (
            prof.get("exchange", "IDX"), delay)
    return None


def _tick_away(p, x, long):
    return float(market.round_tick(p or _IDX, x, "down" if long else "up"))


def _tick_nearest(p, x):
    return float(market.round_tick(p or _IDX, x, "nearest"))


def slot_map(p, day):
    """Profile-driven session slot map for `day`.

    Mon-Thu and Friday are separate slot maps (IDX Mon-Thu 36 + 28 = 64 bars,
    Friday 30 + 22 = 52 bars because Fri session 1 ends at 11:30 and session 2
    starts at 14:00). Yahoo .JK 5m data has null bars during the lunch break
    and at 15:50/15:55, a closing-auction match bar at 16:00 (very large
    volume), and post-trading bars at 16:05-16:10 - all excluded from the
    slots, the same way scan.py session_bars does.
    """
    prof = p or _IDX
    d = datetime.date.fromisoformat(day) if isinstance(day, str) else day
    wd = market._WEEKDAYS[d.weekday()]
    raw = prof["sessions"].get(wd) or []
    cache_key = tuple(tuple(w) for w in raw)
    if cache_key in _SLOT_CACHE:
        return _SLOT_CACHE[cache_key]
    step_min = INTERVAL // 60
    slots, by_min, by_close, sess_ranges, session_counts, keys = [], {}, {}, [], [], []
    s2_starts = set()
    for s_idx, (o_str, c_str) in enumerate(raw):
        o_t = datetime.time.fromisoformat(o_str)
        c_t = datetime.time.fromisoformat(c_str)
        o_min = o_t.hour * 60 + o_t.minute
        c_min = c_t.hour * 60 + c_t.minute
        if c_min <= o_min:
            c_min += 1440
        start_idx = len(slots)
        if s_idx > 0:
            s2_starts.add(start_idx)
        for m in range(o_min, c_min, step_min):
            idx = len(slots)
            slots.append(m)
            by_min[m] = idx
            by_close[m + step_min] = idx
            if idx == 0:
                keys.append(None)
            elif idx in s2_starts:
                keys.append("s2_open")
            else:
                keys.append((s_idx, m))
        end_idx = len(slots) - 1
        sess_ranges.append((start_idx, end_idx))
        session_counts.append(end_idx - start_idx + 1)
    info = {
        "slots": slots,
        "by_min": by_min,
        "by_close": by_close,
        "sessions": sess_ranges,
        "session_counts": session_counts,
        "s2_starts": frozenset(s2_starts),
        "keys": keys,
        "total": len(slots),
    }
    _SLOT_CACHE[cache_key] = info
    return info


class TMError(Exception):
    pass


# ---------------------------------------------------------------- time

def parse_now(text, p=None):
    """ISO time -> naive UTC. A time without an offset is taken as market local time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    prof = p or _IDX
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TMError('--now wants a time like "2026-11-23 09:35" (%s) or ...Z (UTC)' % _place_label(prof))
    if dt.tzinfo is None:
        return market.local_to_utc(prof, dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def utc_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts))


def parse_clock(text, what, p=None):
    """'10:15 AM', '10:15am', '15:55' or '3:55' (a bare 1 to 8 o'clock means p.m.) -> minutes after midnight."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*(?:([AaPp])\.?\s*[Mm]\.?)?\s*$", str(text or ""))
    if not m:
        raise TMError("%s wants a %s time like 10:15 AM or 15:55, not %r" % (what, _place_label(p), text))
    h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
    if mi > 59 or h > 23 or (ap and not 1 <= h <= 12):
        raise TMError("%s %r is not a clock time" % (what, text))
    if ap == "p" and h != 12:
        h += 12
    elif ap == "a" and h == 12:
        h = 0
    elif not ap and 1 <= h <= 8:
        h += 12
    return h * 60 + mi


def clock12(minutes):
    h, m = divmod(minutes, 60)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def clock24(minutes):
    return "%02d:%02d" % divmod(minutes, 60)


# ---------------------------------------------------------------- data

def chart_url(sym, host="query2", p=None):
    return "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m" % (
        host, urllib.parse.quote(market.yahoo_symbol(p or _IDX, sym)))


def _sleep(seconds):
    time.sleep(seconds)


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_chart(sym, p=None):
    """One request for 60 days of 5-min bars. query2 first, one retry after a 429,
    then query1 on 429 or 5xx."""
    last = None
    for n, host in enumerate(HOSTS):
        if n:
            _sleep(PAUSE)
        for attempt in (0, 1):
            url = chart_url(sym, host, p=p)
            try:
                return _get(url)
            except urllib.error.HTTPError as e:
                last = e.code
                try:
                    e.close()
                except Exception:
                    pass
                if e.code == 429 and attempt == 0:
                    _sleep(BACKOFF)
                    continue
                if e.code == 429 or e.code >= 500:
                    break
                if e.code == 404:
                    raise TMError("Yahoo has no chart for %s (HTTP 404): check the ticker" % sym.upper())
                raise TMError("Yahoo answered HTTP %d for %s" % (e.code, sym.upper()))
            except urllib.error.URLError as e:
                last = "could not reach Yahoo: %s" % e.reason
                break
            except OSError as e:
                last = "could not reach Yahoo: %s" % e
                break
    if last == 429:
        raise TMError("Yahoo is rate limiting (HTTP 429). Wait a minute and run it again.")
    if isinstance(last, int):
        raise TMError("Yahoo answered HTTP %s for %s on both hosts. Try again later." % (last, sym.upper()))
    raise TMError(last)


def read_offline(path, sym, p=None):
    """A saved Yahoo chart file (.json or .json.gz), or a folder holding <SYM>-60d5m.json(.gz)."""
    if os.path.isdir(path):
        candidates = []
        for s in (sym.upper(), market.yahoo_symbol(p or _IDX, sym)):
            for ext in ("json", "json.gz"):
                name = "%s-60d5m.%s" % (s, ext)
                if name not in candidates:
                    candidates.append(name)
        for name in candidates:
            if os.path.exists(os.path.join(path, name)):
                path = os.path.join(path, name)
                break
        else:
            raise TMError("no %s-60d5m.json(.gz) in %s" % (sym.upper(), path))
    if not os.path.exists(path):
        raise TMError("no offline chart file %s" % path)
    opener = gzip.open if path.endswith(".gz") else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    except OSError as e:
        raise TMError("could not read %s: %s" % (path, e))


def chart_result(text, sym):
    try:
        data = json.loads(text)
    except ValueError:
        raise TMError("Yahoo returned something that is not JSON for %s" % sym.upper())
    chart = data.get("chart") if isinstance(data, dict) else None
    if not isinstance(chart, dict):
        raise TMError("Yahoo returned something unexpected for %s" % sym.upper())
    res = chart.get("result")
    if not res:
        err = chart.get("error") or {}
        raise TMError("Yahoo has no data for %s: %s" % (sym.upper(), err.get("description") or "unknown ticker"))
    return res[0]


def prev_day_close(result, plan_date, p=None):
    """Last on-grid non-null close strictly before `plan_date` (includes 16:00 closing auction),
    falling back to meta.previousClose."""
    prof = p or _IDX
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    closes = q.get("close") or []
    prior_day, prior_close = None, None
    for i, ts in enumerate(stamps):
        c = closes[i] if i < len(closes) else None
        if ts is None or c is None or int(ts) % INTERVAL:
            continue
        d = market.to_local(prof, utc_of(int(ts))).date().isoformat()
        if d < plan_date and (prior_day is None or d >= prior_day):
            prior_day = d
            prior_close = float(c)
    if prior_close is not None:
        return prior_close
    pc_meta = (result.get("meta") or {}).get("previousClose")
    return float(pc_meta) if isinstance(pc_meta, (int, float)) else None


def parse_bars(result, now_utc, p=None):
    """Yahoo chart result -> (meta, bars, dropped). Regular-session 5-min bars only,
    oldest first. Dropped: bars with a missing price, bars off the 5-minute grid
    (the live tick, e.g. 10:49:45), bars not complete yet (now < start + 5 min,
    where now is the earlier of --now and the data's own regularMarketTime), and
    bars outside the profile's regular session hours."""
    prof = p or _IDX
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    q = ((result.get("indicators") or {}).get("quote") or [{}])[0] or {}
    cols = [q.get(k) or [] for k in ("open", "high", "low", "close", "volume")]
    as_of = now_utc
    rmt = meta.get("regularMarketTime")
    if isinstance(rmt, (int, float)) and utc_of(rmt) < as_of:
        as_of = utc_of(rmt)
    dropped = {"no_price": 0, "off_grid": 0, "not_complete": 0, "outside_hours": 0}
    bars = {}
    for i, ts in enumerate(stamps):
        o, h, l, c, v = [col[i] if i < len(col) else None for col in cols]
        if ts is None or None in (o, h, l, c):
            dropped["no_price"] += 1
            continue
        ts = int(ts)
        if ts % INTERVAL:
            dropped["off_grid"] += 1
            continue
        start = utc_of(ts)
        local = market.to_local(prof, start)
        slot_idx = slot_map(prof, local.date())["by_min"].get(local.hour * 60 + local.minute)
        if slot_idx is None:
            dropped["outside_hours"] += 1
            continue
        if start + datetime.timedelta(seconds=INTERVAL) > as_of:
            dropped["not_complete"] += 1
            continue
        bars[ts] = {"date": local.date().isoformat(), "slot": slot_idx, "start": local.strftime("%H:%M"),
                    "o": o, "h": h, "l": l, "c": c, "v": v or 0}
    return meta, [bars[t] for t in sorted(bars)], dropped


def split_sessions(bars):
    """{date: {slot: bar}}."""
    days = {}
    for b in bars:
        days.setdefault(b["date"], {})[b["slot"]] = b
    return days


def full_sessions(days, before, p=None):
    """Full sessions strictly before the plan's date, oldest first,
    and the short ones that were left out (half days, gaps)."""
    prof = p or _IDX
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        need = slot_map(prof, d)["total"]
        if need > 0 and len(s) == need:
            full.append((d, [s[i] for i in range(need)]))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, short


# ---------------------------------------------------------------- the simulation (sim.py)

def build_pool(sessions, p=None, plan_date=None):
    """pool[i] = every past session's bar i as (o, h, l, c) / bar i-1's close, in date order.
    Session-2 opening bars are grouped under 's2_open' so the lunch gap is drawn only from
    past first-bars-of-session-2."""
    prof = p or _IDX
    target_sm = slot_map(prof, plan_date or "2026-11-26")
    by_key = {}
    for d, D in sessions:
        d_sm = slot_map(prof, d)
        for i in range(1, d_sm["total"]):
            pc = D[i - 1]["c"]
            if pc <= 0:
                continue
            by_key.setdefault(d_sm["keys"][i], []).append(
                (D[i]["o"] / pc, D[i]["h"] / pc, D[i]["l"] / pc, D[i]["c"] / pc))
    return [[] if k is None else list(by_key.get(k, ())) for k in target_sm["keys"]]


def pct(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def simulate(pool, entry, stop, target, k, last, replays=10000, seed=19, window=2, side="buy",
             slot_info=None, ar_band=None, price_decimals=2):
    """Monte Carlo replays of bars k+1..last. Same draws and order as the reel's sim.py."""
    long = side == "buy"
    risk = (entry - stop) if long else (stop - entry)
    r_target = round(((target - entry) if long else (entry - target)) / risk, 4)

    bounds = [(1, len(pool) - 1)] * len(pool)
    if slot_info:
        for s_start, s_end in slot_info["sessions"]:
            if s_start == 0:
                for idx in range(1, s_end + 1):
                    bounds[idx] = (1, s_end)
            else:
                bounds[s_start] = (s_start, s_start)
                for idx in range(s_start + 1, s_end + 1):
                    bounds[idx] = (s_start + 1, s_end)

    def slot(rng, i):
        lo_s, hi_s = bounds[i]
        return i if (window == 0 or lo_s == hi_s) else min(hi_s, max(lo_s, i + rng.randint(-window, window)))

    ar_low, ar_high = ar_band if ar_band is not None else (None, None)
    ar_hits = 0
    rng = random.Random(seed)
    choice = rng.choice
    outcomes, closes, paths = [], [], []
    for n in range(replays):
        p = entry
        outcome = None
        hit_ar = False
        keep = n < SAMPLE_PATHS
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if ar_band is not None:
                if lo <= ar_low or hi >= ar_high or cl <= ar_low or cl >= ar_high:
                    hit_ar = True
                hi = min(ar_high, max(ar_low, hi))
                lo = min(ar_high, max(ar_low, lo))
                cl = min(ar_high, max(ar_low, cl))
            if outcome is None:
                if long:
                    if lo <= stop:
                        outcome = "stop"        # both inside one bar: count the loss (conservative)
                    elif hi >= target:
                        outcome = "target"
                else:
                    if hi >= stop:
                        outcome = "stop"
                    elif lo <= target:
                        outcome = "target"
            p = cl
            if keep:
                path.append(round(p, price_decimals))
        if hit_ar:
            ar_hits += 1
        outcomes.append(outcome or "close")
        closes.append(p)
        if keep:
            paths.append(path)
    cnt = {x: outcomes.count(x) for x in ("target", "stop", "close")}
    green = sum(1 for o, p in zip(outcomes, closes)
                if o == "target" or (o == "close" and (p > entry if long else p < entry)))
    Rs = [r_target if o == "target" else -1.0 if o == "stop" else ((p - entry) if long else (entry - p)) / risk
          for o, p in zip(outcomes, closes)]
    srt = sorted(closes)
    # percentile bands per bar for the fan chart: a second run of 2,000 paths, same seed
    rng = random.Random(seed)
    choice = rng.choice
    allp = []
    for n in range(BAND_PATHS):
        p = entry
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            p = p * c
            if ar_band is not None:
                p = min(ar_high, max(ar_low, p))
            path.append(p)
        allp.append(path)
    bands = []
    for j in range(last - k + 1):
        col = sorted(pp[j] for pp in allp)
        bands.append([round(pct(col, q), price_decimals) for q in BAND_Q])
    lo_, hi_ = pct(srt, 0.01), pct(srt, 0.99)
    W = (hi_ - lo_) / HIST_BINS
    bins = [0] * HIST_BINS
    for c in srt:
        b = int((c - lo_) / W) if W > 0 else 0
        if 0 <= b < HIST_BINS:
            bins[b] += 1
    out = {
        "replays": replays, "seed": seed, "window": window, "bars_left": last - k,
        "p_target": round(cnt["target"] / replays, 4), "p_stop": round(cnt["stop"] / replays, 4),
        "p_neither": round(cnt["close"] / replays, 4), "p_green": round(green / replays, 4),
        "median_close": round(pct(srt, 0.5), price_decimals), "p5_close": round(pct(srt, 0.05), price_decimals),
        "p95_close": round(pct(srt, 0.95), price_decimals), "avg_R": round(statistics.mean(Rs), 3),
        "r_at_target": r_target, "band_paths": BAND_PATHS, "bands": bands, "sample_paths": paths,
        "hist": {"lo": round(lo_, price_decimals), "hi": round(hi_, price_decimals), "bins": bins},
    }
    if ar_band is not None:
        out["ar_hits"] = ar_hits
    return out


# ---------------------------------------------------------------- stop rules and the history replay

def opening_range(D, n):
    """(high, low) of the first n bars of a session given as {slot: bar} or a list."""
    rows = [D[i] for i in range(n)]
    return max(b["h"] for b in rows), min(b["l"] for b in rows)


def rule_stop(rule, oh, ol, entry, long, p=None):
    r = rule["stop_rule"]
    if r == "or_mid":
        return _tick_away(p, (oh + ol) / 2, long)
    if r in ("or_low", "or_high"):
        return _tick_away(p, ol if long else oh, long)
    frac = rule["stop_pct"] / 100.0
    return _tick_away(p, entry * (1 - frac) if long else entry * (1 + frac), long)


def history_replay(sessions, rule, last, side="buy", p=None, until_min=None):
    """The plan's rule on every past full session: entry = the first bar after the
    opening range to close beyond it (up to the --until bar), then stop first, then
    target, bar by bar, else the close at --until."""
    prof = p or _IDX
    long = side == "buy"
    n = rule["or_minutes"] // 5
    trades = []
    for d, D in sessions:
        if until_min is None:
            d_last = min(last, len(D) - 1)
        else:
            d_slots = slot_map(prof, d)["slots"]
            d_last = next((idx for idx in range(len(D) - 1, -1, -1) if d_slots[idx] + 5 <= until_min), None)
        if d_last is None or d_last < n:
            continue
        oh, ol = opening_range(D, n)
        kk = next((i for i in range(n, d_last + 1) if (D[i]["c"] > oh if long else D[i]["c"] < ol)), None)
        if kk is None:
            continue
        e = _tick_nearest(prof, D[kk]["c"])
        s = rule_stop(rule, oh, ol, e, long, p=prof)
        risk = (e - s) if long else (s - e)
        if risk <= 0:
            continue
        t = _tick_nearest(prof, e + rule["target_r"] * risk if long else e - rule["target_r"] * risk)
        oc = None
        for b in D[kk + 1:d_last + 1]:
            if (b["l"] <= s) if long else (b["h"] >= s):
                oc = "stop"
                break
            if (b["h"] >= t) if long else (b["l"] <= t):
                oc = "target"
                break
        cl = D[d_last]["c"]
        R = ((t - e) if long else (e - t)) / risk if oc == "target" else -1.0 if oc == "stop" else \
            ((cl - e) if long else (e - cl)) / risk
        bar_min = int(D[kk]["start"][:2]) * 60 + int(D[kk]["start"][3:])
        trades.append({"date": d, "time": clock12(bar_min + 5), "entry": e, "stop": s, "target": t,
                       "outcome": oc or "close", "R": round(R, 2)})
    return {
        "sessions": len(sessions), "triggered": len(trades),
        "target": sum(1 for x in trades if x["outcome"] == "target"),
        "stop": sum(1 for x in trades if x["outcome"] == "stop"),
        "close": sum(1 for x in trades if x["outcome"] == "close"),
        "green": sum(1 for x in trades if x["R"] > 0),
        "avg_R": round(statistics.mean(x["R"] for x in trades), 3) if trades else None,
        "rule": rule, "trades": trades,
    }


# ---------------------------------------------------------------- the plan

def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TMError("the plan needs a number for %s, got %r" % (what, v))
    if not x > 0 or math.isinf(x):
        raise TMError("the plan's %s must be a positive price, got %r" % (what, v))
    return x


def load_plan(a, now_utc, p=None):
    """The plan from --plan (trader/plan.json) or from the flags, checked and normalized."""
    prof = p or _IDX
    if a.symbol:
        missing = [f for f in ("entry", "stop", "target", "entry_time") if getattr(a, f) is None]
        if missing:
            raise TMError("with --symbol also give %s" % ", ".join("--" + m.replace("_", "-") for m in missing))
        raw = {"symbol": a.symbol, "side": a.side, "date": a.date or market.to_local(prof, now_utc).date().isoformat(),
               "entry": a.entry, "stop": a.stop, "target": a.target, "entry_time": a.entry_time,
               "setup": a.setup, "opening_range": {"minutes": a.or_minutes}, "stop_rule": a.stop_rule,
               "interval": "5m"}
        raw["market"] = prof["id"]
        if getattr(a, "prev_close", None) is not None:
            raw["prev_close"] = a.prev_close
        src = "flags"
    else:
        if not os.path.exists(a.plan):
            raise TMError("no plan at %s: run /trader-exit first, or pass --symbol --date --entry --stop "
                          "--target --entry-time" % a.plan)
        try:
            with open(a.plan, encoding="utf-8") as fh:
                raw = json.load(fh)
        except ValueError as e:
            raise TMError("%s is not valid JSON: %s" % (a.plan, e))
        if not isinstance(raw, dict):
            raise TMError("%s is not a plan" % a.plan)
        if getattr(a, "prev_close", None) is not None:
            raw = dict(raw, prev_close=a.prev_close)
        src = a.plan
    return normalize_plan(raw, src, p=prof if a.symbol else None)


def normalize_plan(raw, src="flags", p=None):
    """A plan dict (trader/plan.json shape) -> the checked plan the time machine runs."""
    try:
        prof = p or (market.load(raw["market"]) if raw.get("market") else _IDX)
    except ValueError as e:
        raise TMError(str(e))
    sym = market.base_symbol(prof, raw.get("symbol"))
    if not re.match(r"^[A-Z][A-Z0-9.\-]{0,9}$", sym):
        raise TMError("the plan needs a ticker symbol, got %r" % raw.get("symbol"))
    side = str(raw.get("side") or "buy").lower()
    if side not in ("buy", "sell"):
        raise TMError("side must be buy or sell, got %r" % raw.get("side"))
    interval = str(raw.get("interval") or "5m")
    if interval != "5m":
        raise TMError("5-minute bars only (the plan says %s): Yahoo keeps 60 days of 5-min bars but only about "
                      "7 days of 1-min bars, too few sessions for a fair replay pool" % interval)
    try:
        date_d = datetime.date.fromisoformat(str(raw.get("date") or ""))
        date = date_d.isoformat()
    except ValueError:
        raise TMError("the plan needs a date like 2026-10-19, got %r" % raw.get("date"))
    if not market.is_trading_day(prof, date_d):
        ex = prof.get("exchange", "IDX")
        name = (prof.get("holidays") or {}).get(date)
        why = ("%s holiday: %s" % (ex, name)) if name else "weekend"
        raise TMError("%s is not a trading day for %s (%s)" % (date, ex, why))
    sm = slot_map(prof, date)
    if sm["total"] == 0:
        raise TMError("%s is not a trading day for %s" % (date, prof.get("exchange", "market")))
    entry, stop, target = (_num(raw.get(k), k) for k in ("entry", "stop", "target"))
    for fld, val in (("stop", stop), ("target", target)):
        if not market.valid_tick(prof, val):
            raise TMError("the plan's %s %s is not on a valid %s tick (tick size %s)"
                          % (fld, val, prof.get("exchange", "IDX"), market.tick_size(prof, val)))
    long = side == "buy"
    if long and not stop < entry < target:
        raise TMError("a buy needs stop < entry < target (got stop %s, entry %s, target %s)" % (stop, entry, target))
    if not long and not target < entry < stop:
        raise TMError("a sell needs target < entry < stop (got target %s, entry %s, stop %s)" % (target, entry, stop))
    k = None
    open_min = sm["slots"][0]
    if raw.get("entry_time"):
        close_min = parse_clock(raw["entry_time"], "entry_time", p=prof)
        if (close_min - open_min) % 5:
            raise TMError("entry_time %s is not on the 5-minute grid (use the bar's close, e.g. 10:15 AM)"
                          % raw["entry_time"])
        if close_min in sm["by_close"]:
            k = sm["by_close"][close_min]
        else:
            raise TMError("entry_time %s is outside %s session hours on %s"
                          % (raw["entry_time"], prof.get("exchange", "market"), date))
    if raw.get("entry_bar") is not None:
        try:
            kb = int(raw["entry_bar"])
        except (TypeError, ValueError):
            raise TMError("entry_bar must be a bar number, got %r" % raw["entry_bar"])
        if k is not None:
            wall_k = (sm["slots"][k] - open_min) // 5 if 0 <= k < sm["total"] else None
            if kb != k and kb != wall_k:
                raise TMError("the plan disagrees with itself: entry_bar %d but entry_time %s is bar %d"
                              % (kb, raw["entry_time"], k))
        else:
            k = kb
    if k is None:
        raise TMError("the plan needs entry_time (the entry bar's close, e.g. 10:15 AM) or entry_bar")
    if not 0 <= k <= sm["total"] - 2:
        raise TMError("the entry must close between %s and %s to leave bars to replay (got %s)"
                      % (clock12(sm["slots"][0] + 5), clock12(sm["slots"][-2] + 5),
                         clock12(open_min + 5 * (k + 1))))
    orng = raw.get("opening_range") or {}
    or_min = orng.get("minutes", 15) if isinstance(orng, dict) else 15
    try:
        or_min = int(or_min)
    except (TypeError, ValueError):
        raise TMError("opening_range.minutes must be a number")
    if or_min < 5 or or_min % 5 or or_min >= sm["session_counts"][0] * 5:
        raise TMError("opening_range.minutes must be a multiple of 5 (got %s)" % or_min)
    risk = (entry - stop) if long else (stop - entry)
    pdec = max(2, market.price_decimals(prof))
    out = {
        "symbol": sym, "side": side, "date": date, "setup": str(raw.get("setup") or "orb"),
        "entry": entry, "entry_time": clock12(sm["slots"][k] + 5), "entry_bar": k,
        "stop": stop, "target": target, "risk_per_share": round(risk, pdec),
        "target_r": round(((target - entry) if long else (entry - target)) / risk, 2),
        "opening_range": dict(orng, minutes=or_min) if isinstance(orng, dict) else {"minutes": or_min},
        "stop_rule": str(raw.get("stop_rule") or "auto"), "interval": "5m",
        "flat_by": raw.get("flat_by"), "from": src, "market": prof["id"],
    }
    if raw.get("prev_close") is not None:
        out["prev_close"] = _num(raw["prev_close"], "prev_close")
    return out


def resolve_rule(plan, entry_day, p=None):
    """The rule the history replay uses: orb, the plan's opening range, its stop rule
    (or_mid, or_low / or_high, or 'pct' = the plan's stop distance as a percent of
    the entry), and the plan's target R. 'auto' works the stop rule out from the
    plan day's own opening range. None when the setup is not orb."""
    if plan["setup"].lower() != "orb":
        return None
    prof = p or _IDX
    long = plan["side"] == "buy"
    n = plan["opening_range"]["minutes"] // 5
    rule = {"setup": "orb", "or_minutes": plan["opening_range"]["minutes"], "stop_rule": plan["stop_rule"],
            "target_r": plan["target_r"],
            "stop_pct": round(100.0 * plan["risk_per_share"] / plan["entry"], 4)}
    far = "or_low" if long else "or_high"
    if rule["stop_rule"] == "auto":
        rule["stop_rule"] = "pct"
        if all(i in entry_day for i in range(n)):
            oh, ol = opening_range(entry_day, n)
            tol = float(market.price_tol(prof, plan["stop"]))
            if abs(_tick_away(prof, (oh + ol) / 2, long) - plan["stop"]) < tol:
                rule["stop_rule"] = "or_mid"
            elif abs(_tick_away(prof, ol if long else oh, long) - plan["stop"]) < tol:
                rule["stop_rule"] = far
    elif rule["stop_rule"] in ("or_low", "or_high") and rule["stop_rule"] != far:
        rule["stop_rule"] = "pct"
    elif rule["stop_rule"] not in ("or_mid", far):
        rule["stop_rule"] = "pct"
    if rule["stop_rule"] != "pct":
        del rule["stop_pct"]
    return rule


# ---------------------------------------------------------------- the run

def _until12(mc):
    t = mc.get("until") or "15:50"
    return clock12(int(t[:2]) * 60 + int(t[3:]))


def lean(mc):
    """(gap, share, break_even): the target's share of the replays that hit one side,
    minus the share that breaks even at the target's R. None when nothing hit a side."""
    pt, ps = mc["p_target"], mc["p_stop"]
    if pt + ps <= 0:
        return None
    r = mc.get("r_at_target") or 1.0
    share, even = pt / (pt + ps), 1.0 / (1.0 + r)
    return share - even, share, even


def verdict(mc):
    """One line from the numbers, see the docstring for the thresholds."""
    pt, ps = mc["p_target"], mc["p_stop"]
    lv = lean(mc)
    if lv is None:
        return "No replay reached the target or the stop by %s: the price at %s decides every one." % (
            _until12(mc), _until12(mc))
    d, share, even = lv
    r = mc.get("r_at_target") or 1.0
    one_r = abs(r - 1.0) < 0.005
    if abs(d) < COIN_FLIP:
        head = "Close to a coin flip" if one_r else "Close to break-even"
    elif abs(d) < STRONG:
        head = "Leans toward the target" if d > 0 else "Leans toward the stop"
    else:
        head = "Strongly toward the target" if d > 0 else "Strongly toward the stop"
    odds = "target first %.1f %% vs stop first %.1f %%" % (100 * pt, 100 * ps)
    if one_r:
        return "%s: %s." % (head, odds)
    return ("%s: at %gR the target has to come first in %.0f %% of the replays that hit one side; "
            "it did in %.0f %% (%s)." % (head, round(r, 2), 100 * even, 100 * share, odds))


def verdict_notes(mc):
    """The lines printed right below the verdict, so nothing reads as one-sided."""
    notes = []
    pn = mc.get("p_neither", 0)
    if pn > MANY_NEITHER and lean(mc) is not None:
        notes.append("%.1f %% of the replays hit neither by %s; the price at %s decides those."
                     % (100 * pn, _until12(mc), _until12(mc)))
    lv = lean(mc)
    avg = mc.get("avg_R")
    if lv and abs(lv[0]) >= COIN_FLIP and avg is not None and avg != 0 and (avg > 0) != (lv[0] > 0):
        notes.append("Average R is %+.3f all the same: the replays that hit neither pull it the other way." % avg)
    return notes


def time_machine(text, plan, now_utc, replays=10000, seed=19, window=2, until=None, source="yahoo", p=None):
    """Chart JSON text + a normalized plan -> the timemachine.json document."""
    if not 1 <= replays <= 1000000:
        raise TMError("--replays must be between 1 and 1,000,000")
    if not 0 <= window <= 10:
        raise TMError("--window must be between 0 and 10 bars")
    try:
        prof = p or (market.load(plan["market"]) if plan.get("market") else _IDX)
    except ValueError as e:
        raise TMError(str(e))
    sym = plan["symbol"]
    result = chart_result(text, sym)
    meta, bars, dropped = parse_bars(result, now_utc, p=prof)
    msym = str(meta.get("symbol") or "").upper()
    want_sym = market.yahoo_symbol(prof, sym)
    if msym and msym != want_sym:
        raise TMError("the data is for %s but the plan is for %s" % (msym, sym))
    gran = meta.get("dataGranularity")
    if gran and gran != "5m":
        raise TMError("the data has %s bars; the time machine needs 5-minute bars" % gran)
    if not bars:
        raise TMError("no complete 5-minute bars for %s in the data" % sym)
    k = plan["entry_bar"]
    if not market.is_trading_day(prof, datetime.date.fromisoformat(plan["date"])):
        ex = prof.get("exchange", "IDX")
        name = (prof.get("holidays") or {}).get(plan["date"])
        why = ("%s holiday: %s" % (ex, name)) if name else "weekend"
        raise TMError("%s is not a trading day for %s (%s)" % (plan["date"], ex, why))
    sm = slot_map(prof, plan["date"])
    if sm["total"] == 0:
        raise TMError("%s is not a trading day for %s" % (plan["date"], prof.get("exchange", "market")))
    full_end_min = sm["slots"][-1] + 5
    sess_today = market.sessions(prof, datetime.date.fromisoformat(plan["date"]))
    if sess_today:
        end_min = sess_today[-1][1].hour * 60 + sess_today[-1][1].minute
        early = end_min < full_end_min
    else:
        end_min = full_end_min
        early = False
    until_min = end_min if until is None else parse_clock(until, "--until", p=prof)
    if (until_min - sm["slots"][0]) % 5 or until_min > end_min:
        raise TMError("--until must be on the 5-minute grid and no later than %s%s"
                      % (clock12(end_min), " (an early close)" if early else ""))
    if until_min not in sm["by_close"]:
        raise TMError("--until %s is outside %s session hours on %s"
                      % (clock12(until_min), prof.get("exchange", "market"), plan["date"]))
    last = sm["by_close"][until_min]
    if last <= k:
        raise TMError("--until %s leaves nothing to replay after the %s entry" % (clock12(until_min),
                                                                             plan["entry_time"]))
    days = split_sessions(bars)
    entry_day = days.get(plan["date"], {})
    if k not in entry_day:
        reason = ("no bars for that day" if not entry_day else
                  "the data stops at the %s bar" % entry_day[max(entry_day)]["start"])
        raise TMError("the entry is not in the data: no complete %s bar (closing %s) on %s for %s (%s)"
                      % (clock24(sm["slots"][k]), plan["entry_time"], plan["date"], sym, reason))
    eb = entry_day[k]
    warn = []
    cal_note = market.calendar_note(prof, plan["date"]) or market.calendar_note(
        prof, market.to_local(prof, now_utc).date()
    )
    if cal_note:
        warn.append(cal_note)
    tol = float(market.price_tol(prof, plan["entry"])) * 2
    if not eb["l"] - tol <= plan["entry"] <= eb["h"] + tol:
        warn.append("the plan's entry %s is outside that bar's range %s to %s"
                    % (_px(plan["entry"], prof), _px(eb["l"], prof), _px(eb["h"], prof)))
    sessions, short = full_sessions(days, plan["date"], p=prof)
    if len(sessions) < MIN_SESSIONS:
        raise TMError("only %d full session(s) of %s before %s in the data; the time machine needs at least %d"
                      % (len(sessions), sym, plan["date"], MIN_SESSIONS))
    pool = build_pool(sessions, p=prof, plan_date=plan["date"])
    if any(not pool[idx] for idx in range(1, sm["total"])):
        raise TMError("not enough matching sessions to fill every slot for %s" % plan["date"])
    ar_band = None
    ref_close = None
    if prof.get("auto_rejection"):
        ref_close = plan["prev_close"] if plan.get("prev_close") is not None else prev_day_close(
            result, plan["date"], p=prof)
        if ref_close is None:
            raise TMError("cannot compute %s ARA/ARB band without previous close; pass --prev-close"
                          % prof.get("exchange", "IDX"))
        try:
            lo_d, hi_d = market.ar_limits(prof, ref_close, plan["date"])
        except ValueError as e:
            if "no auto_rejection rule" in str(e):
                warn.append("no ARA/ARB rule for %s in markets/%s.json; band not checked" % (plan["date"], prof["id"]))
            else:
                raise TMError(str(e))
        else:
            ar_band = (float(lo_d), float(hi_d))
    mc = simulate(pool, plan["entry"], plan["stop"], plan["target"], k, last, replays, seed, window,
                  plan["side"], slot_info=sm, ar_band=ar_band,
                  price_decimals=max(2, market.price_decimals(prof)))
    mc = dict(mc, until=clock24(until_min), pool_sessions=len(sessions), pool_from=sessions[0][0],
              pool_to=sessions[-1][0],
              band_times=[clock24(sm["slots"][j] + 5) for j in range(k, last + 1)])
    if ar_band is not None:
        mc["ar_band"] = {"low": ar_band[0], "high": ar_band[1], "ref": float(ref_close)}
    rule = resolve_rule(plan, entry_day, p=prof)
    plan_out = {kk: v for kk, v in plan.items() if v is not None}
    if rule:
        plan_out["stop_rule"] = rule["stop_rule"]
        history = history_replay(sessions, rule, last, plan["side"], p=prof, until_min=until_min)
    else:
        history = {"sessions": len(sessions), "triggered": 0, "rule": None, "trades": [],
                   "note": "skipped: the history replay knows the opening-range breakout (orb) only, "
                           "this plan's setup is %r" % plan["setup"]}
    last_bar = bars[-1]
    data_doc = {"symbol": msym or sym, "interval": "5m", "range": "60d",
                "last_bar": "%s %s %s" % (last_bar["date"], last_bar["start"], _tz_label(prof)),
                "dropped": dropped, "short_sessions_left_out": short}
    delay_msg = _delay_notice(prof)
    if delay_msg:
        data_doc["data_delay_min"] = int(prof["data_delay_min"])
        data_doc["delay_notice"] = delay_msg
    return {
        "created_by": "trader-timemachine",
        "created_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source,
        "data": data_doc,
        "plan": plan_out,
        "mc": mc,
        "history": history,
        "verdict": verdict(mc),
        "verdict_notes": verdict_notes(mc),
        "warnings": warn,
        "note": ("A simulation built from %s's own last %d full sessions. It is not a prediction: earnings, "
                 "news and halts can do things those sessions never did. Same seed, same numbers." % (sym, len(sessions))),
    }


# ---------------------------------------------------------------- output

def pc(x):
    return "%.1f %%" % (100.0 * x)


def report(doc):
    p, m, h = doc["plan"], doc["mc"], doc["history"]
    prof = market.load(p["market"]) if p.get("market") else _IDX
    long = p["side"] == "buy"
    until = clock12(int(m["until"][:2]) * 60 + int(m["until"][3:]))
    wd = WEEKDAYS[datetime.date.fromisoformat(p["date"]).weekday()]
    r = p["target_r"]
    lines = [
        "%s %s, %s %s: entry %s at %s (bar %d), stop %s, target %s (%sR, risk %s a share)."
        % (p["symbol"], p["side"], wd, p["date"], _px(p["entry"], prof), p["entry_time"], p["entry_bar"],
           _px(p["stop"], prof), _px(p["target"], prof), ("%g" % r), _px(p["risk_per_share"], prof)),
        "%s replays of the rest of the session, %s to %s (%d five-minute bars), seed %d."
        % ("{:,}".format(m["replays"]), p["entry_time"], until, m["bars_left"], m["seed"]),
        "Each bar is drawn whole from %s's own 5-min bars at the same time of day (+-%d bars) over its last "
        "%d full sessions (%s to %s)." % (p["symbol"], m["window"], m["pool_sessions"], m["pool_from"], m["pool_to"]),
        "",
        "  target first   %s" % pc(m["p_target"]),
        "  stop first     %s" % pc(m["p_stop"]),
        "  neither        %-8s still open at %s" % (pc(m["p_neither"]), until),
        "  green          %-8s target first, or %s the entry at %s" % (pc(m["p_green"]),
                                                                       "above" if long else "below", until),
        "",
        "  Price at %s: median %s, 90 %% of replays between %s and %s."
        % (until, _px(m["median_close"], prof), _px(m["p5_close"], prof), _px(m["p95_close"], prof)),
        "  Average R: %+.3f (R = the %s risk: %sR at the target, -1R at the stop)."
        % (m["avg_R"], _px(p["risk_per_share"], prof), ("+%g" % m["r_at_target"]), ),
    ]
    if m.get("ar_band"):
        ab = m["ar_band"]
        lines.append("  ARA/ARB band: %s to %s (ref %s); hit the ARB/ARA limit in %s of %s runs."
                     % (_px(ab["low"], prof), _px(ab["high"], prof), _px(ab["ref"], prof),
                        "{:,}".format(m.get("ar_hits", 0)), "{:,}".format(m["replays"])))
    lines.append("")
    if h.get("rule"):
        ru = h["rule"]
        stop_words = {"or_mid": "opening-range midpoint", "or_low": "opening-range low",
                      "or_high": "opening-range high"}.get(ru["stop_rule"],
                                                           "%.2f %% from the entry" % ru.get("stop_pct", 0))
        if h["triggered"]:
            lines.append("History: the same rule (%d-min opening range, stop at the %s, %gR target) on each of "
                         "those %d real sessions fired %d times: %d target, %d stop, %d neither. Average R %+.3f."
                         % (ru["or_minutes"], stop_words, ru["target_r"], h["sessions"], h["triggered"],
                            h["target"], h["stop"], h["close"], h["avg_R"]))
        else:
            lines.append("History: the same rule never fired in those %d sessions." % h["sessions"])
    else:
        lines.append("History: " + h.get("note", "skipped."))
    lines += ["", doc["verdict"]] + list(doc.get("verdict_notes") or []) + [""]
    for w in doc.get("warnings") or []:
        lines.append("Note: " + (w if w.endswith(".") else w + "."))
    if doc["data"]["short_sessions_left_out"]:
        lines.append("Left out %d short session(s) (half days or gaps): %s."
                     % (len(doc["data"]["short_sessions_left_out"]),
                        ", ".join(x["date"] for x in doc["data"]["short_sessions_left_out"])))
    if doc.get("data", {}).get("delay_notice"):
        lines.append(doc["data"]["delay_notice"])
    lines.append("Fewer than %d full sessions means no verdict." % MIN_SESSIONS)
    lines.append(doc["note"] + " Repeat this run with --seed %d." % m["seed"])
    return lines


def render_chart(doc, height=17):
    """ASCII fan chart of the bands: one column per 5-min bar."""
    p, m = doc["plan"], doc["mc"]
    prof = market.load(p["market"]) if p.get("market") else _IDX
    dec = max(2, market.price_decimals(prof))
    bands, times = m["bands"], m["band_times"]
    lo = min([b[0] for b in bands] + [p["stop"], p["target"]])
    hi = max([b[4] for b in bands] + [p["stop"], p["target"]])
    pad = (hi - lo) * 0.04 or float(market.price_tol(prof, hi)) * 2
    lo, hi = lo - pad, hi + pad
    step = (hi - lo) / (height - 1)

    def row(price):
        return max(0, min(height - 1, int(round((hi - price) / step))))
    grid = [[" "] * len(bands) for _ in range(height)]
    for j, b in enumerate(bands):
        r5, r25, r50, r75, r95 = [row(x) for x in b]
        for r in range(r95, r5 + 1):
            grid[r][j] = "."
        for r in range(r75, r25 + 1):
            grid[r][j] = ":"
        grid[r50][j] = "*"
    marks = {row(p["target"]): "target", row(p["stop"]): "stop"}
    if row(p["entry"]) not in marks:
        marks[row(p["entry"])] = "entry"
    for r in (row(p["target"]), row(p["stop"])):
        grid[r] = ["-" if ch == " " else ch for ch in grid[r]]
    out = ["%s %s, %s replay paths from the %s entry (seed %d)" % (
        p["symbol"], p["date"], "{:,}".format(m.get("band_paths", BAND_PATHS)), p["entry_time"], m["seed"])]
    fmt = "%%9.%df |" % dec
    for r in range(height):
        label = marks.get(r)
        price = {"target": p["target"], "stop": p["stop"], "entry": p["entry"]}.get(label, hi - r * step)
        left = (fmt % price) if (label or r in (0, height - 1)) else "          |"
        out.append(left + "".join(grid[r]) + ("  " + label if label else ""))
    axis = [" "] * len(bands)
    for j in sorted({0, len(bands) // 2, len(bands) - 1}):
        t = times[j]
        hh, mm = int(t[:2]), t[3:]
        lab = "%d:%s" % (hh % 12 or 12, mm)
        s = max(0, min(j, len(bands) - len(lab)))
        axis[s:s + len(lab)] = list(lab)
    out.append("          +" + "-" * len(bands))
    out.append("           " + "".join(axis))
    out.append("* median   : middle half of the paths   . 90 % of the paths   - stop and target")
    return out


# ---------------------------------------------------------------- commands

def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def compute(a):
    prof = None
    if not a.symbol and a.plan and os.path.exists(a.plan):
        try:
            with open(a.plan, encoding="utf-8") as fh:
                raw_plan = json.load(fh)
            if isinstance(raw_plan, dict) and raw_plan.get("market"):
                prof = market.load(raw_plan["market"])
        except (OSError, ValueError):
            pass
    if prof is None:
        try:
            prof = market.from_config(getattr(a, "config", None))
        except ValueError as e:
            raise TMError(str(e))
    now = parse_now(a.now, p=prof)
    plan = load_plan(a, now, p=prof)
    if a.offline:
        text, source = read_offline(a.offline, plan["symbol"], p=prof), "offline"
    else:
        text, source = fetch_chart(plan["symbol"], p=prof), "yahoo"
    return time_machine(text, plan, now, a.replays, a.seed, a.window, a.until, source, p=prof)


def cmd_run(a):
    doc = compute(a)
    if a.write:
        _write(a.write, doc)
    if a.json:
        slim = dict(doc, mc={k: v for k, v in doc["mc"].items() if k != "sample_paths"})
        print(json.dumps(slim, indent=2))
    else:
        print("\n".join(report(doc)))
        if a.write:
            print("Wrote %s." % a.write)
        print("Next: /trader-budget sizes it to your budget and your max loss per trade.")
    return 0


def cmd_chart(a):
    if a.from_file:
        if not os.path.exists(a.from_file):
            raise TMError("no %s: run timemachine.py run --write first" % a.from_file)
        try:
            with open(a.from_file, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["mc"]["bands"]
        except (ValueError, KeyError, TypeError):
            raise TMError("%s is not a time machine result" % a.from_file)
    else:
        doc = compute(a)
    print("\n".join(render_chart(doc)))
    print("\n".join([doc.get("verdict", "")] + list(doc.get("verdict_notes") or [])))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Time Machine: replay a planned day trade (trader-timemachine).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--plan", default="trader/plan.json", help="the plan from trader-exit")
        p.add_argument("--symbol", help="or give the plan as flags: ticker")
        p.add_argument("--side", default="buy", choices=["buy", "sell"])
        p.add_argument("--date", help="the plan's day, YYYY-MM-DD (default today, WIB)")
        p.add_argument("--entry", type=float)
        p.add_argument("--stop", type=float)
        p.add_argument("--target", type=float)
        p.add_argument("--entry-time", help='the entry bar\'s close, e.g. "10:15 AM"')
        p.add_argument("--setup", default="orb")
        p.add_argument("--or-minutes", type=int, default=15)
        p.add_argument("--stop-rule", default="auto", choices=["auto", "or_mid", "or_low", "or_high", "pct"])
        p.add_argument("--replays", type=int, default=10000)
        p.add_argument("--seed", type=int, default=19)
        p.add_argument("--window", type=int, default=2, help="draw from the same time of day +- this many bars")
        p.add_argument("--until", help="end each replay at this time (default: market close)")
        p.add_argument("--offline", metavar="FILE", help="a saved Yahoo chart JSON (.json or .json.gz), no network")
        p.add_argument("--now", help='pretend it is this time ("2026-11-23 09:35" WIB, or ISO with Z)')
        p.add_argument("--config", default="trader/config.json", help="config file (default trader/config.json)")
        p.add_argument("--prev-close", type=float, help="previous close for ARA/ARB band (IDX)")

    p = sub.add_parser("run", help="replay the plan: 10,000 simulated sessions plus the history")
    common(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="save the result (default trader/timemachine.json)")
    p = sub.add_parser("chart", help="ASCII fan chart of the replays")
    common(p)
    p.add_argument("--from", dest="from_file", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="draw a saved result instead of running again")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"run": cmd_run, "chart": cmd_chart}[a.cmd](a)
    except TMError as e:
        print("timemachine.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
