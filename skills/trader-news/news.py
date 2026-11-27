#!/usr/bin/env python3
"""News monitor for trader-news. Standard library only.

Watches headlines from Indonesian RSS feeds for the IDX stocks you watch or hold and
prints only what is new since the last check, newest first, with how far each
stock has moved today and a flag on anything that touches your tickers.

    python news.py                                   # watchlist + plan + portfolio tickers
    python news.py --tickers BBCA BBRI TLKM
    python news.py --tickers BBCA --all --hours 72   # everything in the last 3 days, seen or not
    python news.py --no-moves                        # skip the price line per ticker

Your tickers, when --tickers is not given: every hit in trader/watchlist.json
(trader-scanner), the symbol in trader/plan.json (trader-exit) and the
positions in trader/portfolio.json.

Sources:
  - RSS feeds listed under "news_feeds" in trader/config.json.
  - The move: Yahoo Finance's chart endpoint (unofficial, can lag), the last
    price against yesterday's close:
    https://query2.finance.yahoo.com/v8/finance/chart/<TICKER>.JK?range=1d&interval=5m

Times print in WIB. State: trader/state/news.json remembers
what you have seen (30 days), so an item shows once. Offline: --offline DIR
reads feed-<slug>.xml and chart-<TICKER>.json from DIR.

Headlines are leads, not facts: open the story before acting, and treat
nothing here as advice.
"""

import argparse
import datetime as _dt
import email.utils
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

_CORE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trader-core"))
if _CORE not in sys.path:
    sys.path.insert(0, _CORE)
import market  # noqa: E402

_IDX = market.load("idx")

CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=5m"
BROWSER_UA = "Mozilla/5.0 (compatible; trader-skill-id/0.1; +https://github.com/Dhkysf/Trader-Skill-ID)"
BACKOFF = 5.0  # seconds to wait before the one retry after a 429
DEFAULT_UNIVERSE = "trader/universe.txt"
KEEP_DAYS = 30
MOVE_PCT = 3.0  # a stock this far from yesterday's close is flagged as moving

KEYWORDS = [
    ("earnings", r"\bearnings\b|\bresults\b|\bEPS\b|\bguidance\b|\bforecast\b"),
    ("analyst", r"\bupgrade[sd]?\b|\bdowngrade[sd]?\b|price target|\boutperform\b|\bunderperform\b"),
    ("legal", r"\blawsuit\b|\bsued\b|\bprobe\b|\binvestigation\b|\bsanctions?\b|\bantitrust\b|\bjudge\b|\bcourt\b"),
    ("deal", r"\bacqui(?:re|res|red|sition)\b|\bmerger\b|\bbuyout\b|\btakeover\b|\bdeal\b"),
    ("capital", r"\bdividend\b|\bbuyback\b|\brepurchase\b|\bstock split\b|\boffering\b"),
    ("people", r"\bCEO\b|\bCFO\b|\bresign|\bsteps down\b|\bappoint"),
    ("risk", r"\brecall\b|\bbankrupt|\bdefault\b|\bdelist|\bhack|\bbreach\b|\boutage\b"),
    ("halt", r"\bhalt(?:s|ed)?\b|\btrading (?:pause|suspen)"),
    ("regulatory", r"\bOJK\b|\bapproval\b|\bapproves\b|\bregulator\b|\bregulatory\b"),
    ("macro", r"\bBI\b|\bCPI\b|\binflation\b|\brate\b|\btariffs?\b|\bfutures\b"),
]


class NewsError(Exception):
    pass


# ---------------------------------------------------------------- inputs

def load_json(path):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def watch_from_files(portfolio="trader/portfolio.json", watchlist="trader/watchlist.json",
                     plan="trader/plan.json"):
    """{ticker: name or None}: the scanner's hits, the planned trade and your holdings."""
    out = {}
    wl = load_json(watchlist) or {}
    for h in wl.get("hits", []):
        sym = h.get("symbol") or h.get("ticker")
        if sym:
            out[sym.upper()] = h.get("name")
    pl = load_json(plan) or {}
    if pl.get("symbol"):
        out.setdefault(pl["symbol"].upper(), pl.get("name"))
    pf = load_json(portfolio) or {}
    for p in pf.get("positions", []):
        sym = p.get("ticker") or p.get("symbol")
        if sym:
            out[sym.upper()] = p.get("name") or out.get(sym.upper())
    return out


def names_from_universe(path=DEFAULT_UNIVERSE):
    """{ticker: company name} from a universe file's 'SYMBOL|Name' lines."""
    out = {}
    if not path or not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for ln in fh:
            s = ln.strip()
            if not s or s.startswith("#") or "|" not in s:
                continue
            sym, name = s.split("|", 1)
            sym = sym.strip().upper()
            if sym.endswith(".JK"):
                sym = sym[:-3]
            name = " ".join(name.split())
            if sym and name:
                out[sym] = name
    return out


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    def __init__(self, offline=None, pause=0.15):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise NewsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip"}
        req = urllib.request.Request(url, headers=headers)
        for attempt in (0, 1):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
                    hdrs = getattr(resp, "headers", None)
                    if hdrs and hdrs.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    return data
            except urllib.error.HTTPError as exc:
                code = exc.code
                try:
                    exc.close()
                except Exception:
                    pass
                if code == 429 and attempt == 0:
                    time.sleep(BACKOFF)
                    self._last = time.time()
                    continue
                raise NewsError("HTTP %s for %s" % (code, url))
            except urllib.error.URLError as exc:
                raise NewsError("could not reach %s: %s" % (url, exc.reason))
            except OSError as exc:
                raise NewsError("could not reach %s: %s" % (url, exc))


def yahoo_symbol(ticker, p=None):
    return market.yahoo_symbol(p or _IDX, ticker)


# ---------------------------------------------------------------- parsing

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el, name):
    for c in el.iter():
        if _local(c.tag) == name:
            return (c.text or "").strip()
    return ""


def parse_time(value):
    """RFC 822 (RSS) or ISO 8601 (Atom) -> aware UTC datetime, or None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        d = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.astimezone(_dt.timezone.utc)


def parse_rss(data, ticker=None, source="RSS"):
    """RSS XML -> items."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError("RSS for %s is not valid XML: %s" % (ticker or source, exc))
    out = []
    for it in root.iter("item"):
        title = _text(it, "title")
        link = _text(it, "link")
        guid = _text(it, "guid") or link
        raw_desc = _text(it, "description") or _text(it, "encoded")
        summary = " ".join(re.sub(r"<[^>]+>", " ", raw_desc).split())
        out.append({"id": "rss:" + guid, "source": source, "kind": "headline",
                    "ticker": ticker, "title": title, "summary": summary,
                    "link": link, "time": parse_time(_text(it, "pubDate"))})
    return out


def parse_chart(data, ticker):
    """Yahoo chart JSON -> {"ticker", "price", "prev_close", "pct", "time"} or raise."""
    try:
        doc = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
        meta = doc["chart"]["result"][0]["meta"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise NewsError("chart for %s is not usable" % ticker)
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if not price or not prev:
        raise NewsError("chart for %s has no price" % ticker)
    when = meta.get("regularMarketTime")
    return {"ticker": ticker, "price": round(float(price), 2), "prev_close": round(float(prev), 2),
            "pct": round((float(price) / float(prev) - 1) * 100, 2),
            "time": _dt.datetime.fromtimestamp(when, _dt.timezone.utc) if when else None}


def collect_moves(fetcher, watch, errors=None, p=None):
    errors = [] if errors is None else errors
    out = []
    for t in sorted(watch):
        name = "chart-%s.json" % t
        try:
            try:
                data = fetcher.get(CHART % ("query2", yahoo_symbol(t, p=p)), name)
            except NewsError as exc:
                if fetcher.offline or not re.search(r"HTTP (429|5\d\d)|could not reach", str(exc)):
                    raise
                data = fetcher.get(CHART % ("query1", yahoo_symbol(t, p=p)), name)
            out.append(parse_chart(data, t))
        except NewsError as exc:
            if not (fetcher.offline and "no file" in str(exc)):
                errors.append("price for %s: %s" % (t, exc))
    return out


def _clean_company_name(name):
    s = " ".join((name or "").split())
    s = re.sub(r"^PT\.?\s+", "", s, flags=re.I)
    s = re.sub(r"(?:\s+\(Persero\))?(?:\s+Tbk\.?)?$", "", s, flags=re.I)
    return s.strip()


def mention_patterns(watch, p=None):
    pats = {}
    for t, name in watch.items():
        alts = [r"\b%s\b" % re.escape(t)]
        clean = _clean_company_name(name)
        if clean and len(clean) >= 4:
            alts.append(r"(?i:\b%s\b)" % re.escape(clean).replace(r"\ ", r"[\s-]+"))
        pats[t] = re.compile("|".join(alts))
    return pats


def tag(items, watch, p=None):
    """Which of your tickers each item touches, and why it matters."""
    pats = mention_patterns(watch, p=p)
    for it in items:
        hay = "%s %s" % (it["title"], it.get("summary") or "")
        touches = {it["ticker"]} if it["ticker"] in watch else set()
        for t, rx in pats.items():
            if rx.search(hay):
                touches.add(t)
        it["touches"] = sorted(touches)
        it["tags"] = [label for label, rx in KEYWORDS if re.search(rx, hay, re.I)]
    return items


def dedupe(items):
    """One item per story: same id, or same link, or same title the same day."""
    seen, out = {}, []
    for it in items:
        keys = [it["id"], it["link"],
                "%s|%s" % (re.sub(r"\W+", " ", it["title"].lower()).strip(),
                           it["time"].date() if it["time"] else "")]
        hit = next((seen[k] for k in keys if k and k in seen), None)
        if hit is not None:
            for t in it.get("touches", []):
                if t not in hit["touches"]:
                    hit["touches"].append(t)
            hit["touches"].sort()
            continue
        for k in keys:
            if k:
                seen[k] = it
        out.append(it)
    return out


def fingerprint(it):
    return hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- the check

def _feed_file(label):
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "rss").lower()).strip("-") or "rss"
    return "feed-%s.xml" % slug


def collect(fetcher, watch, state, errors=None, p=None, feeds=None):
    errors = [] if errors is None else errors
    items = []
    if not feeds:
        errors.append("no news_feeds set in config (copy news_feeds from skills/trader-budget/config.example.json)")
        return items
    for entry in feeds:
        if not isinstance(entry, dict) or not entry.get("url"):
            continue
        label = str(entry.get("label") or entry["url"])
        fname = entry.get("file") or _feed_file(label)
        try:
            items += parse_rss(fetcher.get(entry["url"], fname), None, source=label)
        except NewsError as exc:
            errors.append("feed %s: %s" % (label, exc))
    return items


def select(items, state, now, hours=48, show_all=False):
    """Items within the window; only unseen ones unless show_all."""
    seen = state.setdefault("seen", {})
    cutoff = now - _dt.timedelta(hours=hours)
    ahead = now + _dt.timedelta(minutes=10)  # a pinned --now: nothing from after it
    out = []
    for it in items:
        if it["time"] is not None and (it["time"] < cutoff or it["time"] > ahead):
            continue
        fp = fingerprint(it)
        it["new"] = fp not in seen
        if it["new"] or show_all:
            out.append(it)
    out.sort(key=lambda i: (i["time"] or now), reverse=True)
    return out


def remember(items, state, now):
    seen = state.setdefault("seen", {})
    stamp = now.isoformat()
    for it in items:
        seen.setdefault(fingerprint(it), stamp)
    cutoff = (now - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff}
    state["last_check"] = stamp


def render_moves(moves, move_pct=MOVE_PCT, p=None):
    out = []
    prof = p or _IDX
    tz = prof.get("tz_label", "WIB")
    for m in moves:
        flag = "MOVING" if abs(m["pct"]) >= move_pct else ""
        when = (" at %s %s" % (market.to_local(prof, m["time"]).strftime("%H:%M"), tz)) if m.get("time") else ""
        px = market.money(prof, m["price"])
        prev = market.money(prof, m["prev_close"])
        out.append("%-6s %s %+.2f%% vs yesterday's close %s%s  %s" % (
            m["ticker"], px, m["pct"], prev, when, flag))
    return out


def render(items, errors, now, moves=None, move_pct=MOVE_PCT, p=None):
    prof = p or _IDX
    out = render_moves(moves or [], move_pct, p=prof)
    tz = prof.get("tz_label", "WIB")
    if out:
        out.append("")
    if not items:
        out.append("Nothing new.")
    for it in items:
        when = market.to_local(prof, it["time"]).strftime("%Y-%m-%d %H:%M " + tz) if it["time"] else "time unknown"
        mark = "!" if it.get("important") else " "
        who = ",".join(it["touches"]) or (it["ticker"] or "")
        out.append("%s %s  %-11s %-13s %s" % (mark, when, who, it["source"], it["title"]))
        extra = []
        if it["tags"]:
            extra.append("tags: " + ", ".join(it["tags"]))
        extra.append(it["link"])
        out.append("      " + "  ".join(extra))
    for e in errors:
        out.append("note: %s" % e)
    out.append("Checked %s. Headlines are leads, not facts; open the story before acting. "
               "Not financial advice." % market.to_local(prof, now).strftime("%Y-%m-%d %H:%M " + tz))
    return "\n".join(out) + "\n"


def _json_ready(items):
    out = []
    for it in items:
        d = dict(it)
        d["time"] = it["time"].isoformat() if it["time"] else None
        out.append(d)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tickers", nargs="*", help="default: watchlist + plan + portfolio")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--watchlist", default="trader/watchlist.json")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--state", default="trader/state/news.json")
    ap.add_argument("--hours", type=float, default=48, help="ignore items older than this")
    ap.add_argument("--all", action="store_true", help="show seen items too")
    ap.add_argument("--no-moves", action="store_true", help="skip the price line per ticker")
    ap.add_argument("--move-pct", type=float, default=MOVE_PCT, help="flag a move this big (percent)")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE)
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--now", help="ISO time, for reproducible runs")
    ap.add_argument("--dry-run", action="store_true", help="do not update the state file")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.tickers:
        watch = {t.upper(): None for t in args.tickers}
        known = watch_from_files(args.portfolio, args.watchlist, args.plan)
        watch.update({t: known[t] for t in watch if known.get(t)})
    else:
        watch = watch_from_files(args.portfolio, args.watchlist, args.plan)
    if not watch:
        print("news: no tickers. Pass --tickers, or run /trader-scanner first (it writes "
              "trader/watchlist.json).", file=sys.stderr)
        return 2
    try:
        p = market.from_config(args.config)
    except ValueError as e:
        print("news: %s" % e, file=sys.stderr)
        return 2
    now = parse_time(args.now) if args.now else _dt.datetime.now(_dt.timezone.utc)
    state = load_json(args.state) or {}
    errors = []
    norm_watch = {}
    for k, v in watch.items():
        bk = market.base_symbol(p, k)
        if bk not in norm_watch or (not norm_watch[bk] and v):
            norm_watch[bk] = v
    watch = norm_watch
    uni_names = names_from_universe(args.universe)
    for k in list(watch):
        if not watch[k] and uni_names.get(k):
            watch[k] = uni_names[k]
    cfg = load_json(args.config) or {}
    feeds = cfg.get("news_feeds") if isinstance(cfg.get("news_feeds"), list) else []
    fetcher = Fetcher(offline=args.offline)
    items = collect(fetcher, watch, state, errors=errors, p=p, feeds=feeds)
    items = tag(items, watch, p=p)
    items = [it for it in items if it["touches"]]
    items = dedupe(items)
    shown = select(items, state, now, hours=args.hours, show_all=args.all)
    moves = [] if args.no_moves else collect_moves(fetcher, watch, errors, p=p)
    if args.json:
        mv = [dict(m, time=m["time"].isoformat() if m.get("time") else None,
                   moving=abs(m["pct"]) >= args.move_pct) for m in moves]
        print(json.dumps({"checked": now.isoformat(), "moves": mv, "items": _json_ready(shown),
                          "notes": errors}, indent=2))
    else:
        sys.stdout.write(render(shown, errors, now, moves, args.move_pct, p=p))
    if not args.dry_run:
        remember(items, state, now)
        folder = os.path.dirname(args.state)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(args.state, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.write("\n")
    return 0 if any(i["new"] for i in shown) else 1


if __name__ == "__main__":
    sys.exit(main())
