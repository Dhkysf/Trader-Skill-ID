import datetime
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal

from _load import ROOT, load

market = load("trader-core", "market")


# Original reference implementation from skills/trader-scanner/scan.py
def _ref_nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def _ref_eastern_offset(utc):
    y = utc.year
    start = datetime.datetime.combine(_ref_nth_sunday(y, 3, 2), datetime.time(7, 0))
    end = datetime.datetime.combine(_ref_nth_sunday(y, 11, 1), datetime.time(6, 0))
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


class CoreTest(unittest.TestCase):
    def test_a_utc_offset_matches_original_every_30_min_2026_2027(self):
        us = market.load("us")
        cur = datetime.datetime(2026, 1, 1, 0, 0)
        end = datetime.datetime(2027, 12, 31, 23, 30)
        step = datetime.timedelta(minutes=30)
        checked = 0
        while cur <= end:
            self.assertEqual(market.utc_offset(us, cur), _ref_eastern_offset(cur), cur.isoformat())
            cur += step
            checked += 1
        self.assertEqual(checked, 35040)

    def test_b_sessions_holiday_early_close_and_regular(self):
        us = market.load("us")
        self.assertEqual(market.sessions(us, datetime.date(2026, 11, 26)), [])
        self.assertEqual(
            market.sessions(us, datetime.date(2026, 11, 27)),
            [(datetime.time(9, 30), datetime.time(13, 0))],
        )
        self.assertEqual(
            market.sessions(us, datetime.date(2026, 11, 30)),
            [(datetime.time(9, 30), datetime.time(16, 0))],
        )

    def test_c_scanner_help_from_temp_cwd(self):
        scan_py = os.path.join(ROOT, "skills", "trader-scanner", "scan.py")
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, scan_py, "--help"],
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_load_cache_and_unknown_profile(self):
        self.assertIs(market.load("us"), market.load("US"))
        with self.assertRaises(ValueError) as cm:
            market.load("bogus")
        self.assertIn("us", str(cm.exception))

    def test_last_sunday_rule_for_london(self):
        self.assertEqual(market._nth_sunday(2026, 3, -1), datetime.date(2026, 3, 29))
        self.assertEqual(market._nth_sunday(2026, 10, -1), datetime.date(2026, 10, 25))
        self.assertEqual(market._nth_sunday(2026, 12, -1), datetime.date(2026, 12, 27))
        london = {
            "utc_offset_std": 0,
            "utc_offset_dst": 1,
            "dst": {
                "start": {"month": 3, "nth_sunday": -1, "utc_hour": 1},
                "end": {"month": 10, "nth_sunday": -1, "utc_hour": 1},
            },
        }
        self.assertEqual(market.utc_offset(london, datetime.datetime(2026, 3, 29, 0, 59)), 0)
        self.assertEqual(market.utc_offset(london, datetime.datetime(2026, 3, 29, 1, 0)), 1)
        self.assertEqual(market.utc_offset(london, datetime.datetime(2026, 10, 25, 0, 59)), 1)
        self.assertEqual(market.utc_offset(london, datetime.datetime(2026, 10, 25, 1, 0)), 0)

    def test_local_utc_round_trip_and_trading_day(self):
        us = market.load("us")
        utc = datetime.datetime(2026, 10, 19, 14, 15)
        local = market.to_local(us, utc)
        self.assertEqual(local, datetime.datetime(2026, 10, 19, 10, 15))
        self.assertEqual(market.local_to_utc(us, local), utc)
        aware = datetime.datetime(2026, 10, 19, 14, 15, tzinfo=datetime.timezone.utc)
        self.assertEqual(market.to_local(us, aware), local)
        self.assertFalse(market.is_trading_day(us, datetime.date(2026, 10, 17)))
        self.assertFalse(market.is_trading_day(us, datetime.date(2026, 11, 26)))
        self.assertTrue(market.is_trading_day(us, datetime.date(2026, 10, 19)))

    def test_round_tick(self):
        us = market.load("us")
        self.assertEqual(market.round_tick(us, 358.325, "down"), Decimal("358.32"))
        self.assertEqual(market.round_tick(us, 358.325, "up"), Decimal("358.33"))
        self.assertEqual(market.round_tick(us, 358.325, "nearest"), Decimal("358.33"))
        self.assertEqual(market.round_tick(us, 358.321, "nearest"), Decimal("358.32"))
        with self.assertRaises(ValueError):
            market.round_tick(us, 10.0, "invalid")


if __name__ == "__main__":
    unittest.main()
