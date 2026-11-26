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


if __name__ == "__main__":
    unittest.main()
