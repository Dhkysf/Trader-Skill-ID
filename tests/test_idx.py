"""Offline tests for the IDX market profile and trader-scanner IDX support.

Fixtures under tests/fixtures/idx/ were fetched from Yahoo Finance on 2026-11-27.
"""

import datetime
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
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
alerts = load("trader-alerts", "alerts")
tm = load("trader-timemachine", "timemachine")
size = load("trader-budget", "size")

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
        self.assertIn("Exit plan: BBCA.JK long", out)
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

        # Yahoo .JK only; stooq refused
        self.assertIn("/BBCA.JK?", alerts.yahoo_url("BBCA", p=self.idx))
        with self.assertRaises(alerts.AlertError) as cm:
            alerts.get_quotes(["BBCA"], source="stooq", p=self.idx)
        self.assertIn("stooq has no IDX quotes", str(cm.exception))


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


class IdxTimeMachineRestTest(IdxTimeMachineTest):
    pass

    def test_determinism_and_us_tsla_reproduction(self):
        now_u = tm.parse_now("2026-11-26 16:00", p=self.idx)
        a = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=500, seed=7, p=self.idx)["mc"]
        b = tm.time_machine(self.bbca_text, self._plan(), now_u, replays=500, seed=7, p=self.idx)["mc"]
        self.assertEqual(a, b)

        tsla_gz = os.path.join(FIX, "trader-timemachine", "TSLA-60d5m.json.gz")
        out = io.StringIO()
        with redirect_stdout(out):
            code = tm.main([
                "run", "--symbol", "TSLA", "--date", "2026-10-19", "--entry", "364.18",
                "--stop", "358.32", "--target", "370.04", "--entry-time", "10:15 AM",
                "--offline", tsla_gz, "--now", "2026-10-19 10:50",
            ])
        self.assertEqual(code, 0)
        text = out.getvalue()
        for s in ("29.4 %", "25.5 %", "45.1 %", "fired 33 times: 13 target, 15 stop, 5 neither"):
            self.assertIn(s, text)


if __name__ == "__main__":
    unittest.main()
