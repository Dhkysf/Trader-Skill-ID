"""Offline tests for the IDX market profile and trader-scanner IDX support.

Fixtures under tests/fixtures/idx/ were fetched from Yahoo Finance on 2026-11-27.
"""

import datetime
import gzip
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from unittest import mock

from _load import FIX, load

market = load("trader-core", "market")
scan = load("trader-scanner", "scan")
news = load("trader-news", "news")
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
alerts = load("trader-alerts", "alerts")
tm = load("trader-timemachine", "timemachine")
size = load("trader-budget", "size")
check = load("trader-risk", "check")
ticket = load("trader-broker", "ticket")

IDX_FIX = os.path.join(FIX, "idx")
BBCA_5M = os.path.join(IDX_FIX, "BBCA.JK-5m-60d-2026-11-27.json.gz")
SPARK_DAILY = os.path.join(IDX_FIX, "spark-daily-2026-11-27.json.gz")
BBCA_PLAN = os.path.join(IDX_FIX, "plan-bbca.json")
DELAY_MSG = "IDX data from Yahoo is about 10 minutes late. Check your broker app before acting."


def run_scan(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = scan.main(argv)
    return code, out.getvalue(), err.getvalue()


class IdxProfileTest(unittest.TestCase):
    def setUp(self):
        self.idx = market.load("idx")

    def test_tick_table_boundaries(self):
        expected = [
            (199, Decimal("1")),
            (200, Decimal("2")),
            (499, Decimal("2")),
            (500, Decimal("5")),
            (1999, Decimal("5")),
            (2000, Decimal("10")),
            (4999, Decimal("10")),
            (5000, Decimal("25")),
        ]
        for price, tick in expected:
            self.assertEqual(market.tick_size(self.idx, price), tick, price)
            self.assertEqual(market.valid_tick(self.idx, price), (price % int(tick)) == 0, price)
        self.assertTrue(market.valid_tick(self.idx, 498))
        self.assertTrue(market.valid_tick(self.idx, 1995))
        self.assertTrue(market.valid_tick(self.idx, 4990))
        self.assertFalse(market.valid_tick(self.idx, 0))
        self.assertFalse(market.valid_tick(self.idx, 201))
        self.assertFalse(market.valid_tick(self.idx, 2005))
        self.assertEqual(market.round_tick(self.idx, 2005, "down"), Decimal("2000"))

    def test_ar_limits_and_expiry_warning(self):
        cases = [
            (12, (Decimal("11"), Decimal("16"))),
            (150, (Decimal("140"), Decimal("202"))),
            (1000, (Decimal("930"), Decimal("1250"))),
            (9000, (Decimal("8375"), Decimal("10800"))),
        ]
        for ref, want in cases:
            got = market.ar_limits(self.idx, ref, "2026-11-27")
            self.assertEqual(got, want, ref)
            self.assertTrue(market.valid_tick(self.idx, got[0]), got[0])
            self.assertTrue(market.valid_tick(self.idx, got[1]), got[1])

        err = io.StringIO()
        with redirect_stderr(err):
            market.ar_limits(self.idx, 1000, "2027-01-04")
        self.assertIn("check the current ARA/ARB rule on idx.co.id and update markets/idx.json", err.getvalue())
        self.assertEqual(market.round_lot(self.idx, 250), 200)

    def test_sessions_monday_vs_friday_and_holiday(self):
        mon = datetime.date(2026, 11, 23)
        fri = datetime.date(2026, 11, 27)
        hol = datetime.date(2026, 8, 17)
        future = datetime.date(2027, 1, 4)
        self.assertEqual(
            market.sessions(self.idx, mon),
            [(datetime.time(9, 0), datetime.time(12, 0)), (datetime.time(13, 30), datetime.time(15, 50))],
        )
        self.assertEqual(
            market.sessions(self.idx, fri),
            [(datetime.time(9, 0), datetime.time(11, 30)), (datetime.time(14, 0), datetime.time(15, 50))],
        )
        self.assertEqual(market.sessions(self.idx, hol), [])
        self.assertFalse(market.is_trading_day(self.idx, hol))
        self.assertEqual(
            market.sessions(self.idx, future),
            [(datetime.time(9, 0), datetime.time(12, 0)), (datetime.time(13, 30), datetime.time(15, 50))],
        )


class IdxScannerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx"}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_universe_parse_csv_comma_semicolon_and_text(self):
        csv_comma = (
            "No,Kode,Nama Perusahaan,Tanggal Pencatatan,Saham,Papan Pencatatan\n"
            "1,BBCA,Bank Central Asia Tbk.,31 Mei 2000,123,Utama\n"
            "2,ABBA,Mahaka Media Tbk.,03 Apr 2002,456,Pemantauan Khusus\n"
            "3,MBMA,Merdeka Battery Materials Tbk.,18 Apr 2023,789,\n"
        )
        kept, counts = scan.parse_idx_universe(csv_comma)
        self.assertEqual([s for s, _ in kept], ["BBCA", "MBMA"])
        self.assertEqual(counts["Pemantauan Khusus"], 1)

        kept_semi, _ = scan.parse_idx_universe(csv_comma.replace(",", ";"))
        self.assertEqual([s for s, _ in kept_semi], ["BBCA", "MBMA"])

        kept_txt, _ = scan.parse_idx_universe("# comment\nbbca.jk\nTLKM|Telkom Indonesia\n")
        self.assertEqual([s for s, _ in kept_txt], ["BBCA", "TLKM"])

        in_path = os.path.join(self.tmp.name, "daftar.csv")
        out_path = os.path.join(self.tmp.name, "universe.txt")
        with open(in_path, "w", encoding="utf-8") as fh:
            fh.write(csv_comma)
        code, out, _ = run_scan(["universe", "--config", self.cfg, "--from", in_path, "--out", out_path])
        self.assertEqual(code, 0)
        self.assertIn("Kept 2 IDX stocks", out)

        code, _, err = run_scan(["universe", "--config", self.cfg, "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("--from", err)

    def test_daily_idx_fixture_traded_value_and_delay(self):
        out_wl = os.path.join(self.tmp.name, "watchlist.json")
        code, out, _ = run_scan([
            "daily", "--config", self.cfg, "--offline", SPARK_DAILY,
            "--now", "2026-11-27 08:30", "--out", out_wl,
        ])
        self.assertIn(code, (0, 1))
        self.assertIn(DELAY_MSG, out)
        self.assertIn("Rp 5.000.000.000+ traded value", out)
        with open(out_wl, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["delay_notice"], DELAY_MSG)
        self.assertEqual(doc["filters"]["min_price"], 100.0)
        self.assertEqual(doc["filters"]["min_value"], 5000000000.0)

    def test_orb_bbca_fixture_ignores_lunch_and_prints_delay(self):
        out_wl = os.path.join(self.tmp.name, "orb.json")
        code, out, _ = run_scan([
            "orb", "--config", self.cfg, "--offline", BBCA_5M,
            "--now", "2026-11-26 14:30", "--out", out_wl,
        ])
        self.assertIn(code, (0, 1))
        self.assertIn("9:00 to 9:15 AM", out)
        self.assertIn("1 usable", out)
        self.assertIn(DELAY_MSG, out)
        with open(out_wl, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["scanned"], 1)
        self.assertEqual(doc["delay_notice"], DELAY_MSG)


class IdxEntryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx"}, fh)

    def tearDown(self):
        self.tmp.cleanup()

    def run_entry(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = entry.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_friday_session1_and_lunch_break_on_bbca(self):
        # 11:25 on Friday 2026-11-20 is still session 1
        code, out, err = self.run_entry([
            "check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M,
            "--now", "2026-11-20 11:25", "--json",
        ])
        self.assertEqual(code, 1, err)
        r = json.loads(out)
        self.assertEqual((r["status"], r["phase"]), ("waiting", "open"))

        # 11:35 on Friday 2026-11-20 is lunch break, next session at 14:00
        code, out, err = self.run_entry([
            "check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M,
            "--now", "2026-11-20 11:35",
        ])
        self.assertEqual(code, 1, err)
        self.assertIn("market on lunch break, next session at 14:00", out)

    def test_monday_session2_trigger_and_delay_note(self):
        # Monday 2026-11-23: 13:30 bar closes at 13:35 at 5700 (> 5690)
        cfg2 = os.path.join(self.tmp.name, "cfg_s2.json")
        with open(cfg2, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx", "no_entries_before": "13:30"}, fh)
        code, out, err = self.run_entry([
            "check", "BBCA", "--config", cfg2, "--offline", BBCA_5M,
            "--setup", "level", "--level", "5690", "--now", "2026-11-23 13:35",
        ])
        self.assertEqual(code, 0, err)
        self.assertIn("TRIGGERED 1:35 PM", out)
        self.assertIn("13:30 bar", out)
        self.assertIn("data about 10 min late", out)

    def test_pre_break_blackout_default_and_override(self):
        # Monday 2026-11-16: 11:50 bar closes at 11:55 (within 10 min of 12:00 lunch) at 5475 (> 5470)
        cfg_s1 = os.path.join(self.tmp.name, "cfg_prebreak.json")
        with open(cfg_s1, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx", "no_entries_before": "11:51"}, fh)
        code, out, _ = self.run_entry([
            "check", "BBCA", "--config", cfg_s1, "--offline", BBCA_5M,
            "--setup", "level", "--level", "5470", "--now", "2026-11-16 11:55",
        ])
        self.assertEqual(code, 1)
        self.assertIn("within 10 min of the lunch break", out)

        with open(cfg_s1, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx", "no_entries_before": "11:51", "no_entries_before_break_min": 0}, fh)
        code, out, err = self.run_entry([
            "check", "BBCA", "--config", cfg_s1, "--offline", BBCA_5M,
            "--setup", "level", "--level", "5470", "--now", "2026-11-16 11:55",
        ])
        self.assertEqual(code, 0, err)
        self.assertIn("TRIGGERED 11:55 AM", out)


class IdxWatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")
        base = entry.parse_chart(entry.read_text(BBCA_5M), "BBCA")
        cls.prev_close = base["prev_close"]
        cls.thu_bars = [
            dict(b) for b in base["bars"]
            if market.to_local(cls.idx, entry.utc_of(b["t"])).date().isoformat() == "2026-11-26"
        ]
        # fixture was captured before 2026-11-27 open; shift Friday 2026-11-20 bars +7d
        cls.fri_bars = [
            dict(b, t=b["t"] + 7 * 86400) for b in base["bars"]
            if market.to_local(cls.idx, entry.utc_of(b["t"])).date().isoformat() == "2026-11-20"
        ]

    def _provider(self, day_bars, delay_min=10, calls=None):
        def provider(now):
            if calls is not None:
                calls.append(now)
            data_ts = entry.ts_of(now) - delay_min * 60
            bars = [dict(b) for b in day_bars if b["t"] % 300 == 0 and b["t"] + 300 <= data_ts]
            return {"symbol": "BBCA.JK", "meta": {}, "bars": bars, "prev_close": self.prev_close, "data_time": data_ts}
        return provider

    def _run(self, day_bars, start_text, delay_min=10, every=30, until=None):
        clock = entry.SimClock(entry.parse_now(start_text, p=self.idx))
        calls, lines = [], []
        opts = {"setup": "level", "or_minutes": 15, "interval": "5m", "level": 99999,
                "min_volume_x": None, "cfg": {"market": "idx"}}
        code, res = entry.watch_loop(
            self._provider(day_bars, delay_min=delay_min, calls=calls),
            clock.now, clock.sleep, lines.append, opts, every=every, until=until,
        )
        return code, res, lines, calls, clock

    def test_thursday_delay_10_calls_expiry_and_notice(self):
        code, res, lines, calls, clock = self._run(self.thu_bars, "2026-11-26 09:00", delay_min=10, every=30)
        self.assertEqual(code, 1)
        self.assertEqual(res["status"], "expired")
        self.assertEqual(market.to_local(self.idx, clock.now()).strftime("%H:%M"), "15:30")
        self.assertTrue(any(line.startswith("EXPIRED") for line in lines))
        self.assertLessEqual(len(calls), 90)
        notice = "IDX data is about 10 min late: each bar is checked about 10 min after it closes."
        self.assertEqual(lines[0], notice)
        self.assertEqual(lines.count(notice), 1)

    def test_thursday_lunch_break_and_resume(self):
        _, _, lines, calls, _ = self._run(self.thu_bars, "2026-11-26 09:00", delay_min=10, every=30)
        times = [market.to_local(self.idx, c).time() for c in calls]
        lunch_calls = [t for t in times if datetime.time(12, 0) <= t < datetime.time(13, 30)]
        self.assertEqual(len(lunch_calls), 1)
        self.assertEqual(sum(1 for line in lines if line.startswith("LUNCH BREAK")), 1)
        after = [t for t in times if t >= datetime.time(13, 30)]
        self.assertTrue(after)
        self.assertGreaterEqual(after[0], datetime.time(13, 35))

    def test_friday_lunch_break_no_calls_between_1135_and_1400(self):
        _, res, lines, calls, _ = self._run(self.fri_bars, "2026-11-27 09:00", delay_min=10, every=30)
        times = [market.to_local(self.idx, c).time() for c in calls]
        self.assertEqual([t for t in times if datetime.time(11, 35) <= t < datetime.time(14, 0)], [])
        self.assertEqual(sum(1 for line in lines if line.startswith("LUNCH BREAK")), 1)
        self.assertEqual(res["status"], "expired")
        self.assertLessEqual(len(calls), 90)

    def test_delay_0_keeps_original_60_calls(self):
        with mock.patch.dict(entry.market.load("idx"), {"data_delay_min": 0}):
            _, res, lines, calls, _ = self._run(self.thu_bars, "2026-11-26 09:00", delay_min=0, every=30)
        self.assertEqual(len(calls), 60)
        self.assertEqual(res["status"], "expired")
        self.assertFalse(any("each bar is checked" in line for line in lines))

    def test_falls_back_to_every_when_feed_lags_past_delay(self):
        _, _, _, calls, _ = self._run(
            self.thu_bars, "2026-11-26 09:00", delay_min=11, every=30,
            until=datetime.datetime(2026, 11, 26, 9, 20),
        )
        times = [market.to_local(self.idx, c).strftime("%H:%M:%S") for c in calls]
        self.assertEqual(times[:4], ["09:15:02", "09:15:32", "09:16:02", "09:20:00"])


class IdxExitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = os.path.join(self.tmp.name, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as fh:
            json.dump({"market": "idx"}, fh)
        self.idx = market.load("idx")

    def tearDown(self):
        self.tmp.cleanup()

    def run_exit(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = exitp.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_tick_rounding_and_two_tick_minimum_risk(self):
        sr, sp = exitp.parse_stop("price:9873")
        tr, tp = exitp.parse_target("2R")
        c = exitp.compute(9900, sr, sp, tr, tp, p=self.idx)
        self.assertEqual(c["stop"], Decimal("9850"))
        self.assertEqual(c["risk"], Decimal("50"))
        self.assertEqual(c["target"], Decimal("10000"))

        # 1-tick risk (9900 -> 9875) refused
        sr1, sp1 = exitp.parse_stop("price:9875")
        with self.assertRaises(exitp.PlanError) as cm:
            exitp.compute(9900, sr1, sp1, tr, tp, p=self.idx)
        self.assertIn("2 ticks", str(cm.exception))

        # Tick boundary at 5000: 1 tick below 5000 is 10, so 4990 is 1 tick (refused), 4980 is 2 ticks (allowed)
        sr_b1, sp_b1 = exitp.parse_stop("price:4990")
        with self.assertRaises(exitp.PlanError):
            exitp.compute(5000, sr_b1, sp_b1, tr, tp, p=self.idx)
        sr_b2, sp_b2 = exitp.parse_stop("price:4980")
        self.assertEqual(exitp.compute(5000, sr_b2, sp_b2, tr, tp, p=self.idx)["risk"], Decimal("20"))

    def test_arb_ara_and_lunch_break_warnings_and_bbca_end_to_end(self):
        # ARB lock warning when stop is below today's ARB (prev_close=10000 -> ARB=9300)
        code, out, err = self.run_exit([
            "plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "9900",
            "--stop", "price:9200", "--target", "price:12500", "--prev-close", "10000",
            "--date", "2026-11-23", "--time", "09:35", "--now", "2026-11-23 09:40",
        ])
        self.assertEqual(code, 0, err)
        self.assertIn("ARB lock: a stop there may not fill", out)
        self.assertIn("above today's ARA", out)
        self.assertIn("the price can gap after the lunch break", out)
        self.assertIn("Flat by       15:45 WIB", out)

        # Session 2 entry does not warn about lunch break
        code, out, err = self.run_exit([
            "plan", "--config", self.cfg, "--symbol", "BBCA", "--entry", "5700",
            "--stop", "price:5600", "--date", "2026-11-23", "--time", "14:05", "--now", "2026-11-23 14:10",
        ])
        self.assertEqual(code, 0, err)
        self.assertNotIn("lunch break", out)

        # End-to-end offline BBCA: entry -> exit
        epath = os.path.join(self.tmp.name, "entry.json")
        ppath = os.path.join(self.tmp.name, "plan.json")
        code, _, err = (lambda a: (entry.main(a), None, None))(
            ["check", "BBCA", "--config", self.cfg, "--offline", BBCA_5M,
             "--now", "2026-11-23 09:35", "--write", epath]
        )
        self.assertEqual(code, 0, err)
        code, out, err = self.run_exit([
            "plan", "--config", self.cfg, "--from", epath, "--now", "2026-11-23 09:40", "--write", ppath,
        ])
        self.assertEqual(code, 0, err)
        self.assertIn("Exit plan: BBCA long", out)
        self.assertIn("the price can gap after the lunch break", out)


class IdxAlertsTest(unittest.TestCase):
    def setUp(self):
        self.idx = market.load("idx")

    def st(self, text):
        return alerts.market_status(alerts.parse_now(text, p=self.idx), p=self.idx)

    def test_idx_market_status_all_six_states_and_friday(self):
        # Monday 2026-11-23
        self.assertEqual((self.st("2026-11-23 08:30")["status"], self.st("2026-11-23 08:30")["open"]),
                         ("pre-open", False))
        self.assertEqual((self.st("2026-11-23 09:00")["status"], self.st("2026-11-23 09:00")["open"]),
                         ("session 1", True))
        mon_lunch = self.st("2026-11-23 12:30")
        self.assertEqual((mon_lunch["status"], mon_lunch["open"], mon_lunch["next_open"]),
                         ("lunch break", False, "2026-11-23 13:30"))
        self.assertEqual((self.st("2026-11-23 13:30")["status"], self.st("2026-11-23 13:30")["open"]),
                         ("session 2", True))
        self.assertEqual((self.st("2026-11-23 15:55")["status"], self.st("2026-11-23 15:55")["open"]),
                         ("pre-closing", False))
        self.assertEqual((self.st("2026-11-23 16:05")["status"], self.st("2026-11-23 16:05")["open"]),
                         ("closed", False))

        # Friday 2026-11-20
        self.assertEqual(self.st("2026-11-20 11:25")["status"], "session 1")
        fri_lunch = self.st("2026-11-20 13:45")
        self.assertEqual((fri_lunch["status"], fri_lunch["next_open"]), ("lunch break", "2026-11-20 14:00"))
        self.assertEqual(self.st("2026-11-20 14:00")["status"], "session 2")

        # Weekend and holiday
        self.assertEqual(self.st("2026-11-21 10:00")["status"], "closed")
        self.assertEqual(self.st("2026-08-17 10:00")["status"], "closed")

    def test_opening_bell_and_flat_by_and_yahoo_only(self):
        bell = [{"id": "bell", "type": "opening_bell"}]
        t_pre = alerts.parse_now("2026-11-23 08:59", p=self.idx)
        self.assertEqual(alerts.evaluate(bell, {}, self.st("2026-11-23 08:59"), {}, t_pre, p=self.idx)[0], [])
        t_open = alerts.parse_now("2026-11-23 09:00", p=self.idx)
        rings, state = alerts.evaluate(bell, {}, self.st("2026-11-23 09:00"), {}, t_open, p=self.idx)
        self.assertEqual(len(rings), 1)
        self.assertIn("IDX is open", rings[0]["message"])
        # Does not re-fire in session 2
        t_s2 = alerts.parse_now("2026-11-23 13:30", p=self.idx)
        self.assertEqual(alerts.evaluate(bell, {}, self.st("2026-11-23 13:30"), state, t_s2, p=self.idx)[0], [])

        # Flat-by defaults to 15:45 from IDX profile
        rules = alerts.rules_from_plan({"symbol": "BBCA", "stop": 5450, "target": 5750, "market": "idx"})
        flat_rule = [r for r in rules if r["type"] == "time"]
        self.assertEqual(flat_rule[0]["at"], "15:45")
        t_1544 = alerts.parse_now("2026-11-23 15:44", p=self.idx)
        self.assertEqual(alerts.evaluate(flat_rule, {}, self.st("2026-11-23 15:44"), {}, t_1544, p=self.idx)[0], [])
        t_1545 = alerts.parse_now("2026-11-23 15:45", p=self.idx)
        rings, _ = alerts.evaluate(flat_rule, {}, self.st("2026-11-23 15:45"), {}, t_1545, p=self.idx)
        self.assertEqual(len(rings), 1)
        self.assertIn("15:45 WIB", rings[0]["message"])

        # Yahoo .JK only
        self.assertIn("/BBCA.JK?", alerts.yahoo_url("BBCA", p=self.idx))


class IdxTimeMachineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.idx = market.load("idx")
        with open(BBCA_5M, "rb") as fh:
            import gzip
            cls.bbca_text = gzip.decompress(fh.read()).decode("utf-8")
        cls.bbca_result = tm.chart_result(cls.bbca_text, "BBCA")

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

    def test_slot_counts_and_excluded_bars(self):
        sm_thu = tm.slot_map(self.idx, "2026-11-26")
        sm_fri = tm.slot_map(self.idx, "2026-11-20")
        self.assertEqual((sm_thu["session_counts"], sm_thu["total"], sm_thu["s2_starts"]), ([36, 28], 64, frozenset({36})))
        self.assertEqual((sm_fri["session_counts"], sm_fri["total"], sm_fri["s2_starts"]), ([30, 22], 52, frozenset({30})))

        _, bars, _ = tm.parse_bars(self.bbca_result, tm.parse_now("2026-11-27 08:30", p=self.idx), p=self.idx)
        excluded = {"15:50", "15:55", "16:00", "16:05", "16:10"}
        self.assertFalse(any(b["start"] in excluded for b in bars))
        days = tm.split_sessions(bars)
        full, short = tm.full_sessions(days, "2026-11-26", p=self.idx)
        self.assertEqual(len(full), 58)
        self.assertEqual(short, [{"date": "2026-10-16", "bars": 47}])

    def test_session2_lunch_gap_isolation(self):
        _, bars, _ = tm.parse_bars(self.bbca_result, tm.parse_now("2026-11-27 08:30", p=self.idx), p=self.idx)
        full, _ = tm.full_sessions(tm.split_sessions(bars), "2026-11-26", p=self.idx)
        pool_thu = tm.build_pool(full, p=self.idx, plan_date="2026-11-26")
        pool_fri = tm.build_pool(full, p=self.idx, plan_date="2026-11-20")
        self.assertEqual(len(pool_thu[36]), 58)
        self.assertEqual(len(pool_fri[30]), 58)
        self.assertEqual(len(pool_thu[42]), 47)  # 14:00 on Mon-Thu only, never Friday's 14:00 session-2 open

        # Synthetic check: with window=2, slot 36 draws only from pool[36], never 35/37
        sm_thu = tm.slot_map(self.idx, "2026-11-26")
        syn_pool = [(1.0, 1.0, 1.0, 1.0)] * 64
        syn_pool = [([(1.0, 1.0, 1.0, 1.0)] if i != 36 else [(1.05, 1.05, 1.05, 1.05)]) for i in range(64)]
        mc = tm.simulate(syn_pool, 5000.0, 4900.0, 6000.0, k=34, last=37, replays=50, seed=19, window=2, slot_info=sm_thu)
        self.assertEqual(mc["median_close"], 5250.0)

    def test_bbca_ar_band_ticks_and_report(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        doc = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=10000, seed=19, p=self.idx)
        m = doc["mc"]
        self.assertEqual(m["ar_band"], {"low": 5425.0, "high": 6975.0, "ref": 5825.0})
        for path in m["sample_paths"]:
            self.assertTrue(all(5425.0 <= px <= 6975.0 for px in path))
        for row in m["bands"]:
            self.assertTrue(all(5425.0 <= px <= 6975.0 for px in row))
        self.assertTrue(5425.0 <= m["median_close"] <= 6975.0)
        for tr in doc["history"]["trades"]:
            self.assertTrue(market.valid_tick(self.idx, tr["entry"]))
            self.assertTrue(market.valid_tick(self.idx, tr["stop"]))
            self.assertTrue(market.valid_tick(self.idx, tr["target"]))

        rep = "\n".join(tm.report(doc))
        self.assertIn("hit the ARB/ARA limit in ", rep)
        self.assertIn(" of 10,000 runs.", rep)
        self.assertIn(DELAY_MSG, rep)
        self.assertIn("Fewer than 20 full sessions means no verdict", rep)

        # Tight ARB below entry forces band hits and clamping
        doc_hit = tm.time_machine(self.bbca_text, self._plan(prev_close=6250.0), now_u, replays=2000, seed=19, p=self.idx)
        self.assertGreater(doc_hit["mc"]["ar_hits"], 0)
        for path in doc_hit["mc"]["sample_paths"]:
            self.assertTrue(all(5825.0 <= px <= 7500.0 for px in path))

        # Invalid tick refused
        with self.assertRaises(tm.TMError):
            self._plan(stop=5810.0)

        # Friday run
        fri_p = self._plan(date="2026-11-20", entry=5625.0, stop=5575.0, target=5725.0,
                           opening_range={"high": 5675.0, "low": 5575.0, "minutes": 15})
        doc_fri = tm.time_machine(self.bbca_text, fri_p, tm.parse_now("2026-11-20 16:00", p=self.idx),
                                  replays=200, seed=19, p=self.idx)
        self.assertEqual(doc_fri["mc"]["bars_left"], 47)


class IdxBudgetTest(unittest.TestCase):
    """Offline BBCA plan tests for IDX lot rounding, fees, and Rp formatting (rules checked 2026-11-27)."""

    def setUp(self):
        with open(BBCA_PLAN, encoding="utf-8") as fh:
            self.plan = json.load(fh)

    def _run_size(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = size.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_lot_rounding_3_7_lots_to_3_lots_and_rp_formatting(self):
        cfg = {"market": "idx", "budget": 3653750, "cash_buffer_pct": 0, "max_position_pct": 100}
        s = size.size_trade(self.plan, cfg, today="2026-11-23")
        self.assertEqual((s["qty"], s["lots"], s["cost"], s["max_loss"]), (300, 3, 2962500.0, 64218.75))
        self.assertIsNone(s["refusal"])
        order = size.bracket_order(s)
        self.assertEqual(order["qty"], "300")
        self.assertEqual(order["market"], "idx")
        self.assertIn("3 lots (300 shares)", order["why"])
        self.assertIn("Rp 64.219", order["why"])
        rep = size.plan_report(s, order)
        self.assertIn("Rp 2.962.500", rep)
        self.assertIn("Rp 9.875", rep)
        self.assertIn("Rp 64.219", rep)
        self.assertIn("3 lots (300 shares)", rep)
        self.assertNotIn("place_stock_order", rep)

    def test_under_one_lot_refused(self):
        s_cash = size.size_trade(self.plan, {"market": "idx", "budget": 900000, "cash_buffer_pct": 0,
                                             "max_position_pct": 100}, today="2026-11-23")
        self.assertEqual(s_cash["qty"], 0)
        self.assertIn("1 lot", s_cash["refusal"])
        self.assertIsNone(size.bracket_order(s_cash))

        s_loss = size.size_trade(self.plan, {"market": "idx", "budget": 10000000, "max_loss_per_trade": 15000},
                                 today="2026-11-23")
        self.assertEqual(s_loss["qty"], 0)
        self.assertIn("1 lot", s_loss["refusal"])
        self.assertIsNone(size.bracket_order(s_loss))

    def test_fee_inclusive_max_loss_and_override(self):
        # 3 lots price-only loss = 300 * 175 = Rp 52.500 (<= 60.000), but incl. fees = Rp 64.219 (> 60.000) -> 2 lots
        cfg = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 60000}
        s = size.size_trade(self.plan, cfg, today="2026-11-23")
        self.assertEqual((s["qty"], s["lots"], s["max_loss"]), (200, 2, 42812.5))

        # Overriding fees to 0% allows 3 lots
        s_nofee = size.size_trade(self.plan, dict(cfg, buy_fee_pct=0, sell_fee_pct=0), today="2026-11-23")
        self.assertEqual((s_nofee["qty"], s_nofee["lots"], s_nofee["max_loss"]), (300, 3, 52500.0))

    def test_cli_writes_idx_order(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "config.json")
            out_p = os.path.join(d, "orders.json")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 75000}, fh)
            code, out, err = self._run_size([
                "--plan", BBCA_PLAN, "--config", cfg_p, "--portfolio", os.path.join(d, "none"),
                "--now", "2026-11-23 09:30", "--write", out_p,
            ])
            self.assertEqual(code, 0, err)
            self.assertIn("Rp 64.219", out)
            with open(out_p, encoding="utf-8") as fh:
                doc = json.load(fh)
            self.assertEqual(doc["orders"][0]["qty"], "300")
            self.assertEqual(doc["orders"][0]["market"], "idx")

    def test_cash_limit_includes_buy_fee(self):
        idx = market.load("idx")
        now_u = check.parse_now("2026-11-23 10:15", p=idx)
        cfg = {"market": "idx", "budget": 2965000, "cash_buffer_pct": 0, "max_position_pct": 100}
        s = size.size_trade(self.plan, cfg, today="2026-11-23")
        self.assertEqual((s["lots"], s["qty"], s["bound_by"]), (2, 200, "cash"))
        res = check.check([size.bracket_order(s)], cfg, now=now_u)
        self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])

        # Overriding buy_fee_pct to 0 allows 3 lots and check PASSes
        cfg_nofee = dict(cfg, buy_fee_pct=0)
        s_nofee = size.size_trade(self.plan, cfg_nofee, today="2026-11-23")
        self.assertEqual((s_nofee["lots"], s_nofee["qty"]), (3, 300))
        self.assertEqual(check.check([size.bracket_order(s_nofee)], cfg_nofee, now=now_u)["results"][0]["verdict"], "PASS")

        # Knife-edge ROUND_HALF_UP: 2 lots exact fee is 2962.50, rounded up to 2963 (needs 1977963)
        cfg_edge = {"market": "idx", "budget": 1977962.5, "cash_buffer_pct": 0, "max_position_pct": 100}
        s_edge = size.size_trade(self.plan, cfg_edge, today="2026-11-23")
        self.assertEqual((s_edge["lots"], s_edge["qty"], s_edge["bound_by"]), (1, 100, "cash"))
        self.assertEqual(check.check([size.bracket_order(s_edge)], cfg_edge, now=now_u)["results"][0]["verdict"], "PASS")


class IdxRiskTest(unittest.TestCase):
    """Offline BBCA risk-check tests for IDX lots, ticks, ARA/ARB, windows, and short/margin."""

    def setUp(self):
        with open(BBCA_PLAN, encoding="utf-8") as fh:
            self.plan = json.load(fh)
        self.idx = market.load("idx")
        self.cfg = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}
        self.order = size.bracket_order(size.size_trade(self.plan, self.cfg, today="2026-11-23"))

    def _at(self, text):
        return check.parse_now(text, p=self.idx)

    def test_valid_bbca_passes_session1_and_session2(self):
        for ts in ("2026-11-23 10:15", "2026-11-23 14:00"):
            res = check.check([self.order], self.cfg, now=self._at(ts))
            self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])

    def test_lot_and_tick_blocks(self):
        bad_lot = dict(self.order, qty="150")
        res = check.check([bad_lot], self.cfg, now=self._at("2026-11-23 10:15"))
        self.assertEqual(res["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(r.startswith("lot:") for r in res["results"][0]["reasons"]))

        bad_tick = dict(self.order, type="limit", limit_price="9880", stop_loss_stop_price="9710",
                        take_profit_limit_price="10210",
                        plan=dict(self.order["plan"], entry=9880.0, stop=9710.0, target=10210.0))
        res_t = check.check([bad_tick], self.cfg, now=self._at("2026-11-23 10:15"))
        self.assertEqual(res_t["results"][0]["verdict"], "BLOCK")
        tick_reasons = [r for r in res_t["results"][0]["reasons"] if r.startswith("tick:")]
        self.assertGreaterEqual(len(tick_reasons), 3)

    def test_ar_band_blocks(self):
        # prev_close=9800 -> ARB=9125, ARA=11750
        bad_stop = dict(self.order, stop_loss_stop_price="9100",
                        plan=dict(self.order["plan"], stop=9100.0))
        res_s = check.check([bad_stop], self.cfg, now=self._at("2026-11-23 10:15"))
        self.assertTrue(any(r.startswith("ar_band: stop") for r in res_s["results"][0]["reasons"]))

        bad_target = dict(self.order, take_profit_limit_price="11800",
                          plan=dict(self.order["plan"], target=11800.0))
        res_t = check.check([bad_target], self.cfg, now=self._at("2026-11-23 10:15"))
        self.assertTrue(any(r.startswith("ar_band: target") for r in res_t["results"][0]["reasons"]))

        bad_entry = dict(self.order, type="limit", limit_price="11800",
                         take_profit_limit_price="12000",
                         plan=dict(self.order["plan"], entry=11800.0, target=12000.0))
        res_e = check.check([bad_entry], self.cfg, now=self._at("2026-11-23 10:15"))
        self.assertTrue(any(r.startswith("ar_band: entry") for r in res_e["results"][0]["reasons"]))

    def test_windows_lunch_preclosing_and_outside(self):
        cases = [
            ("2026-11-23 12:30", "window: lunch break"),
            ("2026-11-20 11:45", "window: lunch break"),
            ("2026-11-23 15:52", "window: pre-closing"),
            ("2026-11-23 09:10", "window: no new entries before"),
            ("2026-11-23 15:35", "window: no new entries after"),
            ("2026-11-23 16:05", "window: the market is closed"),
        ]
        for ts, prefix in cases:
            res = check.check([self.order], self.cfg, now=self._at(ts))
            self.assertEqual(res["results"][0]["verdict"], "BLOCK", ts)
            self.assertTrue(any(r.startswith(prefix) for r in res["results"][0]["reasons"]), (ts, res["results"][0]["reasons"]))

    def test_short_margin_and_fee_inclusive_loss_blocks(self):
        short_ord = dict(self.order, side="sell")
        res_sh = check.check([short_ord], dict(self.cfg, allow_short=True), now=self._at("2026-11-23 10:15"))
        self.assertEqual(res_sh["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(r.startswith("short:") for r in res_sh["results"][0]["reasons"]))

        res_mg = check.check([self.order], dict(self.cfg, budget=1000000, allow_margin=True),
                             now=self._at("2026-11-23 10:15"))
        self.assertEqual(res_mg["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(r.startswith("cash:") and "margin" in r for r in res_mg["results"][0]["reasons"]))

        # 3 lots BBCA: price-only loss 52.500, incl. fees 64.219 -> blocked at 60.000, passes at 65.000
        res_loss = check.check([self.order], dict(self.cfg, max_loss_per_trade=60000),
                               now=self._at("2026-11-23 10:15"))
        self.assertEqual(res_loss["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(r.startswith("loss:") for r in res_loss["results"][0]["reasons"]))

    def test_cash_check_and_cash_after_include_buy_fee(self):
        cfg = dict(self.cfg, max_loss_per_trade=75000)
        order = size.bracket_order(size.size_trade(self.plan, cfg, today="2026-11-23"))
        res = check.check([order], cfg, now=self._at("2026-11-23 10:15"))
        self.assertEqual(res["cash_after"], 7033056.0)
        self.assertIn("Cash after the passed orders: Rp 7.033.056", check.report(res))

        res_tight = check.check([order], dict(cfg, budget=2965000, cash_buffer_pct=0, max_position_pct=100),
                                now=self._at("2026-11-23 10:15"))
        self.assertEqual(res_tight["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(r.startswith("cash:") and "Rp 2.966.944" in r for r in res_tight["results"][0]["reasons"]))

        res_nofee_tight = check.check([order], dict(cfg, budget=2965000, cash_buffer_pct=0,
                                                    max_position_pct=100, buy_fee_pct=0),
                                      now=self._at("2026-11-23 10:15"))
        self.assertEqual(res_nofee_tight["results"][0]["verdict"], "PASS")

        res_nofee = check.check([order], dict(cfg, buy_fee_pct=0), now=self._at("2026-11-23 10:15"))
        self.assertIn("Cash after the passed orders: Rp 7.037.500", check.report(res_nofee))


class IdxBrokerTest(unittest.TestCase):
    """Offline end-to-end BBCA manual ticket tests (no API / MCP fields, explicit yes, journalling)."""

    def _run_ticket(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ticket.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_manual_bbca_ticket_flow_and_no_api_fields(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "config.json")
            orders_p = os.path.join(d, "orders.json")
            risk_p = os.path.join(d, "state", "risk.json")
            state_p = os.path.join(d, "state", "broker.json")
            pf_p = os.path.join(d, "portfolio.json")
            none_p = os.path.join(d, "none")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 75000}, fh)

            with redirect_stdout(io.StringIO()):
                rc_s = size.main(["--plan", BBCA_PLAN, "--config", cfg_p, "--portfolio", none_p,
                                  "--now", "2026-11-23 09:30", "--write", orders_p])
            self.assertEqual(rc_s, 0)

            with redirect_stdout(io.StringIO()):
                rc_c = check.main(["--orders", orders_p, "--config", cfg_p, "--portfolio", pf_p,
                                   "--prices", none_p, "--state", state_p, "--now", "2026-11-23 10:15",
                                   "--out", risk_p])
            self.assertEqual(rc_c, 0)

            with open(orders_p, encoding="utf-8") as fh:
                ord_doc = json.load(fh)["orders"][0]
            self.assertFalse(hasattr(ticket, "tool_input"))

            common = ["--orders", orders_p, "--config", cfg_p, "--risk", risk_p,
                      "--state", state_p, "--now", "2026-11-23 10:15"]
            code, text, err = self._run_ticket(["show", "--index", "1"] + common)
            self.assertEqual(code, 0, err)
            self.assertIn("ORDER 1 of 1, PAPER account, manual (IDX)", text)
            self.assertIn(
                "BUY 3 lots (300 shares) BBCA at Rp 9.875, stop Rp 9.700, target Rp 10.200, "
                "max loss incl. fees Rp 64.219. Enter it in your broker app yourself.",
                text,
            )
            for forbidden in ("place_stock_order", "order_class", "take_profit_limit_price",
                              "stop_loss_stop_price", "time_in_force", "tool_input"):
                self.assertNotIn(forbidden, text)

            code_j, jtext, _ = self._run_ticket(["show", "--index", "1", "--json"] + common)
            self.assertEqual(code_j, 0)
            jdoc = json.loads(jtext)
            self.assertEqual(jdoc["broker"], "manual")
            self.assertTrue(jdoc["manual"])
            for forbidden in ("tool", "tool_input", "bracket", "order_class", "take_profit_limit_price"):
                self.assertNotIn(forbidden, jdoc)

            # Explicit yes required
            self.assertEqual(self._run_ticket(["approve", "--index", "1", "--reply", "sure"] + common)[0], 1)
            self.assertEqual(self._run_ticket(["approve", "--index", "1", "--reply", "yes to all"] + common)[0], 1)
            self.assertEqual(self._run_ticket(["approve", "--index", "1", "--reply", "yes 4 lots"] + common)[0], 1)
            code_a, out_a, _ = self._run_ticket(["approve", "--index", "1", "--reply", "yes 3 lots BBCA"] + common)
            self.assertEqual(code_a, 0)
            self.assertIn("Enter this order in your broker app yourself", out_a)
            self.assertNotIn("place_stock_order", out_a)

            # Result & fill journalling
            code_r, out_r, err_r = self._run_ticket([
                "result", "--index", "1", "--status", "placed", "--filled-qty", "300",
                "--filled-price", "9875", "--portfolio", pf_p,
            ] + common)
            self.assertEqual(code_r, 0, err_r)
            self.assertIn("fee Rp 4.444", out_r)
            code_f, _, err_f = self._run_ticket([
                "fill", "--symbol", "BBCA", "--side", "sell", "--qty", "300", "--price", "10200",
                "--date", "2026-11-23", "--portfolio", pf_p, "--config", cfg_p, "--state", state_p,
                "--now", "2026-11-23 15:00",
            ])
            self.assertEqual(code_f, 0, err_f)
            with open(pf_p, encoding="utf-8") as fh:
                pf = json.load(fh)
            # incl. buy fee Rp 4.444 and sell fee Rp 7.650
            self.assertEqual((pf["cash"], pf["positions"]), (10085406.0, []))

            code_l, out_l, _ = self._run_ticket(["log", "--state", state_p, "--config", cfg_p, "--now", "2026-11-23 15:05"])
            self.assertEqual(code_l, 0)
            self.assertIn("Rp 64.219", out_l)

            # Editing order invalidates fingerprint
            with open(orders_p, encoding="utf-8") as fh:
                edited = json.load(fh)
            edited["orders"][0]["qty"] = "400"
            with open(orders_p, "w", encoding="utf-8") as fh:
                json.dump(edited, fh)
            code_e, text_e, _ = self._run_ticket(["show", "--index", "1"] + common)
            self.assertEqual(code_e, 1)
            self.assertIn("was not in the last risk check", text_e)

    def test_fill_deducts_idx_fees_and_fee_override(self):
        # Fees from markets/idx.json (buy 0.15%, sell 0.25%, checked 2026-11-27): 300*9875*0.15% = 4443.75 -> Rp 4.444,
        # 300*9700*0.25% = Rp 7.275; price loss 300*175 = 52.500
        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "config.json")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({"market": "idx", "budget": 10000000}, fh)

            def fill(pf_p, side, price, *extra):
                return self._run_ticket(["fill", "--symbol", "BBCA", "--side", side, "--qty", "300", "--price", price,
                                         "--date", "2026-11-23", "--portfolio", pf_p, "--config", cfg_p,
                                         "--state", os.path.join(d, "broker.json"), "--now", "2026-11-23 10:15"] + list(extra))

            pf_p = os.path.join(d, "pf.json")
            code, out, err = fill(pf_p, "buy", "9875")
            self.assertEqual(code, 0, err)
            self.assertIn("fee Rp 4.444", out)
            with open(pf_p, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["positions"][0]["lots"][0]["cost"], 2962500 + 4444)
            code, out, err = fill(pf_p, "sell", "9700")
            self.assertEqual(code, 0, err)
            self.assertIn("fee Rp 7.275", out)
            with open(pf_p, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["cash"], 10000000 - 52500 - 4444 - 7275)
            with open(os.path.join(d, "broker.json"), encoding="utf-8") as fh:
                self.assertEqual([r.get("fee") for r in json.load(fh)["orders"]], [4444.0, 7275.0])

            # --fee: the real fee from the broker app wins
            pf2 = os.path.join(d, "pf2.json")
            code, out, err = fill(pf2, "buy", "9875", "--fee", "5000")
            self.assertEqual(code, 0, err)
            self.assertIn("fee Rp 5.000", out)
            with open(pf2, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["cash"], 10000000 - 2962500 - 5000)

    def test_parse_yes_strict_numbers_and_tickers(self):
        with open(BBCA_PLAN, encoding="utf-8") as fh:
            plan = json.load(fh)
        cfg = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 75000}
        order = size.bracket_order(size.size_trade(plan, cfg, today="2026-11-23"))
        idx = market.load("idx")

        with tempfile.TemporaryDirectory() as d:
            uni_p = os.path.join(d, "universe.txt")
            with open(uni_p, "w", encoding="utf-8") as fh:
                fh.write("BBRI|PT Bank Rakyat Indonesia (Persero) Tbk.\nBELI|PT Global Digital Niaga Tbk.\n")

            ok1, why1 = ticket.parse_yes("yes 10 lots BBCA at 9875", order, p=idx, cfg=cfg, universe_path=uni_p)
            self.assertFalse(ok1)
            self.assertIn("10", why1)

            ok2, why2 = ticket.parse_yes("yes BBRI", order, p=idx, cfg=cfg, universe_path=uni_p)
            self.assertFalse(ok2)
            self.assertIn("BBRI", why2)
            self.assertIn("BBCA", why2)

            ok3, why3 = ticket.parse_yes("yes bbri", order, p=idx, cfg=cfg, universe_path=uni_p)
            self.assertFalse(ok3)
            self.assertIn("BBRI", why3)

            for reply in ("yes please", "yes gas", "Yes, 3 lots BBCA", "yes beli 3 lot"):
                ok, why = ticket.parse_yes(reply, order, p=idx, cfg=cfg, universe_path=uni_p)
                self.assertTrue(ok, "%r should pass, got: %s" % (reply, why))

    def test_fingerprint_covers_market_and_plan_stop(self):
        order = {
            "symbol": "BBCA", "side": "buy", "qty": "300", "type": "limit",
            "time_in_force": "day", "limit_price": "9875", "market": "idx",
            "plan": {"entry": 9875, "stop": 9700, "target": 10200, "prev_close": 9850},
        }
        self.assertEqual(check.fingerprint(order), ticket.fingerprint(order))
        self.assertNotEqual(check.fingerprint(order), check.fingerprint(dict(order, market="forex")))

        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "config.json")
            orders_p = os.path.join(d, "orders.json")
            risk_p = os.path.join(d, "risk.json")
            state_p = os.path.join(d, "broker.json")
            none_p = os.path.join(d, "none")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}, fh)
            with open(orders_p, "w", encoding="utf-8") as fh:
                json.dump({"orders": [order]}, fh)

            with redirect_stdout(io.StringIO()):
                rc = check.main(["--orders", orders_p, "--config", cfg_p, "--portfolio", none_p,
                                 "--prices", none_p, "--state", state_p, "--now", "2026-11-23 10:15",
                                 "--out", risk_p])
            self.assertEqual(rc, 0)

            common = ["--orders", orders_p, "--config", cfg_p, "--risk", risk_p,
                      "--state", state_p, "--now", "2026-11-23 10:15"]
            code, text, _ = self._run_ticket(["show", "--index", "1"] + common)
            self.assertEqual(code, 0)
            self.assertIn("READY: trader-risk PASS", text)

            edited = dict(order, plan=dict(order["plan"], stop=5000))
            with open(orders_p, "w", encoding="utf-8") as fh:
                json.dump({"orders": [edited]}, fh)
            code2, text2, _ = self._run_ticket(["show", "--index", "1"] + common)
            self.assertEqual(code2, 1)
            self.assertIn("NOT READY", text2)
            self.assertIn("run check.py again", text2)


class IdxTimeMachineRestTest(IdxTimeMachineTest):
    def test_determinism_on_bbca(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        a = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=500, seed=7, p=self.idx)["mc"]
        b = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=500, seed=7, p=self.idx)["mc"]
        self.assertEqual(a, b)


class DefaultIdxWithoutMarketKey(unittest.TestCase):
    def test_scanner_and_entry_default_to_idx_when_market_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "config.json")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({}, fh)
            code, _, err = run_scan(["universe", "--config", cfg_p, "--no-write"])
            self.assertEqual(code, 1)
            self.assertIn("--from", err)

            out_wl = os.path.join(d, "orb.json")
            code, out, _ = run_scan([
                "orb", "--config", cfg_p, "--offline", BBCA_5M,
                "--now", "2026-11-26 14:30", "--out", out_wl,
            ])
            self.assertEqual(code, 0)
            self.assertIn("WIB", out)
            self.assertIn("Rp ", out)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = entry.main([
                    "check", "BBCA", "--config", cfg_p, "--offline", BBCA_5M,
                    "--now", "2026-11-23 09:35",
                ])
            self.assertEqual(rc, 0)
            self.assertIn("BBCA", buf.getvalue())
            self.assertNotIn("BBCA.JK", buf.getvalue())
            self.assertIn("WIB", buf.getvalue())
            self.assertIn("Rp ", buf.getvalue())


class IdxNewsRssTest(unittest.TestCase):
    # Real RSS fixture cut from https://www.cnbcindonesia.com/market/rss (checked 2026-11-27)
    FEED = {"label": "CNBC Indonesia Market", "url": "https://www.cnbcindonesia.com/market/rss"}

    def _run_news(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = news.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_real_cnbc_rss_matches_bbca_and_ignores_unrelated(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p = os.path.join(d, "config.json")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({"news_feeds": [self.FEED]}, fh)  # no "market" key -> defaults to idx
            uni_p = os.path.join(d, "universe.txt")
            with open(uni_p, "w", encoding="utf-8") as fh:
                fh.write("BBCA|PT Bank Central Asia Tbk.\nTLKM|PT Telkom Indonesia (Persero) Tbk.\n")
            state_p = os.path.join(d, "state", "news.json")
            code, out, err = self._run_news([
                "--tickers", "BBCA", "--config", cfg_p, "--universe", uni_p,
                "--offline", IDX_FIX, "--state", state_p,
                "--hours", "72", "--now", "2026-11-26T12:00:00+07:00",
                "--portfolio", os.path.join(d, "none.json"),
                "--watchlist", os.path.join(d, "none.json"),
                "--plan", os.path.join(d, "none.json"),
            ])
            self.assertEqual(code, 0, err)
            self.assertIn("BBCA", out)
            self.assertIn("CNBC Indonesia Market", out)
            self.assertIn("WIB", out)
            self.assertNotIn("TLKM", out)
            self.assertNotIn("Lelang", out)
            self.assertNotIn("sec_user_agent", out.lower())
            self.assertNotIn("SEC", out)
            with open(state_p, encoding="utf-8") as fh:
                seen = json.load(fh)["seen"]
            self.assertEqual(len(seen), 1)

    def test_company_name_match_and_case_sensitive_ticker(self):
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            '<item><title>Bank Central Asia Rilis Layanan Baru</title>'
            '<link>https://example.com/1</link><guid>id-1</guid>'
            '<pubDate>Thu, 26 Nov 2026 10:00:00 +0700</pubDate>'
            '<description>Layanan digital baru diluncurkan.</description></item>'
            '<item><title>Saham BBCA Menguat Tipis</title>'
            '<link>https://example.com/2</link><guid>id-2</guid>'
            '<pubDate>Thu, 26 Nov 2026 09:00:00 +0700</pubDate>'
            '<description>Perdagangan sesi pagi.</description></item>'
            '<item><title>Berita Umum: goto pasar modal</title>'
            '<link>https://example.com/3</link><guid>id-3</guid>'
            '<pubDate>Thu, 26 Nov 2026 08:00:00 +0700</pubDate>'
            '<description>Tidak terkait emiten.</description></item>'
            '</channel></rss>'
        )
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "feed-cnbc-indonesia-market.xml"), "w", encoding="utf-8") as fh:
                fh.write(xml)
            with gzip.open(BBCA_5M, "rt", encoding="utf-8") as fh:
                chart_doc = json.load(fh)
            with open(os.path.join(d, "chart-BBCA.json"), "w", encoding="utf-8") as fh:
                json.dump(chart_doc, fh)
            cfg_p = os.path.join(d, "config.json")
            with open(cfg_p, "w", encoding="utf-8") as fh:
                json.dump({"news_feeds": [self.FEED]}, fh)
            uni_p = os.path.join(d, "universe.txt")
            with open(uni_p, "w", encoding="utf-8") as fh:
                fh.write("BBCA|PT Bank Central Asia Tbk.\nGOTO|PT GoTo Gojek Tokopedia Tbk.\n")
            code, out, err = self._run_news([
                "--tickers", "BBCA", "GOTO", "--config", cfg_p, "--universe", uni_p,
                "--offline", d, "--state", os.path.join(d, "state.json"),
                "--hours", "48", "--now", "2026-11-26T12:00:00+07:00", "--json",
                "--portfolio", os.path.join(d, "none.json"),
                "--watchlist", os.path.join(d, "none.json"),
                "--plan", os.path.join(d, "none.json"),
            ])
            self.assertEqual(code, 0, err)
            data = json.loads(out)
            self.assertEqual(len(data["items"]), 2)
            self.assertTrue(all(it["touches"] == ["BBCA"] for it in data["items"]))
            self.assertEqual(len(data["moves"]), 1)
            self.assertEqual(data["moves"][0]["ticker"], "BBCA")


class IdxPipelineMoneySafetyTest(unittest.TestCase):
    def _run_mod(self, mod, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = mod.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_pipeline_symbol_and_blocked_real_files(self):
        exitp = load("trader-exit", "exit")
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                os.makedirs("trader", exist_ok=True)
                with open("trader/config.json", "w", encoding="utf-8") as fh:
                    json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}, fh)
                code, _, err = self._run_mod(entry, [
                    "check", "BBCA", "--offline", BBCA_5M, "--now", "2026-11-26 10:30", "--write",
                ])
                self.assertEqual(code, 0, err)
                code, _, err = self._run_mod(exitp, [
                    "plan", "--from", "trader/entry.json", "--now", "2026-11-26 10:30", "--write",
                ])
                self.assertEqual(code, 0, err)
                code, _, err = self._run_mod(size, ["--now", "2026-11-26 10:30", "--write"])
                self.assertEqual(code, 0, err)
                code, _, err = self._run_mod(check, ["--now", "2026-11-26 10:30"])
                self.assertEqual(code, 0, err)

                with open("trader/entry.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["symbol"], "BBCA")
                with open("trader/plan.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["symbol"], "BBCA")
                with open("trader/orders.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["orders"][0]["symbol"], "BBCA")
                with open("trader/state/risk.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["results"][0]["symbol"], "BBCA")

                # (b) blocked: ["BBCA"] must block in check.py and refuse in size.py
                with open("trader/config.json", "w", encoding="utf-8") as fh:
                    json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000,
                               "blocked": ["BBCA"]}, fh)
                code, out, err = self._run_mod(check, ["--now", "2026-11-26 10:30"])
                self.assertEqual(code, 1, out)
                with open("trader/state/risk.json", encoding="utf-8") as fh:
                    r0 = json.load(fh)["results"][0]
                self.assertEqual(r0["verdict"], "BLOCK")
                self.assertTrue(any(r.startswith("blocked:") for r in r0["reasons"]), r0["reasons"])
                code_s, _, err_s = self._run_mod(size, ["--now", "2026-11-26 10:30", "--write"])
                self.assertEqual(code_s, 1)
                self.assertIn("blocked", err_s)
            finally:
                os.chdir(cwd)

    def test_jk_suffix_input_works_at_every_boundary(self):
        exitp = load("trader-exit", "exit")
        alerts_mod = load("trader-alerts", "alerts")
        ticket_mod = load("trader-broker", "ticket")
        idx = market.load("idx")
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                os.makedirs("trader", exist_ok=True)
                with open("trader/config.json", "w", encoding="utf-8") as fh:
                    json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}, fh)
                self.assertEqual(self._run_mod(entry, [
                    "check", "bbca.jk", "--offline", BBCA_5M, "--now", "2026-11-26 10:30", "--write",
                ])[0], 0)
                self.assertEqual(self._run_mod(exitp, [
                    "plan", "--from", "trader/entry.json", "--now", "2026-11-26 10:30", "--write",
                ])[0], 0)
                self.assertEqual(self._run_mod(size, ["--now", "2026-11-26 10:30", "--write"])[0], 0)
                self.assertEqual(self._run_mod(check, ["--now", "2026-11-26 10:30"])[0], 0)
                self.assertEqual(self._run_mod(ticket_mod, [
                    "approve", "--index", "1", "--reply", "yes BBCA.JK", "--now", "2026-11-26 10:30",
                ])[0], 0)
                self.assertEqual(self._run_mod(ticket_mod, [
                    "fill", "--symbol", "bbca.jk", "--side", "buy", "--qty", "100", "--price", "5875",
                    "--now", "2026-11-26 10:30",
                ])[0], 0)
                with open("trader/portfolio.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["positions"][0]["ticker"], "BBCA")
                self.assertEqual(self._run_mod(ticket_mod, [
                    "flatten", "--symbol", "BBCA.JK", "--now", "2026-11-26 10:30",
                ])[0], 0)
                with open("trader/orders.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["orders"][0]["symbol"], "BBCA")
                # check() also normalizes legacy BBCA.JK keys in prices.json and portfolio.json
                res = check.check(
                    [{"symbol": "BBCA", "side": "sell", "qty": "100", "type": "market", "time_in_force": "day"}],
                    {"market": "idx", "budget": 10000000},
                    portfolio={"cash": 9000000, "positions": [{"ticker": "BBCA.JK", "shares": 100}]},
                    prices={"BBCA.JK": 5900},
                    now=check.parse_now("2026-11-26 10:30", p=idx),
                )
                self.assertEqual(res["results"][0]["kind"], "exit")
                # alerts.write_prices normalizes keys
                p_path = os.path.join(d, "trader", "prices.json")
                alerts_mod.write_prices(p_path, {"BBCA.JK": {"price": 5900}}, check.parse_now("2026-11-26 10:30", p=idx), "yahoo", p=idx)
                with open(p_path, encoding="utf-8") as fh:
                    self.assertIn("BBCA", json.load(fh)["prices"])
            finally:
                os.chdir(cwd)

    def test_pipeline_prev_close_and_arb_block_real_files(self):
        exitp = load("trader-exit", "exit")
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                os.makedirs("trader", exist_ok=True)
                with open("trader/config.json", "w", encoding="utf-8") as fh:
                    json.dump({"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}, fh)
                self.assertEqual(self._run_mod(entry, [
                    "check", "BBCA", "--offline", BBCA_5M, "--now", "2026-11-26 10:30", "--write",
                ])[0], 0)
                self.assertEqual(self._run_mod(exitp, [
                    "plan", "--from", "trader/entry.json", "--now", "2026-11-26 10:30", "--write",
                ])[0], 0)
                with open("trader/plan.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["prev_close"], 5825.0)
                self.assertEqual(self._run_mod(size, ["--now", "2026-11-26 10:30", "--write"])[0], 0)
                with open("trader/orders.json", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["orders"][0]["plan"]["prev_close"], 5825.0)

                # (d) stop under ARB (5425 for prev_close=5825 on 2026-11-26) is BLOCKed by check.py
                self.assertEqual(self._run_mod(exitp, [
                    "plan", "--from", "trader/entry.json", "--stop", "price:5400",
                    "--now", "2026-11-26 10:30", "--write",
                ])[0], 0)
                self.assertEqual(self._run_mod(size, ["--now", "2026-11-26 10:30", "--write"])[0], 0)
                code, out, _ = self._run_mod(check, ["--now", "2026-11-26 10:30"])
                self.assertEqual(code, 1, out)
                with open("trader/state/risk.json", encoding="utf-8") as fh:
                    r0 = json.load(fh)["results"][0]
                self.assertEqual(r0["verdict"], "BLOCK")
                self.assertTrue(any(r.startswith("ar_band:") and "ARB" in r for r in r0["reasons"]), r0["reasons"])
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
