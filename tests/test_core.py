import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal

from _load import FIX, ROOT, load

market = load("trader-core", "market")
size = load("trader-budget", "size")
check = load("trader-risk", "check")


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
        # Inline New York DST rule (for future forex sessions; mirrors original transition)
        ny_rule = {
            "utc_offset_std": -5,
            "utc_offset_dst": -4,
            "dst": {
                "start": {"month": 3, "nth_sunday": 2, "utc_hour": 7},
                "end": {"month": 11, "nth_sunday": 1, "utc_hour": 6},
            },
        }
        cur = datetime.datetime(2026, 1, 1, 0, 0)
        end = datetime.datetime(2027, 12, 31, 23, 30)
        step = datetime.timedelta(minutes=30)
        checked = 0
        while cur <= end:
            self.assertEqual(market.utc_offset(ny_rule, cur), _ref_eastern_offset(cur), cur.isoformat())
            cur += step
            checked += 1
        self.assertEqual(checked, 35040)

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
        self.assertIs(market.load("idx"), market.load("IDX"))
        with self.assertRaises(ValueError) as cm:
            market.load("bogus")
        self.assertIn("idx", str(cm.exception))

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
        idx = market.load("idx")
        utc = datetime.datetime(2026, 11, 23, 2, 35)
        local = market.to_local(idx, utc)
        self.assertEqual(local, datetime.datetime(2026, 11, 23, 9, 35))
        self.assertEqual(market.local_to_utc(idx, local), utc)
        aware = datetime.datetime(2026, 11, 23, 2, 35, tzinfo=datetime.timezone.utc)
        self.assertEqual(market.to_local(idx, aware), local)
        self.assertFalse(market.is_trading_day(idx, datetime.date(2026, 11, 21)))
        self.assertFalse(market.is_trading_day(idx, datetime.date(2026, 8, 17)))
        self.assertTrue(market.is_trading_day(idx, datetime.date(2026, 11, 23)))

    def test_round_tick(self):
        idx = market.load("idx")
        self.assertEqual(market.round_tick(idx, 5010, "down"), Decimal("5000"))
        self.assertEqual(market.round_tick(idx, 5010, "up"), Decimal("5025"))
        self.assertEqual(market.round_tick(idx, 5015, "nearest"), Decimal("5025"))
        flat = {"tick": 0.01}
        self.assertEqual(market.round_tick(flat, 358.325, "down"), Decimal("358.32"))
        self.assertEqual(market.round_tick(flat, 358.325, "up"), Decimal("358.33"))
        with self.assertRaises(ValueError):
            market.round_tick(idx, 5000, "invalid")

    def test_from_config(self):
        self.assertIs(market.from_config(None), market.load("idx"))
        self.assertIs(market.from_config("/nonexistent/config.json"), market.load("idx"))
        self.assertIs(market.from_config({}), market.load("idx"))
        self.assertIs(market.from_config({"market": "idx"}), market.load("idx"))
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "config.json")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('{}\n')
            self.assertIs(market.from_config(cfg), market.load("idx"))
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('{"market": "idx"}\n')
            self.assertIs(market.from_config(cfg), market.load("idx"))
        with self.assertRaises(ValueError):
            market.from_config({"market": "bogus"})

    def test_money_formatting(self):
        usd = {"currency": "USD"}
        self.assertEqual(market.money(usd, 50), "$50")
        self.assertEqual(market.money(usd, 1250), "$1,250")
        self.assertEqual(market.money(usd, 46.88), "$46.88")
        self.assertEqual(market.money(usd, 0), "$0")
        self.assertEqual(market.money(usd, -0.001), "$0")
        idx = market.load("idx")
        self.assertEqual(market.money(idx, 15000), "Rp 15.000")
        self.assertEqual(market.money(idx, 9875000), "Rp 9.875.000")
        self.assertEqual(market.money(idx, 64218.75), "Rp 64.219")
        self.assertEqual(market.money(idx, 0), "Rp 0")
        self.assertEqual(market.money(idx, -0.001), "Rp 0")
        self.assertEqual(market.money({"currency": "EUR"}, 15000), "EUR 15,000")
        self.assertEqual(market.fees(idx), (0.15, 0.25))
        self.assertEqual(market.fees(idx, {"buy_fee_pct": 0.1, "sell_fee_pct": 0.0}), (0.1, 0.0))
        with self.assertRaises(ValueError):
            market.fees(idx, {"buy_fee_pct": -0.1})

    def test_no_second_dst_implementation_in_skills(self):
        skills_dir = os.path.join(ROOT, "skills")
        for base, _, files in os.walk(skills_dir):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(base, f)
                if os.path.relpath(path, ROOT) == os.path.join("skills", "trader-core", "market.py"):
                    continue
                with open(path, encoding="utf-8") as fh:
                    src = fh.read()
                self.assertNotIn("def _nth_sunday(", src, path)
                self.assertNotIn("def eastern_offset(", src, path)

    def test_new_key_wins_over_usd_alias_with_notice(self):
        merged, notices = market.merge_config(
            {"max_loss_per_trade": 40000, "max_loss_per_trade_usd": 80000},
            {"max_loss_per_trade": 50000},
        )
        self.assertEqual(merged["max_loss_per_trade"], 40000)
        self.assertNotIn("max_loss_per_trade_usd", merged)
        self.assertEqual(len(notices), 1)
        self.assertIn("max_loss_per_trade", notices[0])
        self.assertIn("max_loss_per_trade_usd", notices[0])

        with open(os.path.join(FIX, "idx", "plan-bbca.json"), encoding="utf-8") as fh:
            plan = json.load(fh)
        s = size.size_trade(plan, {"market": "idx", "budget": 10000000, "max_loss_per_trade": 40000, "max_loss_per_trade_usd": 80000},
                            today="2026-11-23")
        self.assertEqual(s["lots"], 1)
        self.assertEqual(len(s["notices"]), 1)


if __name__ == "__main__":
    unittest.main()
