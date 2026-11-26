"""Offline IDX parity tests covering every generic behaviour proven by US tests.

Fixtures under tests/fixtures/idx/ were fetched from Yahoo Finance and CNBC Indonesia on 2026-11-27.
"""

import copy
import datetime
import gzip
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from unittest import mock

from _load import FIX, ROOT, load

market = load("trader-core", "market")
scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
tm = load("trader-timemachine", "timemachine")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")
alerts = load("trader-alerts", "alerts")
news = load("trader-news", "news")

IDX_FIX = os.path.join(FIX, "idx")
BBCA_5M = os.path.join(IDX_FIX, "BBCA.JK-5m-60d-2026-11-27.json.gz")
BBRI_5M = os.path.join(IDX_FIX, "BBRI.JK-5m-60d-2026-11-27.json.gz")
GOTO_5M = os.path.join(IDX_FIX, "GOTO.JK-5m-60d-2026-11-27.json.gz")
TLKM_5M = os.path.join(IDX_FIX, "TLKM.JK-5m-60d-2026-11-27.json.gz")
SPARK_DAILY = os.path.join(IDX_FIX, "spark-daily-2026-11-27.json.gz")
BBCA_PLAN = os.path.join(IDX_FIX, "plan-bbca.json")
CNBC_XML = os.path.join(IDX_FIX, "feed-cnbc-indonesia-market.xml")

DT = datetime.datetime
D = datetime.date


def _read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


def _ts_wib(idx, text):
    dt = DT.strptime(text, "%Y-%m-%d %H:%M:%S" if text.count(":") == 2 else "%Y-%m-%d %H:%M")
    utc = market.local_to_utc(idx, dt)
    return int((utc - DT(1970, 1, 1)).total_seconds())


def _run_mod(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class IdxScannerParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx"}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clock_label_and_bad_time_inputs(self):
        self.assertEqual(scan.clock_label(DT(2026, 11, 23, 9, 15)), "9:15 AM")
        self.assertEqual(scan.clock_label(datetime.time(13, 30)), "1:30 PM")
        self.assertEqual(scan._parse_now_in("2026-11-23 09:35", self.idx), DT(2026, 11, 23, 2, 35))
        self.assertEqual(scan._parse_now_in("2026-11-23T02:35:00Z", self.idx), DT(2026, 11, 23, 2, 35))
        with self.assertRaises(scan.ScanError):
            scan._parse_now_in("tomorrow", self.idx)
        with self.assertRaises(scan.ScanError):
            scan.parse_hhmm("25:00")

    def test_parse_spark_and_in_progress_daily_close(self):
        text = _read_gz(SPARK_DAILY)
        wanted = {scan.to_yahoo(s, self.idx): s for s in ["BBCA", "BBRI", "ZZZZ"]}
        data = scan.parse_spark(text, wanted, p=self.idx)
        self.assertEqual(len(data), 4)
        self.assertNotIn("ZZZZ", data)
        self.assertIn("BBCA", data)
        closes_before = scan.daily_closes(data["BBCA"], scan._parse_now_in("2026-11-25 15:49", self.idx), p=self.idx)
        self.assertEqual(closes_before[-1], (D(2026, 11, 24), 5800.0))
        closes_after = scan.daily_closes(data["BBCA"], scan._parse_now_in("2026-11-25 15:50", self.idx), p=self.idx)
        self.assertEqual(closes_after[-1], (D(2026, 11, 25), 5825.0))

    def test_spark_errors_and_urls(self):
        too_many = '{"spark":{"result":null,"error":{"code":"Bad Request","description":"Number of symbols needs to be less than or equal to 20"}}}'
        with self.assertRaises(scan.ScanError):
            scan.parse_spark(too_many)
        self.assertEqual(scan.parse_spark('{"spark":{"result":[],"error":null}}'), {})
        with self.assertRaises(scan.ScanError):
            scan.parse_spark('{"chart":{}}')
        self.assertEqual(scan.spark_path(["bbca", "tlkm"], "3mo", "1d", p=self.idx),
                         "/v7/finance/spark?symbols=BBCA.JK,TLKM.JK&range=3mo&interval=1d")
        self.assertEqual(scan.chart_path("bbca", "1d", "5m", p=self.idx),
                         "/v8/finance/chart/BBCA.JK?range=1d&interval=5m")

    def test_network_429_5xx_404_and_partial(self):
        body = _read_gz(SPARK_DAILY)
        calls, sleeps = [], []
        old_get, old_sleep = scan.http_get, scan.SLEEP
        try:
            def make_fake(codes):
                seq = list(codes)
                def fake(url, timeout=20):
                    calls.append(url.split("/v")[0])
                    code = seq.pop(0) if seq else 200
                    if code != 200:
                        raise urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b""))
                    return body
                return fake

            scan.SLEEP = sleeps.append
            scan.http_get = make_fake([429, 429, 200])
            self.assertEqual(scan.yahoo_get("/v7/finance/spark?symbols=BBCA.JK&range=3mo&interval=1d"), body)
            self.assertEqual(calls, ["https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com",
                                     "https://query2.finance.yahoo.com"])
            self.assertEqual(sleeps, [scan.BACKOFF])

            calls.clear()
            sleeps.clear()
            scan.http_get = make_fake([503, 200])
            scan.yahoo_get("/v8/finance/chart/BBCA.JK?range=1d&interval=5m")
            self.assertEqual(len(calls), 2)
            self.assertEqual(sleeps, [])

            calls.clear()
            scan.http_get = make_fake([404])
            with self.assertRaises(scan.ScanError):
                scan.yahoo_get("/v8/finance/chart/ZZZZ.JK?range=1d&interval=5m")
            self.assertEqual(len(calls), 1)

            sleeps.clear()
            scan.http_get = make_fake([200] + [429] * 10)
            syms = ["BBCA", "BBRI", "TLKM", "GOTO", "ZZZZ"] + ["X%02d" % i for i in range(20)]
            data, failed = scan.fetch_spark(syms, "3mo", "1d", 0.3, p=self.idx)
            self.assertEqual(len(data), 4)
            self.assertEqual(failed["ZZZZ"], "no data from Yahoo")
            self.assertIn("HTTP 429", failed["X15"])
            self.assertEqual(sleeps, [0.3, scan.BACKOFF])
        finally:
            scan.http_get, scan.SLEEP = old_get, old_sleep

    def test_daily_setups_and_rsi_math(self):
        data, _ = scan.load_offline(SPARK_DAILY, p=self.idx)
        hits, counts, last = scan.scan_daily(data, sorted(data), scan._parse_now_in("2026-11-27 08:30", self.idx), 0, 0, p=self.idx)
        self.assertEqual(last, D(2026, 11, 25))
        self.assertEqual({h["symbol"]: h["setups"] for h in hits},
                         {"BBCA": ["breakout_20d", "bull_flag"], "BBRI": ["bull_flag"]})
        self.assertEqual(counts["scanned"], 4)

        # Synthetic reclaim_ma20, oversold, oversold_bounce
        reclaim = [1000.0] * 23 + [950.0, 1005.0]
        oversold = [1000.0 - i * 15.0 for i in range(25)]
        bounce = [1000.0 - i * 15.0 for i in range(24)] + [670.0]
        self.assertIn("reclaim_ma20", scan.find_setups(reclaim)[0])
        self.assertIn("oversold", scan.find_setups(oversold)[0])
        self.assertIn("oversold_bounce", scan.find_setups(bounce)[0])

        self.assertIsNone(scan.rsi([1.0] * 10))
        self.assertEqual(scan.rsi([float(x) for x in range(1, 40)]), 100.0)
        closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        self.assertAlmostEqual(scan.rsi(closes), 70.46, places=1)

    def test_daily_liquidity_and_short_empty_charts(self):
        data, _ = scan.load_offline(SPARK_DAILY, p=self.idx)
        hits, counts, _ = scan.scan_daily(data, sorted(data), scan._parse_now_in("2026-11-27 08:30", self.idx), 100, 0, 5000000000.0, p=self.idx)
        self.assertEqual(counts["illiquid"], 1)  # GOTO at Rp 27
        self.assertNotIn("GOTO", [h["symbol"] for h in hits])

        s = {"t": [_ts_wib(self.idx, "2026-10-%02d 09:00" % d) for d in range(1, 11)],
             "c": [500.0] * 10, "meta": {"regularMarketPrice": 500, "regularMarketVolume": 5000000}}
        hits2, counts2, last2 = scan.scan_daily({"X": s, "E": {"t": [], "c": [], "meta": {}}}, ["X", "E", "GONE"],
                                               scan._parse_now_in("2026-10-20 08:30", self.idx), 100, 0, p=self.idx)
        self.assertEqual(hits2, [])
        self.assertEqual((counts2["fetched"], counts2["short"], counts2["scanned"]), (2, 1, 0))
        self.assertIsNone(last2)

    def test_orb_scan_sorting_price_floor_and_cutoff(self):
        data = {}
        for sym, path in (("BBCA", BBCA_5M), ("BBRI", BBRI_5M), ("TLKM", TLKM_5M), ("GOTO", GOTO_5M)):
            d, _ = scan.load_offline(path, p=self.idx)
            data.update(d)
        day, cutoff = scan.orb_window(scan._parse_now_in("2026-11-23 10:45", self.idx), None, 15, datetime.time(15, 30), p=self.idx)
        hits, counts, _ = scan.scan_orb(data, sorted(data), day, cutoff, 15, 100, 0, p=self.idx)
        self.assertEqual([h["symbol"] for h in hits], ["BBCA", "BBRI", "TLKM"])
        self.assertEqual([h["at"] for h in hits], ["9:35 AM", "10:00 AM", "10:40 AM"])
        self.assertEqual(counts["illiquid"], 1)  # GOTO at Rp 28

        # 09:34 -> 09:30 bar still forming; 09:35 -> triggered
        day0, cut0 = scan.orb_window(scan._parse_now_in("2026-11-23 09:34", self.idx), None, 15, datetime.time(15, 30), p=self.idx)
        self.assertEqual(scan.scan_orb(data, ["BBCA"], day0, cut0, 15, 0, 0, p=self.idx)[0], [])
        day1, cut1 = scan.orb_window(scan._parse_now_in("2026-11-23 09:35", self.idx), None, 15, datetime.time(15, 30), p=self.idx)
        self.assertEqual(scan.scan_orb(data, ["BBCA"], day1, cut1, 15, 0, 0, p=self.idx)[0][0]["at"], "9:35 AM")

    def test_orb_live_tick_missing_bar_and_30m_range(self):
        data, _ = scan.load_offline(BBCA_5M, p=self.idx)
        s = copy.deepcopy(data["BBCA"])
        s["t"].append(_ts_wib(self.idx, "2026-11-23 10:12:30"))
        for k in ("c", "h", "l", "o", "v"):
            if s[k] is not None:
                s[k].append(5550.0)
        bars = scan.session_bars(s, D(2026, 11, 23), DT(2026, 11, 23, 10, 15), p=self.idx)
        self.assertEqual(len(bars), 15)
        self.assertTrue(scan.usable(bars, D(2026, 11, 23), DT(2026, 11, 23, 10, 15), 3, p=self.idx))

        # Missing bar makes chart unusable
        s_miss = copy.deepcopy(data["BBCA"])
        t0910 = _ts_wib(self.idx, "2026-11-23 09:10")
        idx0910 = next(i for i, t in enumerate(s_miss["t"]) if t >= t0910)
        s_miss["c"][idx0910] = None
        bars_miss = scan.session_bars(s_miss, D(2026, 11, 23), DT(2026, 11, 23, 10, 15), p=self.idx)
        self.assertFalse(scan.usable(bars_miss, D(2026, 11, 23), DT(2026, 11, 23, 10, 15), 3, p=self.idx))

        # 30-minute range (6 bars: 09:00 to 09:30)
        day, cut = scan.orb_window(scan._parse_now_in("2026-11-23 10:45", self.idx), None, 30, datetime.time(15, 30), p=self.idx)
        hits, _, _ = scan.scan_orb(data, ["BBCA"], day, cut, 30, 0, 0, p=self.idx)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["at"], "9:35 AM")

    def test_orb_two_stage_confirm_and_cap(self):
        data = {}
        for path in (BBCA_5M, BBRI_5M, TLKM_5M):
            d, _ = scan.load_offline(path, p=self.idx)
            data.update(d)
        spark_like = {k: dict(v, h=None, l=None) for k, v in data.items()}
        day, cut = D(2026, 11, 23), DT(2026, 11, 23, 10, 45)
        for sym, s in data.items():
            bars = scan.session_bars(s, day, cut, p=self.idx)
            if scan.usable(bars, day, cut, 3, p=self.idx) and scan.orb_hit(bars, 3):
                self.assertTrue(scan.orb_candidate(bars, 3), sym)

        asked = []
        def confirm(sym):
            asked.append(sym)
            return data[sym]
        hits, counts, _ = scan.scan_orb(spark_like, sorted(data), day, cut, 15, 0, 0, confirm, max_confirm=1, p=self.idx)
        self.assertEqual((counts["confirmed"], counts["unconfirmed"]), (1, counts["candidates"] - 1))
        self.assertEqual(len(hits), 1)

        def broken(sym):
            raise scan.ScanError("Yahoo answered HTTP 429 for /v8/finance/chart/%s" % sym)
        hits_b, _, failed_b = scan.scan_orb(spark_like, ["BBCA"], day, cut, 15, 0, 0, broken, p=self.idx)
        self.assertEqual(hits_b, [])
        self.assertIn("429", failed_b["BBCA"])

    def test_orb_window_messages_and_cli_errors(self):
        until = datetime.time(15, 30)
        def msg(now, at=None, u=until):
            with self.assertRaises(scan.ScanError) as cm:
                scan.orb_window(scan._parse_now_in(now, self.idx), at, 15, u, p=self.idx)
            return str(cm.exception)
        self.assertIn("weekend", msg("2026-11-21 10:15"))
        self.assertIn("IDX holiday", msg("2026-08-17 10:15"))
        self.assertIn("after 9:20 AM", msg("2026-11-23 09:10"))
        self.assertIn("expired", msg("2026-11-23 15:35"))
        self.assertIn("expired", msg("2026-11-23 11:30", u=datetime.time(11, 0)))
        self.assertIn("closed at 3:50 PM", msg("2026-11-23 16:05"))
        self.assertIn("later than now", msg("2026-11-23 10:00", at=datetime.time(10, 15)))
        self.assertIn("after the 3:50 PM close", msg("2026-11-23 17:00", at=datetime.time(16, 30)))
        with self.assertRaises(scan.ScanError):
            scan.orb_window(scan._parse_now_in("2026-11-23 10:15", self.idx), None, 7, until, p=self.idx)

        wl = os.path.join(self.tmp.name, "wl.json")
        for argv, want in (
            (["orb", "--config", self.cfg, "--offline", BBCA_5M, "--now", "2026-11-21 10:15"], "weekend"),
            (["orb", "--config", self.cfg, "--offline", BBCA_5M, "--now", "2026-11-23 09:10"], "after 9:20 AM"),
            (["orb", "--config", self.cfg, "--offline", BBCA_5M], "--at HH:MM"),
            (["daily", "--config", self.cfg, "--universe", os.path.join(self.tmp.name, "nope.txt")], "scan.py universe"),
            (["daily", "--config", self.cfg, "--offline", os.path.join(self.tmp.name, "missing")], "no offline file"),
        ):
            code, _, err = _run_mod(scan, argv)
            self.assertEqual(code, 1, argv)
            self.assertIn(want, err)
            self.assertNotIn("Traceback", err)

        code, out, _ = _run_mod(scan, ["orb", "--config", self.cfg, "--offline", BBCA_5M, "--now", "2026-11-23 09:25", "--out", wl])
        self.assertEqual(code, 1)
        self.assertIn("No chart closed above its opening-range high", out)
        with open(wl, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["hits"], [])

    def test_cli_end_to_end_folder_lists_and_json(self):
        folder = os.path.join(self.tmp.name, "charts")
        os.makedirs(folder)
        shutil.copy(BBCA_5M, os.path.join(folder, "BBCA.JK.json.gz"))
        shutil.copy(BBRI_5M, os.path.join(folder, "BBRI.JK.json.gz"))
        with open(os.path.join(folder, "ZZZZ.json"), "w", encoding="utf-8") as fh:
            fh.write('{"chart":{"result":null,"error":{"description":"No data found"}}}')

        wl = os.path.join(self.tmp.name, "wl.json")
        code, text, err = _run_mod(scan, ["orb", "--config", self.cfg, "--offline", folder, "--now", "2026-11-23 10:15", "--out", wl])
        self.assertEqual(code, 0, err)
        doc = json.load(open(wl, encoding="utf-8"))
        self.assertEqual((doc["universe"], doc["scanned"], doc["failed"]), (3, 2, 1))
        self.assertEqual([h["symbol"] for h in doc["hits"]], ["BBCA", "BBRI"])

        # --watchlist and --at
        code2, text2, _ = _run_mod(scan, ["orb", "--config", self.cfg, "--offline", folder, "--at", "10:15", "--watchlist", wl, "--json", "--no-write"])
        self.assertEqual(code2, 0)
        self.assertEqual(len(json.loads(text2)["hits"]), 2)

        # symbols_from_file & daily --json
        txt = os.path.join(self.tmp.name, "list.txt")
        with open(txt, "w", encoding="utf-8") as fh:
            fh.write("# idx\nBBCA|Bank Central Asia\nbbri\n\nBBCA\n")
        self.assertEqual(scan.symbols_from_file(txt), ["BBCA", "BBRI", "BBCA"])
        code3, j3, _ = _run_mod(scan, ["daily", "--config", self.cfg, "--offline", SPARK_DAILY, "--now", "2026-11-27 08:30", "--limit", "2", "--json", "--no-write"])
        self.assertIn(code3, (0, 1))
        d3 = json.loads(j3)
        self.assertEqual(d3["universe"], 2)
        self.assertEqual(d3["note"], "A scan is a list of charts that match a rule, not a list of stocks to buy.")


class IdxEntryParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")
        cls.bbca_doc = json.loads(_read_gz(BBCA_5M))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx"}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def _eval(self, text, doc=None, **kw):
        ch = entry.parse_chart(json.dumps(doc or self.bbca_doc), "BBCA")
        return entry.evaluate(ch, entry.parse_now(text, p=self.idx), cfg=kw.pop("cfg", {"market": "idx"}), **kw)

    def test_orb_trigger_forming_and_phases(self):
        self.assertEqual((self._eval("2026-11-23 08:50")["status"], self._eval("2026-11-23 08:50")["phase"]),
                         ("waiting", "pre-open"))
        r_form = self._eval("2026-11-23 09:10")
        self.assertEqual((r_form["status"], r_form["phase"], r_form["opening_range"]["bars"], r_form["opening_range"]["complete"]),
                         ("waiting", "forming", 2, False))
        r_open = self._eval("2026-11-23 09:16")
        self.assertEqual((r_open["status"], r_open["phase"], r_open["opening_range"]["bars"]), ("waiting", "open", 3))
        r_wait = self._eval("2026-11-23 09:32")
        self.assertEqual(r_wait["status"], "waiting")
        self.assertEqual(r_wait["forming"]["bar_start"], "09:30")
        self.assertEqual(self._eval("2026-11-23 09:34:59")["status"], "waiting")
        r_trig = self._eval("2026-11-23 09:35")
        self.assertEqual(r_trig["status"], "triggered")
        self.assertEqual((r_trig["trigger"]["time"], r_trig["trigger"]["bar_start"], r_trig["trigger"]["bar_index"], r_trig["trigger"]["price"]),
                         ("9:35 AM", "09:30", 6, 5550.0))

    def test_live_tick_lag_note_and_after_close(self):
        d = copy.deepcopy(self.bbca_doc)
        r0 = d["chart"]["result"][0]
        t_cut = _ts_wib(self.idx, "2026-11-23 09:45")
        keep = [i for i, t in enumerate(r0["timestamp"]) if t <= t_cut]
        r0["timestamp"] = [r0["timestamp"][i] for i in keep] + [_ts_wib(self.idx, "2026-11-23 09:49:45")]
        q = r0["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep] + [q[k][keep[-1]]]
        r0["meta"]["regularMarketTime"] = _ts_wib(self.idx, "2026-11-23 09:49:45")
        ch = entry.parse_chart(json.dumps(d), "BBCA")
        r1 = entry.evaluate(ch, entry.utc_of(ch["data_time"]), cfg={"market": "idx"})
        self.assertEqual(r1["forming"]["bar_start"], "09:45")
        r2 = entry.evaluate(ch, entry.parse_now("2026-11-23 09:50", p=self.idx), cfg={"market": "idx"})
        self.assertIn("Yahoo's last trade is 09:49:45", r2["lag_note"])
        r3 = entry.evaluate(ch, entry.parse_now("2026-11-23 09:51", p=self.idx), cfg={"market": "idx"})
        self.assertTrue(all(b["t"] % 300 == 0 for b in r3["_bars"]))

        r_close = self._eval("2026-11-23 16:05")
        self.assertEqual((r_close["status"], r_close["phase"]), ("triggered", "after-close"))
        desc = "\n".join(entry.describe(r_close))
        self.assertIn("minutes ago", desc)
        self.assertNotIn("This is the moment", desc)

    def test_volume_level_30m_and_cutoffs(self):
        r_vol = self._eval("2026-11-23 09:35", min_volume_x=3.0)
        self.assertEqual(r_vol["status"], "waiting")
        self.assertIn("under your 3.00x", r_vol["reason"])
        r_lvl = self._eval("2026-11-23 10:00", setup="level", level=5540.0)
        self.assertEqual(r_lvl["trigger"]["time"], "9:35 AM")
        with self.assertRaises(entry.EntryError):
            self._eval("2026-11-23 10:00", setup="level")
        r_30 = self._eval("2026-11-23 10:00", or_minutes=30)
        self.assertEqual(r_30["opening_range"]["bars"], 6)
        r_exp = self._eval("2026-11-23 09:35", cfg={"market": "idx", "no_entries_before": "09:15", "no_entries_after": "09:30"})
        self.assertEqual(r_exp["status"], "expired")

    def test_expiry_and_lag_at_cutoff(self):
        # 2026-11-25 BBCA has no ORB breakout all day
        self.assertEqual(self._eval("2026-11-25 15:29")["status"], "waiting")
        r_exp = self._eval("2026-11-25 15:30")
        self.assertEqual(r_exp["status"], "expired")
        self.assertIn("by 15:30", r_exp["reason"])
        self.assertEqual(self._eval("2026-11-25 16:05")["phase"], "after-close")

        d = copy.deepcopy(self.bbca_doc)
        r0 = d["chart"]["result"][0]
        t_cut = _ts_wib(self.idx, "2026-11-25 10:10")
        keep = [i for i, t in enumerate(r0["timestamp"]) if t <= t_cut]
        r0["timestamp"] = [r0["timestamp"][i] for i in keep]
        q = r0["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep]
        r0["meta"]["regularMarketTime"] = _ts_wib(self.idx, "2026-11-25 10:14:40")
        cfg = {"market": "idx", "no_entries_before": "09:15", "no_entries_after": "10:15"}
        r_lag = self._eval("2026-11-25 10:15:10", doc=d, cfg=cfg)
        self.assertEqual(r_lag["status"], "waiting")
        self.assertIn("lag_note", r_lag)
        self.assertEqual(self._eval("2026-11-25 10:16", doc=d, cfg=cfg)["status"], "expired")

    def test_one_minute_rules_null_bar_and_mismatch(self):
        t0 = _ts_wib(self.idx, "2026-11-23 09:00")
        ts = [t0 + 60 * i for i in range(25)] + [t0 + 60 * 25 + 30]
        closes = [5500.0] * 15 + [5500.0, 5500.0, 5500.0, 5500.0, None, 5500.0, 5525.0, 5525.0, 5550.0, 5550.0, 5550.0]
        highs = [5500.0] * 15 + [5525.0, 5500.0, 5500.0, 5500.0, None, 5500.0, 5525.0, 5525.0, 5550.0, 5550.0, 5550.0]
        lows = [5450.0] * 15 + [5475.0] * 4 + [None] + [5475.0] * 6
        vols = [10000] * 15 + [5000] * 4 + [None] + [5000, 5000, 5000, 30000, 5000, 0]
        doc1m = {"chart": {"result": [{"meta": {"symbol": "BBCA.JK", "regularMarketTime": ts[-1],
                                                "chartPreviousClose": 5450.0, "dataGranularity": "1m"},
                                       "timestamp": ts,
                                       "indicators": {"quote": [{"open": closes, "high": highs, "low": lows,
                                                                 "close": closes, "volume": vols}]}}], "error": None}}
        ch = entry.parse_chart(json.dumps(doc1m), "BBCA")
        r = entry.evaluate(ch, entry.utc_of(ch["data_time"]), interval="1m", cfg={"market": "idx"})
        self.assertEqual((r["trigger"]["time"], r["trigger"]["bar_index"]), ("9:22 AM", 21))
        rv = entry.evaluate(ch, entry.utc_of(ch["data_time"]), interval="1m", min_volume_x=2, cfg={"market": "idx"})
        self.assertEqual((rv["trigger"]["time"], rv["trigger"]["bar_index"]), ("9:24 AM", 23))
        self.assertNotIn(19, [b["slot"] for b in r["_bars"]])

        p1m = os.path.join(self.tmp.name, "bbca1m.json")
        with open(p1m, "w", encoding="utf-8") as fh:
            json.dump(doc1m, fh)
        code, _, err = _run_mod(entry, ["check", "BBCA", "--config", self.cfg, "--offline", p1m])
        self.assertEqual(code, 1)
        self.assertIn("1m bars, not 5m", err)

    def test_bad_inputs_and_calendar_empty_errors(self):
        with self.assertRaises(entry.EntryError):
            self._eval("2026-11-23 09:35", or_minutes=7)
        with self.assertRaises(entry.EntryError):
            self._eval("2026-11-23 09:35", interval="15m")
        with self.assertRaises(entry.EntryError):
            entry.parse_now("tomorrow", p=self.idx)
        with self.assertRaises(entry.EntryError):
            entry.parse_hhmm("25:00", "x", p=self.idx)

        self.assertEqual((self._eval("2026-11-21 10:00")["status"], self._eval("2026-11-21 10:00")["phase"]),
                         ("no-data", "closed"))
        self.assertIn("IDX", self._eval("2026-08-17 10:00")["reason"])
        empty = copy.deepcopy(self.bbca_doc)
        del empty["chart"]["result"][0]["timestamp"]
        empty["chart"]["result"][0]["indicators"] = {"quote": [{}]}
        self.assertEqual((self._eval("2026-11-23 09:35", doc=empty)["status"],
                          self._eval("2026-11-23 09:35", doc=empty)["phase"]), ("no-data", "open"))
        self.assertFalse(self._eval("2028-03-01 10:00")["calendar_known"])
        with self.assertRaises(entry.EntryError):
            entry.parse_chart("<html>", "BBCA")

    def test_network_retry_fallback_404_and_ranges(self):
        body = _read_gz(BBCA_5M)
        calls, sleeps = [], []
        old_open, old_sleep = entry._open_url, entry._sleep
        try:
            def set_answers(*codes):
                seq = list(codes)
                def fake(url, timeout=20):
                    calls.append(url)
                    c = seq.pop(0) if seq else 200
                    if c == 200:
                        return body
                    raise urllib.error.HTTPError(url, c, "x", {}, io.BytesIO(b'{"chart":{"result":null,"error":{"description":"No data found"}}}'))
                entry._open_url = fake

            entry._sleep = sleeps.append
            set_answers(429, 200)
            c = entry.get_chart("BBCA", "5m", D(2026, 11, 23), today=D(2026, 11, 23), p=self.idx)
            self.assertGreater(len(c["bars"]), 10)
            self.assertIn("/BBCA.JK?", calls[0])
            self.assertEqual(sleeps, [entry.BACKOFF])

            calls.clear()
            sleeps.clear()
            set_answers(429, 429, 200)
            entry.get_chart("BBCA", "5m", D(2026, 11, 23), today=D(2026, 11, 23), p=self.idx)
            self.assertIn("query1", calls[2])

            calls.clear()
            sleeps.clear()
            set_answers(503, 200)
            entry.get_chart("BBCA", "5m", D(2026, 11, 23), today=D(2026, 11, 23), p=self.idx)
            self.assertEqual(sleeps, [])

            set_answers(429, 429, 429, 429)
            code, _, err = _run_mod(entry, ["check", "BBCA", "--config", self.cfg, "--now", "2026-11-23 09:35"])
            self.assertEqual(code, 1)
            self.assertIn("HTTP 429", err)

            set_answers(404)
            with self.assertRaises(entry.EntryError):
                entry.get_chart("ZZZZ", "5m", D(2026, 11, 23), today=D(2026, 11, 23), p=self.idx)
        finally:
            entry._open_url, entry._sleep = old_open, old_sleep

        today = D(2026, 11, 23)
        self.assertEqual(entry.chart_range(today, today, "5m"), "1d")
        self.assertEqual(entry.chart_range(D(2026, 11, 20), today, "5m"), "5d")
        self.assertEqual(entry.chart_range(D(2026, 11, 1), today, "5m"), "1mo")
        self.assertEqual(entry.chart_range(D(2026, 10, 10), today, "5m"), "60d")
        with self.assertRaises(entry.EntryError):
            entry.chart_range(D(2026, 11, 1), today, "1m")

    def test_watch_trigger_lag_preopen_and_doze(self):
        base = entry.parse_chart(json.dumps(self.bbca_doc), "BBCA")
        day_bars = [dict(b) for b in base["bars"] if market.to_local(self.idx, entry.utc_of(b["t"])).date().isoformat() == "2026-11-23"]

        def make_provider(lag_until=None, calls=None):
            def provider(now):
                if calls is not None:
                    calls.append(now)
                nts = entry.ts_of(now)
                data_ts = nts - 30 if (lag_until is not None and now < lag_until) else nts
                bars = []
                for b in day_bars:
                    if b["t"] % 300 or b["t"] > data_ts:
                        continue
                    b = dict(b)
                    if b["t"] + 300 > data_ts:
                        b["c"], b["h"] = 5520.0, max(b["h"], 5520.0)
                    bars.append(b)
                if data_ts % 300:
                    bars.append({"t": data_ts, "o": 5520.0, "h": 5520.0, "l": 5520.0, "c": 5520.0, "v": 0})
                return {"symbol": "BBCA.JK", "meta": {}, "bars": bars, "prev_close": base["prev_close"], "data_time": data_ts}
            return provider

        opts = {"setup": "orb", "or_minutes": 15, "interval": "5m", "level": None, "min_volume_x": None, "cfg": {"market": "idx"}}
        with mock.patch.dict(entry.market.load("idx"), {"data_delay_min": 0}):
            calls, lines, fired = [], [], []
            clk = entry.SimClock(entry.parse_now("2026-11-23 09:27", p=self.idx))
            code, _ = entry.watch_loop(make_provider(calls=calls), clk.now, clk.sleep, lines.append, dict(opts),
                                       every=60, on_trigger=lambda r, now: fired.append((r, now)))
            self.assertEqual(code, 0)
            self.assertEqual(fired[0][0]["trigger"]["time"], "9:35 AM")
            self.assertEqual([market.to_local(self.idx, c).strftime("%H:%M:%S") for c in calls], ["09:27:00", "09:30:02", "09:35:02"])

            lag = entry.parse_now("2026-11-23 09:35:30", p=self.idx)
            calls2 = []
            clk2 = entry.SimClock(entry.parse_now("2026-11-23 09:32", p=self.idx))
            code2, _ = entry.watch_loop(make_provider(lag_until=lag, calls=calls2), clk2.now, clk2.sleep, lambda _: None, dict(opts), every=30)
            self.assertEqual(code2, 0)
            self.assertEqual([market.to_local(self.idx, c).strftime("%H:%M:%S") for c in calls2], ["09:32:00", "09:35:02", "09:35:32"])

            lines_pre = []
            clk_pre = entry.SimClock(entry.parse_now("2026-11-23 08:45", p=self.idx))
            entry.watch_loop(make_provider(), clk_pre.now, clk_pre.sleep, lines_pre.append, dict(opts), every=30)
            self.assertIn("not open yet", lines_pre[0])
            self.assertIn("opening range set", "\n".join(lines_pre))

            class Dozing(entry.SimClock):
                naps = 0
                def sleep(self, seconds):
                    entry.SimClock.sleep(self, seconds)
                    self.naps += 1
                    if self.naps == 3:
                        self.t += datetime.timedelta(minutes=17)

            clk_d = Dozing(entry.parse_now("2026-11-23 09:16", p=self.idx))
            calls_d, lines_d = [], []
            code_d, res_d = entry.watch_loop(make_provider(calls=calls_d), clk_d.now, clk_d.sleep, lines_d.append, dict(opts), every=30)
            self.assertEqual(code_d, 0)
            self.assertEqual(res_d["trigger"]["time"], "9:35 AM")

    def test_watch_expiry_until_closed_and_errors(self):
        opts = {"setup": "orb", "or_minutes": 15, "interval": "5m", "level": None, "min_volume_x": None, "cfg": {"market": "idx"}}
        base = entry.parse_chart(json.dumps(self.bbca_doc), "BBCA")
        nov25 = [dict(b) for b in base["bars"] if market.to_local(self.idx, entry.utc_of(b["t"])).date().isoformat() == "2026-11-25"]

        def prov(now):
            nts = entry.ts_of(now)
            return {"symbol": "BBCA.JK", "meta": {}, "bars": [b for b in nov25 if b["t"] + 300 <= nts],
                    "prev_close": base["prev_close"], "data_time": nts}

        with mock.patch.dict(entry.market.load("idx"), {"data_delay_min": 0}):
            clk = entry.SimClock(entry.parse_now("2026-11-25 10:30", p=self.idx))
            lines = []
            code, _ = entry.watch_loop(prov, clk.now, clk.sleep, lines.append, dict(opts), every=300,
                                       until=DT(2026, 11, 25, 11, 0))
            self.assertEqual(code, 1)
            self.assertIn("--until 11:00", lines[-1])

        clk_wk = entry.SimClock(entry.parse_now("2026-11-21 10:00", p=self.idx))
        lines_wk = []
        self.assertEqual(entry.watch_loop(prov, clk_wk.now, clk_wk.sleep, lines_wk.append, dict(opts))[0], 1)
        self.assertIn("weekend", lines_wk[0])

        def broken(now):
            raise entry.EntryError("Yahoo did not answer")
        clk_err = entry.SimClock(entry.parse_now("2026-11-23 10:00", p=self.idx))
        lines_err = []
        self.assertEqual(entry.watch_loop(broken, clk_err.now, clk_err.sleep, lines_err.append, dict(opts))[0], 1)
        self.assertIn("Stopping after 5 failed reads", lines_err[-1])

    def test_cli_check_write_json_offline_and_flags(self):
        out_e = os.path.join(self.tmp.name, "entry.json")
        code, text, _ = _run_mod(entry, ["check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M,
                                         "--now", "2026-11-23 09:35", "--write", out_e])
        self.assertEqual(code, 0)
        self.assertIn("TRIGGERED 9:35 AM", text)
        e = json.load(open(out_e, encoding="utf-8"))
        self.assertEqual((e["status"], e["market"], e["bar_index"], e["price"]), ("triggered", "idx", 6, 5550.0))

        code_w, j_w, _ = _run_mod(entry, ["check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M,
                                          "--now", "2026-11-23 09:32", "--json"])
        self.assertEqual(code_w, 1)
        self.assertNotIn("_bars", json.loads(j_w))

        folder = os.path.join(self.tmp.name, "charts")
        os.makedirs(folder)
        shutil.copy(BBCA_5M, os.path.join(folder, "BBCA.JK.json.gz"))
        self.assertEqual(_run_mod(entry, ["check", "bbca", "--config", self.cfg, "--offline", folder, "--now", "2026-11-23 09:35"])[0], 0)
        self.assertEqual(_run_mod(entry, ["check", "TLKM", "--config", self.cfg, "--offline", BBCA_5M])[0], 1)

        for argv, want in (
            (["check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M, "--side", "short"], "longs only"),
            (["check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M, "--level", "5000"], "--level is for --setup level"),
            (["check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M, "--setup", "level"], "needs --level"),
        ):
            c, _, err = _run_mod(entry, argv)
            self.assertEqual(c, 1)
            self.assertIn(want, err)

    def test_cli_config_watch_and_watchlist(self):
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        try:
            os.makedirs("trader", exist_ok=True)
            with open("trader/config.json", "w", encoding="utf-8") as fh:
                json.dump({"market": "idx", "no_entries_after": "09:30"}, fh)
            c, out, _ = _run_mod(entry, ["check", "BBCA", "--offline", BBCA_5M, "--now", "2026-11-23 09:35"])
            self.assertEqual(c, 1)
            self.assertIn("EXPIRED", out)

            with open("trader/config.json", "w", encoding="utf-8") as fh:
                fh.write("{bad")
            self.assertEqual(_run_mod(entry, ["check", "BBCA", "--offline", BBCA_5M])[0], 1)

            with open("trader/config.json", "w", encoding="utf-8") as fh:
                json.dump({"market": "idx"}, fh)
            c_w, out_w, _ = _run_mod(entry, ["watch", "BBCA", "--offline", BBCA_5M, "--now", "2026-11-23 09:20", "--every", "30"])
            self.assertEqual(c_w, 0)
            self.assertIn("TRIGGERED", out_w)
            self.assertTrue(os.path.exists("trader/entry.json"))

            os.makedirs("charts", exist_ok=True)
            shutil.copy(BBCA_5M, "charts/BBCA.JK.json.gz")
            shutil.copy(BBRI_5M, "charts/BBRI.JK.json.gz")
            with open("trader/watchlist.json", "w", encoding="utf-8") as fh:
                json.dump({"created_by": "trader-scanner", "hits": [
                    {"symbol": "BBCA", "setups": ["orb"]}, {"symbol": "BBRI", "setups": ["orb"]}, {"symbol": "ZZZZ", "setups": ["orb"]}
                ]}, fh)
            c_wl, out_wl, _ = _run_mod(entry, ["watchlist", "--offline", "charts", "--now", "2026-11-23 09:40"])
            self.assertEqual(c_wl, 0)
            self.assertIn("1 of 3 triggered", out_wl)
            self.assertEqual(_run_mod(entry, ["watchlist", "--watchlist", "missing.json"])[0], 1)
        finally:
            os.chdir(cwd)


class IdxExitParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx"}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def _c(self, ep, stop, target="2R", oh=5500, ol=5425, atr=None, n=None):
        sr, sp = exitp.parse_stop(stop)
        tr, tp = exitp.parse_target(target)
        return exitp.compute(ep, sr, sp, tr, tp, oh, ol, atr, n, p=self.idx)

    def test_or_mid_or_low_pct_atr_and_targets(self):
        p1 = self._c(5550, "or-mid", "1R")
        self.assertEqual((p1["stop"], p1["risk"], p1["target"], p1["reward_risk"]),
                         (Decimal("5450"), Decimal("100"), Decimal("5650"), Decimal("1.00")))
        self.assertIn("rounded down", p1["stop_detail"])
        self.assertEqual(self._c(5550, "or-mid")["target"], Decimal("5750"))
        p_raw = self._c(5550.0001, "or-mid", "1R", 5500.0001, 5425.0001)
        self.assertEqual((p_raw["stop"], p_raw["target"]), (Decimal("5450"), Decimal("5650")))
        self.assertEqual(self._c(5550, "or-low")["stop"], Decimal("5425"))
        self.assertEqual(self._c(5550, "pct:1")["stop"], Decimal("5475"))
        self.assertEqual(self._c(5550, "atr:1.5", atr=50.0, n=7)["stop"], Decimal("5475"))
        self.assertEqual(self._c(5550, "or-mid", "1.5R")["target"], Decimal("5700"))
        pt = self._c(5550, "or-mid", "price:5700")
        self.assertEqual((pt["reward_risk"], pt["target_label"]), (Decimal("1.50"), "your price (1.5R)"))

    def test_math_refusals_and_atr_session_bars(self):
        for stop, target, why in (
            ("price:5550", "2R", "at or above the entry"),
            ("price:5600", "2R", "at or above the entry"),
            ("or-mid", "price:5500", "at or below the entry"),
            ("price:5525", "2R", "2 ticks"),
        ):
            with self.assertRaises(exitp.PlanError) as cm:
                self._c(5550, stop, target)
            self.assertIn(why, str(cm.exception))
        for bad in ("mid-ish", "pct:100", "price:0", "atr:-1"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_stop(bad)
        for bad in ("0R", "R", "lots", "price:x"):
            with self.assertRaises(exitp.PlanError):
                exitp.parse_target(bad)
        with self.assertRaises(exitp.PlanError):
            self._c(5550, "or-mid", oh=None, ol=None)
        with self.assertRaises(exitp.PlanError):
            self._c(5550, "or-mid", oh=5425, ol=5500)

        ch = exitp.load_chart("BBCA", "5m", None, BBCA_5M, p=self.idx)
        bars = exitp.session_bars(ch, D(2026, 11, 23), "5m", upto_slot=6, p=self.idx)
        self.assertEqual(len(bars), 7)
        atr, n = exitp.atr_of(bars)
        self.assertEqual((atr, n), (50.0, 7))
        all_bars = exitp.session_bars(ch, D(2026, 11, 23), "5m", p=self.idx)
        self.assertEqual(exitp.atr_of(all_bars)[1], 14)

    def test_cli_end_to_end_show_and_manual_flags(self):
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        try:
            os.makedirs("trader", exist_ok=True)
            shutil.copy(self.cfg, "trader/config.json")
            self.assertEqual(_run_mod(entry, ["check", "BBCA", "--offline", BBCA_5M, "--now", "2026-11-23 09:35", "--write"])[0], 0)
            code, text, err = _run_mod(exitp, ["plan", "--now", "2026-11-23 09:40", "--stop", "or-mid", "--target", "1R", "--write"])
            self.assertEqual(code, 0, err)
            self.assertIn("not a guarantee", text)
            self.assertIn("/trader-timemachine", text)
            self.assertNotIn("pro" + "fit", text.lower())
            self.assertEqual(_run_mod(exitp, ["show", "--now", "2026-11-23 09:45"])[0], 0)
            self.assertIn("not today", _run_mod(exitp, ["show", "--now", "2026-11-24 09:45"])[1])

            code_m, out_m, _ = _run_mod(exitp, ["plan", "--symbol", "bbca", "--entry", "5550", "--or-high", "5500",
                                                "--or-low", "5425", "--time", "09:35", "--entry-bar", "6",
                                                "--date", "2026-11-23", "--target", "1R", "--now", "2026-11-23 09:40", "--json"])
            self.assertEqual(code_m, 0)
            self.assertEqual(json.loads(out_m)["stop"], 5450.0)
            os.remove("trader/plan.json")
            self.assertEqual(_run_mod(exitp, ["show"])[0], 1)
        finally:
            os.chdir(cwd)

    def test_cli_atr_refusals_and_flat_by(self):
        code, out, err = _run_mod(exitp, ["plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5550",
                                          "--stop", "atr:1.5", "--offline", BBCA_5M, "--date", "2026-11-23",
                                          "--time", "09:35", "--entry-bar", "6", "--now", "2026-11-23 09:40", "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["atr_bars"], 7)

        for argv in (
            ["plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5550", "--stop", "atr:1.5",
             "--offline", BBCA_5M, "--date", "2026-11-23", "--time", "09:05", "--entry-bar", "1", "--now", "2026-11-23 09:40"],
            ["plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5550", "--side", "sell", "--now", "2026-11-23 09:40"],
            ["plan", "--config", self.cfg, "--symbol", "BBCA", "--now", "2026-11-23 09:40"],
            ["plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5550", "--or-high", "5500", "--now", "2026-11-23 09:40"],
            ["plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5550", "--stop", "price:5450",
             "--date", "2026-11-20", "--time", "09:35", "--now", "2026-11-20 09:40", "--flat-by", "16:00"],
            ["plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5550", "--stop", "price:5450",
             "--date", "2026-11-23", "--time", "15:50", "--now", "2026-11-23 15:50"],
        ):
            c, _, e = _run_mod(exitp, argv)
            self.assertEqual(c, 1, argv)
            self.assertNotIn("Traceback", e)


class IdxTimeMachineParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")
        cls.bbca_text = _read_gz(BBCA_5M)

    def _plan(self, **kw):
        raw = {
            "symbol": "BBCA", "side": "buy", "date": "2026-11-26", "setup": "orb",
            "entry": 5875.0, "entry_time": "09:25 AM", "interval": "5m",
            "opening_range": {"high": 5850.0, "low": 5800.0, "minutes": 15},
            "stop": 5825.0, "stop_rule": "or_mid", "target": 5975.0, "target_r": 2.0,
            "market": "idx",
        }
        raw.update(kw)
        return tm.normalize_plan(raw)

    def test_mc_fields_bands_history_and_report(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        doc = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=1000, seed=19, p=self.idx)
        m = doc["mc"]
        self.assertEqual((m["replays"], m["seed"], m["window"], m["until"]), (1000, 19, 2, "15:50"))
        self.assertEqual((m["pool_sessions"], m["bars_left"], m["r_at_target"]), (58, 59, 2.0))
        self.assertAlmostEqual(m["p_target"] + m["p_stop"] + m["p_neither"], 1.0, places=6)
        self.assertEqual(m["bands"][0], [5875.0] * 5)
        self.assertEqual(len(m["bands"]), 60)
        self.assertEqual(len(m["band_times"]), 60)
        self.assertTrue(all(p[0] == 5875.0 for p in m["sample_paths"]))
        h = doc["history"]
        self.assertEqual(h["sessions"], 58)
        self.assertEqual(h["triggered"], h["target"] + h["stop"] + h["close"])
        rep = "\n".join(tm.report(doc))
        for w in ("1,000 replays", "seed 19", "58 full sessions", "not a prediction"):
            self.assertIn(w, rep)
        for bad in ("profit", "P&L", "guarantee", "real time", "tick by tick"):
            self.assertNotIn(bad, rep)

    def test_seeds_window_and_replays(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        a = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=500, seed=19, p=self.idx)["mc"]
        b = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=500, seed=7, p=self.idx)["mc"]
        self.assertNotEqual(a["bands"], b["bands"])
        r = random.Random(19)
        self.assertEqual([r.randint(-2, 2) for _ in range(8)], [-2, 2, -2, 2, -1, 1, 0, 2])
        w0 = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=300, seed=19, window=0, p=self.idx)["mc"]
        self.assertNotEqual(w0["bands"], a["bands"])
        with self.assertRaises(tm.TMError):
            tm.time_machine(self.bbca_text, self._plan(), now_u, replays=0, p=self.idx)
        with self.assertRaises(tm.TMError):
            tm.time_machine(self.bbca_text, self._plan(), now_u, window=11, p=self.idx)

    def test_bars_filtering_clock_short_and_min_sessions(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        doc = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=200, seed=19, p=self.idx)
        self.assertNotIn("2026-11-26", [t["date"] for t in doc["history"]["trades"]])
        self.assertIn("Left out 1 short session", "\n".join(tm.report(doc)))

        with self.assertRaises(tm.TMError) as cm:
            tm.time_machine(self.bbca_text, self._plan(), tm.parse_now("2026-11-26 09:20", p=self.idx), replays=50, p=self.idx)
        self.assertIn("not in the data", str(cm.exception))

        # Missing price dropped
        d_hole = json.loads(self.bbca_text)
        d_hole["chart"]["result"][0]["indicators"]["quote"][0]["close"][5] = None
        doc_h = tm.time_machine(json.dumps(d_hole), self._plan(), now_u, replays=100, p=self.idx)
        self.assertEqual(doc_h["data"]["dropped"]["no_price"], doc["data"]["dropped"]["no_price"] + 1)

        # Empty / broken
        with self.assertRaises(tm.TMError):
            tm.time_machine("<html>rate limited</html>", self._plan(), now_u, p=self.idx)

        # Fewer than 20 sessions refused
        d_trim = json.loads(self.bbca_text)
        res = d_trim["chart"]["result"][0]
        cut_ts = _ts_wib(self.idx, "2026-10-30 09:00")
        keep = [i for i, t in enumerate(res["timestamp"]) if t >= cut_ts]
        res["timestamp"] = [res["timestamp"][i] for i in keep]
        q = res["indicators"]["quote"][0]
        for k in q:
            q[k] = [q[k][i] for i in keep]
        with self.assertRaises(tm.TMError) as cm2:
            tm.time_machine(json.dumps(d_trim), self._plan(), now_u, p=self.idx)
        self.assertIn("at least 20", str(cm2.exception))

    def test_plan_checks_and_until(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        with self.assertRaises(tm.TMError):
            tm.time_machine(self.bbca_text, self._plan(symbol="TLKM"), now_u, p=self.idx)
        with self.assertRaises(tm.TMError):
            tm.time_machine(self.bbca_text, self._plan(date="2026-11-27"), now_u, p=self.idx)
        for bad in (
            dict(entry_time="09:27 AM", entry_bar=None),
            dict(entry_time="16:00", entry_bar=None),
            dict(entry_bar=9),
            dict(entry_time=None, entry_bar=None),
            dict(interval="1m"),
            dict(stop=5900.0),
            dict(side="short"),
            dict(symbol=""),
            dict(entry="abc"),
            dict(date="Nov 26"),
            dict(opening_range={"minutes": 7}),
        ):
            with self.assertRaises(tm.TMError):
                self._plan(**bad)

        self.assertEqual(self._plan(entry_time=None, entry_bar=4)["entry_time"], "9:25 AM")
        self.assertEqual(self._plan(entry_bar=None, entry_time="13:35")["entry_bar"], 36)

        doc_u = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=100, until="15:45", p=self.idx)
        self.assertEqual((doc_u["mc"]["until"], doc_u["mc"]["bars_left"]), ("15:45", 58))
        for bad_u in ("09:25 AM", "15:55", "12:30", "15:47", "noon"):
            with self.assertRaises(tm.TMError):
                tm.time_machine(self.bbca_text, self._plan(), now_u, replays=50, until=bad_u, p=self.idx)

    def test_plan_warnings_rules_non_orb_and_sell(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        doc_w = tm.time_machine(self.bbca_text, self._plan(entry=6100.0, stop=6000.0, target=6200.0), now_u, replays=100, p=self.idx)
        self.assertIn("outside that bar's range", doc_w["warnings"][0])
        self.assertEqual(tm._tick_away(self.idx, 5810.0, True), 5800.0)
        self.assertEqual(tm._tick_away(self.idx, 5810.0, False), 5825.0)
        doc_nr = tm.time_machine(self.bbca_text, self._plan(stop_rule=None), now_u, replays=50, p=self.idx)
        self.assertEqual(doc_nr["history"]["rule"]["stop_rule"], "or_mid")
        doc_flag = tm.time_machine(self.bbca_text, self._plan(setup="flag"), now_u, replays=100, p=self.idx)
        self.assertIsNone(doc_flag["history"]["rule"])
        doc_sell = tm.time_machine(self.bbca_text, self._plan(side="sell", stop=5925.0, target=5775.0, stop_rule="or_high"),
                                   now_u, replays=200, p=self.idx)
        self.assertIn("below the entry", "\n".join(tm.report(doc_sell)))

    def test_verdict_thresholds_1r_and_2r(self):
        self.assertTrue(tm.verdict({"p_target": 0.30, "p_stop": 0.26}).startswith("Close to a coin flip"))
        self.assertTrue(tm.verdict({"p_target": 0.40, "p_stop": 0.30}).startswith("Leans toward the target"))
        self.assertTrue(tm.verdict({"p_target": 0.20, "p_stop": 0.30}).startswith("Leans toward the stop"))
        self.assertTrue(tm.verdict({"p_target": 0.60, "p_stop": 0.30}).startswith("Strongly toward the target"))
        mc2 = {"p_target": 0.241, "p_stop": 0.505, "p_neither": 0.254, "r_at_target": 2.0, "avg_R": 0.095}
        self.assertIn("at 2R the target has to come first in 33 %", tm.verdict(mc2))
        self.assertIn("at 1.5R", tm.verdict(dict(mc2, r_at_target=1.5)))

    def test_network_retry_fallback_and_404(self):
        self.assertEqual(tm.chart_url("bbca", p=self.idx),
                         "https://query2.finance.yahoo.com/v8/finance/chart/BBCA.JK?range=60d&interval=5m")
        calls, sleeps = [], []
        old_get, old_sleep = tm._get, tm._sleep
        try:
            def set_answers(codes):
                seq = list(codes)
                def fake(url, timeout=20):
                    calls.append(url.split(".finance")[0].split("//")[1])
                    c = seq.pop(0)
                    if c != 200:
                        raise urllib.error.HTTPError(url, c, "x", {}, io.BytesIO(b""))
                    return self.bbca_text
                tm._get = fake

            tm._sleep = sleeps.append
            set_answers([429, 429, 200])
            self.assertEqual(tm.fetch_chart("BBCA", p=self.idx), self.bbca_text)
            self.assertEqual(calls, ["query2", "query2", "query1"])
            self.assertEqual(sleeps, [tm.BACKOFF, tm.PAUSE])

            calls.clear()
            set_answers([503, 200])
            tm.fetch_chart("BBCA", p=self.idx)
            self.assertEqual(calls, ["query2", "query1"])

            set_answers([404])
            with self.assertRaises(tm.TMError):
                tm.fetch_chart("ZZZZ", p=self.idx)
        finally:
            tm._get, tm._sleep = old_get, old_sleep

    def test_cli_run_json_flags_folder_errors_and_chart(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "cfg.json")
            pl = os.path.join(d, "plan.json")
            out_p = os.path.join(d, "tm.json")
            json.dump({"market": "idx"}, open(cfg, "w", encoding="utf-8"))
            json.dump(self._plan(), open(pl, "w", encoding="utf-8"))

            c1, t1, e1 = _run_mod(tm, ["run", "--plan", pl, "--config", cfg, "--offline", BBCA_5M,
                                       "--now", "2026-11-26 16:00", "--replays", "200", "--write", out_p])
            self.assertEqual(c1, 0, e1)
            self.assertIn("/trader-budget", t1)
            doc = json.load(open(out_p, encoding="utf-8"))
            self.assertEqual((doc["created_by"], doc["source"]), ("trader-timemachine", "offline"))

            c2, t2, _ = _run_mod(tm, ["run", "--plan", pl, "--config", cfg, "--offline", BBCA_5M,
                                      "--now", "2026-11-26 16:00", "--replays", "200", "--json"])
            self.assertEqual(c2, 0)
            self.assertNotIn("sample_paths", json.loads(t2)["mc"])

            c3, t3, _ = _run_mod(tm, ["chart", "--from", out_p])
            self.assertEqual(c3, 0)
            self.assertIn("* median", t3)
            c4, _, e4 = _run_mod(tm, ["run", "--plan", os.path.join(d, "nope.json")])
            self.assertEqual(c4, 1)
            self.assertNotIn("Traceback", e4)


class IdxBudgetParityTest(unittest.TestCase):
    def setUp(self):
        with open(BBCA_PLAN, encoding="utf-8") as fh:
            self.plan = json.load(fh)
        self.cfg = {"market": "idx", "budget": 10000000, "cash_buffer_pct": 10, "max_position_pct": 75,
                    "max_order": 8000000, "min_order": 100000, "max_loss_per_trade": 100000, "min_reward_risk": 1.0}

    def test_config_example_and_limit_order(self):
        with open(os.path.join(ROOT, "skills", "trader-budget", "config.example.json"), encoding="utf-8") as fh:
            ex = json.load(fh)
        self.assertEqual((ex["market"], ex["budget"], ex["broker"]), ("idx", 10000000, "manual"))
        s = size.size_trade(self.plan, self.cfg, limit=9850, today="2026-11-23")
        self.assertEqual(s["risk_per_share"], 150.0)
        o = size.bracket_order(s)
        self.assertEqual((o["type"], o["limit_price"]), ("limit", "9850"))

    def test_sizing_limits_each_cap_can_bind(self):
        self.assertEqual(size.size_trade(self.plan, self.cfg, today="2026-11-23")["bound_by"], "max loss")
        self.assertEqual(size.size_trade(self.plan, dict(self.cfg, max_order=2000000), today="2026-11-23")["bound_by"], "max order")
        self.assertEqual(size.size_trade(self.plan, dict(self.cfg, max_position_pct=20), today="2026-11-23")["bound_by"], "position cap")
        self.assertEqual(size.size_trade(self.plan, self.cfg, cash=2500000, today="2026-11-23")["bound_by"], "cash")

    def test_fresh_stale_prices_and_portfolio_cash(self):
        s_bad = size.size_trade(self.plan, self.cfg, price=10050, today="2026-11-23")
        self.assertIn("under your minimum 1", s_bad["refusal"])
        s_ok = size.size_trade(self.plan, dict(self.cfg, min_reward_risk=0), price=10050, today="2026-11-23")
        self.assertIsNone(s_ok["refusal"])
        self.assertEqual(size.size_trade(self.plan, self.cfg, price=9800, today="2026-11-23")["entry"], 9875.0)

        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "cfg.json")
            pp = os.path.join(d, "prices.json")
            pf = os.path.join(d, "pf.json")
            json.dump(self.cfg, open(cfg_p, "w", encoding="utf-8"))
            json.dump({"as_of": "2026-11-23T02:50:00Z", "prices": {"BBCA": 10050},
                       "detail": {"BBCA": {"time": "2026-11-23T02:50:00Z"}}}, open(pp, "w", encoding="utf-8"))
            json.dump({"cash": 2500000, "positions": []}, open(pf, "w", encoding="utf-8"))
            c1, out1, _ = _run_mod(size, ["--plan", BBCA_PLAN, "--config", cfg_p, "--portfolio", os.path.join(d, "none"),
                                          "--prices", pp, "--now", "2026-11-23 09:55", "--json"])
            self.assertEqual(c1, 1)
            self.assertIn("above the plan's entry", json.loads(out1)["notes"][0])
            c2, out2, _ = _run_mod(size, ["--plan", BBCA_PLAN, "--config", cfg_p, "--portfolio", pf,
                                          "--prices", pp, "--now", "2026-11-23 10:30", "--json"])
            self.assertEqual(c2, 0)
            self.assertEqual(json.loads(out2)["sizing"]["bound_by"], "cash")

    def test_min_order_bad_plans_and_cli_errors(self):
        cheap = dict(self.plan, symbol="GOTO", entry=50.0, stop=45.0, target=60.0)
        s = size.size_trade(cheap, dict(self.cfg, max_loss_per_trade=1000), today="2026-11-23")
        self.assertIn("minimum order", s["refusal"])
        for bad in (
            dict(self.plan, stop=9900.0),
            dict(self.plan, target=9800.0),
            dict(self.plan, target=None),
            dict(self.plan, side="sell"),
            dict(self.plan, symbol=""),
        ):
            with self.assertRaises(size.SizeError):
                size.size_trade(bad, self.cfg, today="2026-11-23")
        with self.assertRaises(size.SizeError):
            size.size_trade(self.plan, dict(self.cfg, blocked=["bbca"]), today="2026-11-23")
        with self.assertRaises(size.SizeError):
            size.size_trade(self.plan, self.cfg, today="2026-11-24")

    def test_weights_mode_caps_drops_and_errors(self):
        w = size.parse_weights({"BBCA": 60, "BBRI": 30, "TLKM": 10})
        r = size.size(w, {"market": "idx", "budget": 10000000, "cash_buffer_pct": 0, "max_position_pct": 40, "min_order": 100000})
        self.assertEqual({p["ticker"]: p["dollars"] for p in r["positions"]}, {"BBCA": 4000000, "BBRI": 4000000, "TLKM": 2000000})
        r_idle = size.size(size.parse_weights({"BBCA": 50, "BBRI": 50}),
                           {"market": "idx", "budget": 10000000, "cash_buffer_pct": 10, "max_position_pct": 25, "min_order": 100000})
        self.assertEqual(r_idle["idle"], 4000000)
        r_blk = size.size(w, {"market": "idx", "budget": 10000000, "blocked": ["tlkm"], "max_position_pct": 100})
        self.assertNotIn("TLKM", [p["ticker"] for p in r_blk["positions"]])
        with self.assertRaises(size.SizeError):
            size.size(w, {"market": "idx", "budget": 10000000, "fractional": False})

    @unittest.expectedFailure  # BUG: size.whole_shares ignores IDX 100-share lot size (skills/trader-budget/size.py:685-706)
    def test_weights_mode_whole_lots_on_idx(self):
        w = size.parse_weights({"BBCA": 50, "BBRI": 50})
        r = size.size(w, {"market": "idx", "budget": 10000000, "cash_buffer_pct": 10, "max_position_pct": 75,
                          "min_order": 100000, "fractional": False}, prices={"BBCA": 5875, "BBRI": 3080})
        for p in r["positions"]:
            self.assertEqual(p["shares"] % 100, 0, p)

    def test_weights_mode_cli(self):
        with tempfile.TemporaryDirectory() as d:
            c = os.path.join(d, "cfg.json")
            t = os.path.join(d, "targets.json")
            json.dump({"market": "idx", "budget": 10000000, "fractional": True}, open(c, "w", encoding="utf-8"))
            json.dump({"BBCA": 60, "BBRI": 40}, open(t, "w", encoding="utf-8"))
            code, out, err = _run_mod(size, ["--targets", t, "--config", c, "--json"])
            self.assertEqual(code, 0, err)
            self.assertEqual([o["symbol"] for o in json.loads(out)["orders"]], ["BBCA", "BBRI"])
            self.assertEqual(_run_mod(size, ["--targets", os.path.join(d, "nope.json"), "--config", c])[0], 1)


class IdxRiskParityTest(unittest.TestCase):
    def setUp(self):
        with open(BBCA_PLAN, encoding="utf-8") as fh:
            self.plan = json.load(fh)
        self.idx = market.load("idx")
        self.cfg = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000,
                    "max_daily_loss": 250000, "max_trades_per_day": 3, "max_orders_per_day": 10,
                    "min_order": 100000, "max_order": 8000000, "min_reward_risk": 1.0}
        self.order = size.bracket_order(size.size_trade(self.plan, self.cfg, today="2026-11-23"))
        self.now = check.parse_now("2026-11-23 10:15", p=self.idx)

    def test_pass_fields_fingerprint_and_cli(self):
        res = check.check([self.order], self.cfg, now=self.now)
        r = res["results"][0]
        self.assertEqual((r["verdict"], r["reasons"], r["warnings"], r["kind"]), ("PASS", [], [], "entry"))
        self.assertEqual(check.fingerprint(self.order), ticket.fingerprint(self.order))
        self.assertNotEqual(check.fingerprint(dict(self.order, qty="500")), check.fingerprint(self.order))

        with tempfile.TemporaryDirectory() as d:
            cp = os.path.join(d, "cfg.json")
            op = os.path.join(d, "orders.json")
            rp = os.path.join(d, "risk.json")
            none = os.path.join(d, "none")
            json.dump(self.cfg, open(cp, "w", encoding="utf-8"))
            json.dump({"orders": [self.order]}, open(op, "w", encoding="utf-8"))
            code, out, err = _run_mod(check, ["--orders", op, "--config", cp, "--portfolio", none,
                                              "--prices", none, "--state", none, "--now", "2026-11-23 10:15", "--out", rp])
            self.assertEqual(code, 0, err)
            self.assertIn("not financial advice", out)
            self.assertEqual(json.load(open(rp, encoding="utf-8"))["results"][0]["fingerprint"], check.fingerprint(self.order))

    def test_stop_target_and_reward_risk_blocks(self):
        no_stop = dict(self.order)
        for k in ("order_class", "take_profit_limit_price", "stop_loss_stop_price"):
            no_stop.pop(k, None)
        self.assertEqual(check.check([no_stop], self.cfg, now=self.now)["results"][0]["verdict"], "PASS")
        self.assertIn("in the plan only", " ".join(check.check([no_stop], self.cfg, now=self.now)["results"][0]["warnings"]))
        no_stop["plan"] = {"entry": 9875.0}
        self.assertEqual(check.check([no_stop], self.cfg, now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([no_stop], dict(self.cfg, require_stop=False, min_reward_risk=0), now=self.now)["results"][0]["verdict"], "PASS")
        self.assertEqual(check.check([dict(self.order, stop_loss_stop_price="9900")], self.cfg, now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([dict(self.order, take_profit_limit_price="9850")], self.cfg, now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([self.order], dict(self.cfg, min_reward_risk=2.0), now=self.now)["results"][0]["verdict"], "BLOCK")

    def test_price_freshness_lower_and_limit_ref(self):
        qt = check.parse_now("2026-11-23 10:10", p=self.idx)
        res_hi = check.check([self.order], self.cfg, prices={"BBCA": 10050.0}, now=self.now, price_times={"BBCA": qt})
        self.assertEqual(res_hi["results"][0]["verdict"], "BLOCK")
        res_stale = check.check([self.order], self.cfg, prices={"BBCA": 10050.0},
                                now=check.parse_now("2026-11-23 10:40", p=self.idx), price_times={"BBCA": qt})
        self.assertEqual(res_stale["results"][0]["verdict"], "PASS")
        self.assertIn("older than 15 minutes", " ".join(res_stale["results"][0]["warnings"]))
        lim = dict(self.order, type="limit", limit_price="9850")
        self.assertEqual(check.check([lim], self.cfg, prices={"BBCA": 10050.0}, now=self.now)["results"][0]["entry_ref"], 9850.0)

    def test_daily_loss_trades_exits_and_batch_limits(self):
        def placed(sym, day="2026-11-23", ml=70000.0, kind="entry", status="placed"):
            return {"symbol": sym, "side": "buy", "status": status, "date": day, "max_loss": ml, "kind": kind}

        st2 = {"orders": [placed("TLKM"), placed("BBRI")]}
        self.assertEqual(check.check([self.order], self.cfg, state=st2, now=self.now)["results"][0]["verdict"], "PASS")
        st3 = {"orders": [placed("TLKM"), placed("BBRI"), placed("ASII")]}
        r3 = check.check([self.order], self.cfg, state=st3, now=self.now)["results"][0]
        self.assertEqual(r3["verdict"], "BLOCK")
        self.assertTrue(any(x.startswith("trades:") for x in r3["reasons"]))

        st_yest = {"orders": [placed("TLKM", day="2026-11-20"), placed("BBRI", day="2026-11-20"), placed("ASII", day="2026-11-20")]}
        self.assertEqual(check.check([self.order], self.cfg, state=st_yest, now=self.now)["results"][0]["verdict"], "PASS")

        batch = [dict(self.order, symbol=s) for s in ("AAAA", "BBBB", "CCCC", "DDDD")]
        res_b = check.check(batch, dict(self.cfg, budget=50000000, max_daily_loss=500000), now=self.now)
        self.assertEqual([r["verdict"] for r in res_b["results"]], ["PASS", "PASS", "PASS", "BLOCK"])

    def test_window_weekend_holiday_and_config_errors(self):
        self.assertEqual(check.check([self.order], self.cfg, now=check.parse_now("2026-11-21 10:15", p=self.idx))["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([self.order], self.cfg, now=check.parse_now("2026-12-25 10:15", p=self.idx))["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([self.order], dict(self.cfg, no_entries_before=None, no_entries_after=None),
                                     now=check.parse_now("2026-11-21 10:15", p=self.idx))["results"][0]["verdict"], "PASS")
        with self.assertRaises((check.RiskError, ValueError)):
            check.check([self.order], dict(self.cfg, no_entries_before="9.15am"), now=self.now)

    def test_exits_partial_short_and_buy_sell_batch(self):
        pf = {"cash": 5000000, "positions": [{"ticker": "BBCA", "shares": 300, "lots": [{"date": "2026-11-23", "shares": 300, "cost": 2962500}]}]}
        sell = {"symbol": "BBCA", "side": "sell", "qty": "300", "type": "market", "time_in_force": "day", "market": "idx"}
        r_ex = check.check([sell], dict(self.cfg, blocked=["BBCA"], max_order=100), portfolio=pf,
                           now=check.parse_now("2026-11-23 15:55", p=self.idx))["results"][0]
        self.assertEqual((r_ex["verdict"], r_ex["kind"]), ("PASS", "exit"))

        part = dict(sell, qty="200")
        res_p = check.check([part, part], self.cfg, portfolio=pf, prices={"BBCA": 9900.0}, now=self.now)
        self.assertEqual([r["verdict"] for r in res_p["results"]], ["PASS", "BLOCK"])

        res_bs = check.check([self.order, sell], self.cfg, now=self.now)
        self.assertEqual([(r["verdict"], r["kind"]) for r in res_bs["results"]], [("PASS", "entry"), ("PASS", "exit")])

    def test_cash_position_duplicate_min_max_blocked_and_live(self):
        self.assertEqual(check.check([self.order], dict(self.cfg, max_order=1000000), now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([self.order], dict(self.cfg, min_order=5000000), now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([self.order], dict(self.cfg, blocked=["BBCA"]), now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertIn("LIVE", check.check([self.order], dict(self.cfg, paper=False), now=self.now)["warnings"][0])

    def test_format_asset_options_and_bracket_blocks(self):
        opt = {"symbol": "BE270617C00100000", "side": "buy", "qty": "100", "type": "limit", "limit_price": "1000", "time_in_force": "day", "market": "idx"}
        self.assertEqual(check.check([opt], dict(self.cfg, require_stop=False, min_reward_risk=0), now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([opt], dict(self.cfg, allow_options=True, require_stop=False, min_reward_risk=0), now=self.now)["results"][0]["verdict"], "PASS")
        cry = dict(opt, symbol="BTC/USD")
        self.assertEqual(check.check([cry], dict(self.cfg, require_stop=False, min_reward_risk=0), now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertEqual(check.check([dict(self.order, time_in_force="ioc")], self.cfg, now=self.now)["results"][0]["verdict"], "BLOCK")
        self.assertIn("as a string", " ".join(check.check([dict(self.order, stop_loss_stop_price=9700)], self.cfg, now=self.now)["results"][0]["warnings"]))

    def test_sell_frees_cash_and_daily_order_limit(self):
        pf = {"cash": 2000000, "positions": [{"ticker": "TLKM", "shares": 1000, "lots": [{"date": "2026-11-23", "shares": 1000, "cost": 2000000}]}]}
        sell_tlkm = {"symbol": "TLKM", "side": "sell", "qty": "1000", "type": "market", "time_in_force": "day", "market": "idx"}
        res = check.check([sell_tlkm, self.order], dict(self.cfg, cash_buffer_pct=0, max_position_pct=100),
                          portfolio=pf, prices={"TLKM": 2100.0}, now=self.now)
        self.assertEqual([r["verdict"] for r in res["results"]], ["PASS", "PASS"])

        st10 = {"orders": [{"symbol": "T%d" % i, "side": "buy", "status": "placed", "date": "2026-11-23"} for i in range(10)]}
        self.assertEqual(check.check([self.order], self.cfg, state=st10, now=self.now)["results"][0]["verdict"], "BLOCK")

    def test_cli_prices_freshness_and_errors(self):
        self.assertEqual(_run_mod(check, ["--orders", "/nonexistent.json", "--no-write"])[0], 1)
        self.assertEqual(_run_mod(check, ["--orders", BBCA_PLAN, "--now", "noon", "--no-write"])[0], 1)


class IdxBrokerParityTest(unittest.TestCase):
    def setUp(self):
        self.idx = market.load("idx")
        with open(BBCA_PLAN, encoding="utf-8") as fh:
            self.plan = json.load(fh)
        self.cfg_dict = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 75000}
        self.order = size.bracket_order(size.size_trade(self.plan, self.cfg_dict, today="2026-11-23"))

    def test_explicit_yes_rules_on_idx(self):
        for r in ("yes", "Yes.", "YES", "y", "yes place it", "yes BBCA", "yes 3 lots", "yes 300 BBCA", "yes 9700", "yes 10200", "yes 64219"):
            self.assertTrue(ticket.parse_yes(r, self.order, ["BBCA", "BBRI"], p=self.idx, cfg=self.cfg_dict)[0], r)
        for r in ("", "sure", "ok", "yeah", "yes to all", "yes both", "yes BBRI", "yes 4 lots", "yes?", "no", "yes, wait"):
            self.assertFalse(ticket.parse_yes(r, self.order, ["BBCA", "BBRI"], p=self.idx, cfg=self.cfg_dict)[0], r)
        sell = {"symbol": "BBCA", "side": "sell", "qty": "300", "type": "market", "time_in_force": "day", "market": "idx"}
        self.assertTrue(ticket.parse_yes("yes sell 300 BBCA", sell, p=self.idx, cfg=self.cfg_dict)[0])
        self.assertFalse(ticket.parse_yes("yes sell 400", sell, p=self.idx, cfg=self.cfg_dict)[0])

    def test_fingerprint_and_plain_limit_order(self):
        self.assertEqual(ticket.fingerprint(self.order), ticket.fingerprint(dict(self.order, why="x", plan={})))
        lim = dict(self.order, type="limit", limit_price="9850")
        self.assertIn("at Rp 9.850", ticket.plain(lim, p=self.idx, cfg=self.cfg_dict))
        self.assertEqual(ticket.max_loss(dict(self.order, plan={}), p=self.idx, cfg=self.cfg_dict), (None, 9700.0))

    def test_gates_no_risk_stale_blocked_and_decline(self):
        with tempfile.TemporaryDirectory() as d:
            cp, op, rp, sp = [os.path.join(d, f) for f in ("cfg.json", "orders.json", "risk.json", "state.json")]
            pf, none = os.path.join(d, "pf.json"), os.path.join(d, "none")
            json.dump(self.cfg_dict, open(cp, "w", encoding="utf-8"))
            json.dump({"orders": [self.order]}, open(op, "w", encoding="utf-8"))
            common = ["--orders", op, "--config", cp, "--risk", rp, "--state", sp, "--now", "2026-11-23 10:15"]
            self.assertEqual(_run_mod(ticket, ["show"] + common)[0], 1)
            self.assertEqual(_run_mod(ticket, ["approve", "--index", "1", "--reply", "yes"] + common)[0], 1)

            with redirect_stdout(io.StringIO()):
                check.main(["--orders", op, "--config", cp, "--portfolio", pf, "--prices", none, "--state", sp,
                            "--now", "2026-11-20 10:15", "--out", rp])
            self.assertIn("not today", _run_mod(ticket, ["show", "--index", "1"] + common)[1])

            with redirect_stdout(io.StringIO()):
                check.main(["--orders", op, "--config", cp, "--portfolio", pf, "--prices", none, "--state", sp,
                            "--now", "2026-11-23 09:10", "--out", rp])
            self.assertIn("BLOCKED", _run_mod(ticket, ["show", "--index", "1", "--orders", op, "--config", cp, "--risk", rp,
                                                        "--state", sp, "--now", "2026-11-23 09:10"])[1])

            with redirect_stdout(io.StringIO()):
                check.main(["--orders", op, "--config", cp, "--portfolio", pf, "--prices", none, "--state", sp,
                            "--now", "2026-11-23 10:15", "--out", rp])
            self.assertEqual(_run_mod(ticket, ["result", "--index", "1", "--status", "placed"] + common)[0], 1)
            self.assertEqual(_run_mod(ticket, ["decline", "--index", "1", "--reply", "no"] + common)[0], 0)
            self.assertIn("DONE: declined", _run_mod(ticket, ["show", "--index", "1"] + common)[1])

    def test_double_approve_and_duplicate_after_result(self):
        with tempfile.TemporaryDirectory() as d:
            cp, op, rp, sp = [os.path.join(d, f) for f in ("cfg.json", "orders.json", "risk.json", "state.json")]
            pf, none = os.path.join(d, "pf.json"), os.path.join(d, "none")
            json.dump(self.cfg_dict, open(cp, "w", encoding="utf-8"))
            json.dump({"orders": [self.order]}, open(op, "w", encoding="utf-8"))
            with redirect_stdout(io.StringIO()):
                check.main(["--orders", op, "--config", cp, "--portfolio", pf, "--prices", none, "--state", sp,
                            "--now", "2026-11-23 10:15", "--out", rp])
            common = ["--orders", op, "--config", cp, "--risk", rp, "--state", sp, "--now", "2026-11-23 10:15"]
            self.assertEqual(_run_mod(ticket, ["approve", "--index", "1", "--reply", "yes"] + common)[0], 0)
            self.assertEqual(_run_mod(ticket, ["approve", "--index", "1", "--reply", "yes"] + common)[0], 1)
            self.assertEqual(_run_mod(ticket, ["result", "--index", "1", "--status", "placed", "--filled-qty", "300",
                                               "--filled-price", "9875", "--portfolio", pf] + common)[0], 0)
            st = json.load(open(sp, encoding="utf-8"))
            res = check.check([self.order], self.cfg_dict, state=st, now=check.parse_now("2026-11-23 10:30", p=self.idx))
            self.assertIn("already placed today", " ".join(res["results"][0]["reasons"]))

    def test_flatten_end_to_end_and_explicit_qty(self):
        with tempfile.TemporaryDirectory() as d:
            cp, op, rp, sp = [os.path.join(d, f) for f in ("cfg.json", "orders.json", "risk.json", "state.json")]
            pf = os.path.join(d, "pf.json")
            json.dump(self.cfg_dict, open(cp, "w", encoding="utf-8"))
            json.dump({"cash": 7000000, "positions": [{"ticker": "BBCA", "shares": 300,
                                                       "lots": [{"id": "BBCA-1", "date": "2026-11-23", "shares": 300, "cost": 2966944}]}]},
                      open(pf, "w", encoding="utf-8"))
            c, txt, err = _run_mod(ticket, ["flatten", "--symbol", "BBCA", "--orders", op, "--portfolio", pf,
                                            "--plan", BBCA_PLAN, "--config", cp, "--now", "2026-11-23 15:45"])
            self.assertEqual(c, 0, err)
            self.assertIn("flat by 15:45 WIB", txt)
            self.assertEqual(_run_mod(ticket, ["flatten", "--symbol", "BBCA", "--qty", "300", "--orders", op,
                                               "--portfolio", os.path.join(d, "none"), "--plan", os.path.join(d, "none"),
                                               "--config", cp, "--now", "2026-11-23 15:45"])[0], 0)
            self.assertEqual(_run_mod(ticket, ["flatten", "--symbol", "BBCA", "--qty", "0", "--orders", op, "--config", cp])[0], 1)

    def test_fill_sell_fifo_lot_relief_and_oversell(self):
        with tempfile.TemporaryDirectory() as d:
            cp, pf, sp = [os.path.join(d, f) for f in ("cfg.json", "pf.json", "state.json")]
            json.dump(self.cfg_dict, open(cp, "w", encoding="utf-8"))
            json.dump({"cash": 0, "positions": [{"ticker": "BBCA", "shares": 400, "lots": [
                {"id": "BBCA-1", "date": "2026-11-18", "shares": 200, "cost": 1900000},
                {"id": "BBCA-2", "date": "2026-11-20", "shares": 200, "cost": 2000000}]}]},
                open(pf, "w", encoding="utf-8"))
            c, _, err = _run_mod(ticket, ["fill", "--symbol", "BBCA", "--side", "sell", "--qty", "300", "--price", "10000",
                                          "--date", "2026-11-23", "--portfolio", pf, "--config", cp, "--state", sp, "--now", "2026-11-23 10:15"])
            self.assertEqual(c, 0, err)
            lots = json.load(open(pf, encoding="utf-8"))["positions"][0]["lots"]
            self.assertEqual([l["id"] for l in lots], ["BBCA-2"])
            self.assertEqual(lots[0]["shares"], 100)
            self.assertEqual(_run_mod(ticket, ["fill", "--symbol", "BBCA", "--side", "sell", "--qty", "500", "--price", "10000",
                                               "--portfolio", pf, "--config", cp, "--state", sp])[0], 1)


class IdxAlertsParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")

    def test_parse_now_and_quotes_offline_gz(self):
        self.assertEqual(alerts.parse_now("2026-11-23 09:00", p=self.idx), DT(2026, 11, 23, 2, 0))
        self.assertEqual(alerts.parse_now("2026-11-23T02:00:00Z", p=self.idx), DT(2026, 11, 23, 2, 0))
        with self.assertRaises(alerts.AlertError):
            alerts.parse_now("tomorrow", p=self.idx)
        self.assertFalse(alerts.market_status(alerts.parse_now("2028-03-01 10:00", p=self.idx), p=self.idx)["calendar_known"])

        with tempfile.TemporaryDirectory() as d:
            with gzip.open(BBCA_5M, "rt", encoding="utf-8") as fh:
                open(os.path.join(d, "yahoo-BBCA.JK.json"), "w", encoding="utf-8").write(fh.read())
            shutil.copy(BBRI_5M, os.path.join(d, "yahoo-BBRI.JK.json.gz"))
            q, errs = alerts.get_quotes(["BBCA", "BBRI", "ZZZZ"], "yahoo", d, p=self.idx)
            self.assertEqual(sorted(q), ["BBCA", "BBRI"])
            self.assertEqual(len(errs), 1)

    def test_network_retry_fallback_404_403_and_pause(self):
        body = _read_gz(BBCA_5M)
        saved = (alerts._urlopen, alerts._sleep)
        try:
            def run_net(codes, syms=("BBCA",)):
                seq, calls, sleeps = list(codes), [], []
                def fake(req, timeout=None):
                    calls.append((req.full_url.split("/")[2], req.get_header("User-agent")))
                    c = seq.pop(0)
                    if c != 200:
                        fp = io.BytesIO(b'{"chart":{"result":null,"error":{"description":"No data found"}}}' if c == 404 else b"")
                        raise urllib.error.HTTPError(req.full_url, c, "x", {}, fp)
                    return io.BytesIO(body.encode("utf-8"))
                alerts._urlopen = fake
                alerts._sleep = sleeps.append
                q, errs = alerts.get_quotes(list(syms), p=self.idx)
                return q, errs, calls, sleeps

            q, errs, calls, sleeps = run_net([429, 200])
            self.assertIn("BBCA", q)
            self.assertEqual(sleeps, [alerts.BACKOFF])
            _, _, calls2, _ = run_net([429, 429, 200])
            self.assertEqual([h.split(".")[0] for h, _ in calls2], ["query2", "query2", "query1"])
            _, _, calls3, _ = run_net([503, 200])
            self.assertEqual([h.split(".")[0] for h, _ in calls3], ["query2", "query1"])
            _, errs4, calls4, _ = run_net([404], ("ZZZZ",))
            self.assertEqual(len(calls4), 1)
            self.assertIn("No data found", errs4[0])
            _, _, calls5, _ = run_net([403])
            self.assertEqual(len(calls5), 1)
            _, _, _, sleeps2 = run_net([200, 200], ("BBCA", "BBRI"))
            self.assertEqual(sleeps2, [alerts.PAUSE])
        finally:
            alerts._urlopen, alerts._sleep = saved

    def test_rules_above_stop_rearm_pct_move_and_bell(self):
        st = alerts.market_status(alerts.parse_now("2026-11-23 10:00", p=self.idx), p=self.idx)
        now = alerts.parse_now("2026-11-23 10:00", p=self.idx)
        q = {"BBCA": {"symbol": "BBCA", "price": 5900.0, "prev_close": 5800.0}}
        rings, state = alerts.evaluate([{"id": "a", "symbol": "BBCA", "type": "above", "price": 5850}], q, st, {}, now, p=self.idx)
        self.assertEqual(len(rings), 1)
        self.assertEqual(alerts.evaluate([{"id": "a", "symbol": "BBCA", "type": "above", "price": 5850}], q, st, state, now, p=self.idx)[0], [])

        stop_rule = [{"id": "s", "symbol": "BBCA", "type": "stop", "price": 5800, "rearm": True}]
        q["BBCA"]["price"] = 5775.0
        r1, st1 = alerts.evaluate(stop_rule, q, st, {}, now, p=self.idx)
        self.assertEqual(len(r1), 1)
        q["BBCA"]["price"] = 5850.0
        _, st2 = alerts.evaluate(stop_rule, q, st, st1, now, p=self.idx)
        self.assertNotIn("s", st2["rung"])
        q["BBCA"]["price"] = 5775.0
        self.assertEqual(len(alerts.evaluate(stop_rule, q, st, st2, now, p=self.idx)[0]), 1)

        q["BBCA"]["price"] = 5975.0
        self.assertEqual(len(alerts.evaluate([{"id": "m", "symbol": "BBCA", "type": "pct_move", "pct": 3, "direction": "up"}],
                                             q, st, {}, now, p=self.idx)[0]), 1)

    def test_plan_rules_flat_by_and_bad_rules(self):
        plan = json.load(open(BBCA_PLAN, encoding="utf-8"))
        rules = alerts.rules_from_plan(plan, p=self.idx)
        self.assertEqual([r["type"] for r in rules], ["stop", "target", "time"])
        q = {"BBCA": {"symbol": "BBCA", "price": 9650.0}}
        st = alerts.market_status(alerts.parse_now("2026-11-23 10:00", p=self.idx), p=self.idx)
        rings, _ = alerts.evaluate(rules, q, st, {}, alerts.parse_now("2026-11-23 10:00", p=self.idx), p=self.idx)
        self.assertEqual([r["id"] for r in rings], ["bbca-plan-stop"])
        for bad in ({"id": "x", "type": "moon"}, {"id": "x", "type": "above", "symbol": "BBCA"}, {"id": "x", "type": "time", "at": "4pm"}):
            with self.assertRaises(alerts.AlertError):
                alerts.evaluate([bad], {}, st, {}, alerts.parse_now("2026-11-23 10:00", p=self.idx), p=self.idx)

    def test_cli_plan_add_list_reset_and_check(self):
        with tempfile.TemporaryDirectory() as d:
            cp, rp, sp, pp = [os.path.join(d, f) for f in ("cfg.json", "rules.json", "state.json", "prices.json")]
            json.dump({"market": "idx"}, open(cp, "w", encoding="utf-8"))
            with gzip.open(BBCA_5M, "rt", encoding="utf-8") as fh:
                open(os.path.join(d, "yahoo-BBCA.JK.json"), "w", encoding="utf-8").write(fh.read())
            self.assertEqual(_run_mod(alerts, ["add", "--from-plan", "--plan", BBCA_PLAN, "--rules", rp, "--state", sp, "--config", cp])[0], 0)
            self.assertEqual(_run_mod(alerts, ["add", "--rules", rp, "--opening-bell"])[0], 0)
            self.assertEqual(_run_mod(alerts, ["add", "--rules", rp, "--opening-bell"])[0], 1)
            self.assertEqual(_run_mod(alerts, ["check", "--rules", rp, "--state", sp, "--prices-out", pp,
                                               "--config", cp, "--offline", d, "--now", "2026-11-23 10:15"])[0], 0)
            self.assertIn("rang", _run_mod(alerts, ["list", "--rules", rp, "--state", sp])[1])
            self.assertEqual(_run_mod(alerts, ["reset", "opening-bell", "--state", sp])[0], 0)
            self.assertEqual(_run_mod(alerts, ["reset", "opening-bell", "--state", sp])[0], 1)

    def test_cli_add_quote_clock_and_no_rules(self):
        with tempfile.TemporaryDirectory() as d:
            cp, rp, pp = [os.path.join(d, f) for f in ("cfg.json", "rules.json", "prices.json")]
            json.dump({"market": "idx"}, open(cp, "w", encoding="utf-8"))
            with gzip.open(BBCA_5M, "rt", encoding="utf-8") as fh:
                open(os.path.join(d, "yahoo-BBCA.JK.json"), "w", encoding="utf-8").write(fh.read())
            with gzip.open(BBRI_5M, "rt", encoding="utf-8") as fh:
                open(os.path.join(d, "yahoo-BBRI.JK.json"), "w", encoding="utf-8").write(fh.read())
            self.assertEqual(_run_mod(alerts, ["quote", "BBCA", "--config", cp, "--offline", d, "--write", pp, "--now", "2026-11-26 16:15"])[0], 0)
            self.assertEqual(_run_mod(alerts, ["quote", "BBRI", "--config", cp, "--offline", d, "--write", pp])[0], 0)
            self.assertEqual(sorted(json.load(open(pp, encoding="utf-8"))["prices"]), ["BBCA", "BBRI"])
            self.assertEqual(_run_mod(alerts, ["clock", "--config", cp, "--now", "2026-11-23 10:15"])[0], 0)
            self.assertEqual(_run_mod(alerts, ["clock", "--config", cp, "--now", "2026-08-17 10:15"])[0], 1)
            self.assertEqual(_run_mod(alerts, ["check", "--rules", rp, "--offline", d])[0], 1)


class IdxNewsParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")

    def test_parse_rss_times_symbol_tags_and_dedupe(self):
        with open(CNBC_XML, "rb") as fh:
            items = news.parse_rss(fh.read(), None, "CNBC Indonesia Market")
        self.assertEqual(len(items), 5)
        self.assertTrue(items[0]["id"].startswith("rss:"))
        self.assertEqual(news.parse_time("Thu, 26 Nov 2026 20:50:00 +0700").hour, 13)
        self.assertIsNone(news.parse_time("soon"))
        self.assertEqual(news.yahoo_symbol("bbca", p=self.idx), "BBCA.JK")

        sample = [{"id": "1", "source": "CNBC", "kind": "headline", "ticker": None,
                   "title": "BBCA and BMRI declare dividend", "summary": "", "link": "https://x/1", "time": None}]
        tagged = news.tag(sample, {"BBCA": None, "BMRI": None}, p=self.idx)
        self.assertEqual(tagged[0]["touches"], ["BBCA", "BMRI"])
        self.assertIn("capital", tagged[0]["tags"])
        ded = news.dedupe(tagged + [dict(tagged[0], id="2")])
        self.assertEqual(len(ded), 1)

    def test_cli_once_newest_first_watchlist_errors_and_state(self):
        with tempfile.TemporaryDirectory() as d:
            cp, sp, wl, pl = [os.path.join(d, f) for f in ("cfg.json", "state.json", "wl.json", "plan.json")]
            json.dump({"news_feeds": [{"label": "CNBC Indonesia Market", "url": "https://www.cnbcindonesia.com/market/rss"}]},
                      open(cp, "w", encoding="utf-8"))
            json.dump({"created_by": "trader-scanner", "hits": [{"symbol": "BBCA"}]}, open(wl, "w", encoding="utf-8"))
            json.dump({"created_by": "trader-exit", "symbol": "TLKM"}, open(pl, "w", encoding="utf-8"))
            self.assertEqual(sorted(news.watch_from_files("/nonexistent.json", wl, pl)), ["BBCA", "TLKM"])

            base = ["--config", cp, "--offline", IDX_FIX, "--state", sp, "--hours", "72",
                    "--now", "2026-11-26T12:00:00+07:00", "--portfolio", os.path.join(d, "none.json"),
                    "--watchlist", os.path.join(d, "none.json"), "--plan", os.path.join(d, "none.json")]
            c1, out1, err1 = _run_mod(news, ["--tickers", "BBCA"] + base)
            self.assertEqual(c1, 0, err1)
            self.assertIn("Not financial advice", out1)
            c2, out2, _ = _run_mod(news, ["--tickers", "BBCA"] + base)
            self.assertEqual(c2, 1)
            self.assertIn("Nothing new.", out2)
            self.assertEqual(_run_mod(news, base)[0], 2)

            st = {"seen": {"old": "2026-08-01T00:00:00+00:00"}}
            news.remember([], st, news.parse_time("2026-11-26T12:00:00+07:00"))
            self.assertNotIn("old", st["seen"])

    def test_future_filter_moves_and_day_trading_tags(self):
        items = [{"id": "x", "source": "CNBC", "kind": "headline", "ticker": "BBCA",
                  "title": "Trading halted after OJK approval; futures rise before CPI; merger deal ahead of earnings",
                  "summary": "", "link": "", "time": None}]
        tags = news.tag(items, {"BBCA": None}, p=self.idx)[0]["tags"]
        for t in ("halt", "regulatory", "macro", "deal", "earnings"):
            self.assertIn(t, tags)
        m = news.parse_chart(_read_gz(BBCA_5M).encode("utf-8"), "BBCA")
        self.assertIn("MOVING", news.render_moves([m], p=self.idx)[0])
        with self.assertRaises(news.NewsError):
            news.parse_chart(b'{"chart":{"result":null}}', "ZZZZ")


class IdxCoreParityTest(unittest.TestCase):
    def test_core_profile_time_tick_config_money_and_scanner_help(self):
        scan_py = os.path.join(ROOT, "skills", "trader-scanner", "scan.py")
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, scan_py, "--help"], cwd=tmp,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        idx = market.load("idx")
        self.assertIs(idx, market.load("IDX"))
        with self.assertRaises(ValueError):
            market.load("bogus")
        self.assertEqual(market._nth_sunday(2026, 3, -1), D(2026, 3, 29))

        utc = DT(2026, 11, 23, 2, 35)
        loc = market.to_local(idx, utc)
        self.assertEqual(loc, DT(2026, 11, 23, 9, 35))
        self.assertEqual(market.local_to_utc(idx, loc), utc)
        self.assertFalse(market.is_trading_day(idx, D(2026, 8, 17)))
        self.assertTrue(market.is_trading_day(idx, D(2026, 11, 23)))

        self.assertEqual(market.round_tick(idx, 5010, "down"), Decimal("5000"))
        self.assertEqual(market.round_tick(idx, 5010, "up"), Decimal("5025"))
        self.assertEqual(market.round_tick(idx, 5015, "nearest"), Decimal("5025"))
        with self.assertRaises(ValueError):
            market.round_tick(idx, 5000, "invalid")

        self.assertIs(market.from_config(None), idx)
        self.assertIs(market.from_config({}), idx)
        self.assertEqual(market.money(idx, 64218.75), "Rp 64.219")
        self.assertEqual(market.money({"currency": "EUR"}, 15000), "EUR 15,000")
        self.assertEqual(market.fees(idx), (0.15, 0.25))
        with self.assertRaises(ValueError):
            market.fees(idx, {"buy_fee_pct": -0.1})

        for base, _, files in os.walk(os.path.join(ROOT, "skills")):
            for f in files:
                if f.endswith(".py"):
                    src = open(os.path.join(base, f), encoding="utf-8").read()
                    if "def eastern_offset(" in src:
                        self.assertIn("market.utc_offset(", src)
                        self.assertNotIn("def _nth_sunday(", src)

    def test_new_key_wins_over_usd_alias_on_idx(self):
        merged, notices = market.merge_config({"max_loss_per_trade": 40000, "max_loss_per_trade_usd": 80000},
                                              {"max_loss_per_trade": 50000})
        self.assertEqual(merged["max_loss_per_trade"], 40000)
        self.assertNotIn("max_loss_per_trade_usd", merged)
        self.assertEqual(len(notices), 1)
        plan = json.load(open(BBCA_PLAN, encoding="utf-8"))
        s = size.size_trade(plan, {"market": "idx", "budget": 10000000, "max_loss_per_trade": 40000, "max_loss_per_trade_usd": 80000},
                            today="2026-11-23")
        self.assertEqual(s["lots"], 1)


if __name__ == "__main__":
    unittest.main()
