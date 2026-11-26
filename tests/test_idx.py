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

from _load import FIX, load

market = load("trader-core", "market")
scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
alerts = load("trader-alerts", "alerts")

IDX_FIX = os.path.join(FIX, "idx")
BBCA_5M = os.path.join(IDX_FIX, "BBCA.JK-5m-60d-2026-11-27.json.gz")
SPARK_DAILY = os.path.join(IDX_FIX, "spark-daily-2026-11-27.json.gz")
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
        self.assertIn("IDR 5,000,000,000+ traded value", out)
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


if __name__ == "__main__":
    unittest.main()
