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

    def test_from_config(self):
        self.assertIs(market.from_config(None), market.load("idx"))
        self.assertIs(market.from_config("/nonexistent/config.json"), market.load("idx"))
        self.assertIs(market.from_config({}), market.load("idx"))
        self.assertIs(market.from_config({"market": "us"}), market.load("us"))
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "config.json")
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('{}\n')
            self.assertIs(market.from_config(cfg), market.load("idx"))
            with open(cfg, "w", encoding="utf-8") as fh:
                fh.write('{"market": "us"}\n')
            self.assertIs(market.from_config(cfg), market.load("us"))
        with self.assertRaises(ValueError):
            market.from_config({"market": "bogus"})

    def test_money_formatting(self):
        us = market.load("us")
        self.assertEqual(market.money(us, 50), "$50")
        self.assertEqual(market.money(us, 1250), "$1,250")
        self.assertEqual(market.money(us, 46.88), "$46.88")
        self.assertEqual(market.money(us, 2913.44), "$2,913.44")
        self.assertEqual(market.money(us, 0), "$0")
        self.assertEqual(market.money(us, -0.001), "$0")
        self.assertEqual(market.money(us, -50), "$-50")
        idx = market.load("idx")
        self.assertEqual(market.money(idx, 15000), "Rp 15.000")
        self.assertEqual(market.money(idx, 9875000), "Rp 9.875.000")
        self.assertEqual(market.money(idx, 64218.75), "Rp 64.219")
        self.assertEqual(market.money(idx, 0), "Rp 0")
        self.assertEqual(market.money(idx, -0.001), "Rp 0")
        self.assertEqual(market.money({"currency": "EUR"}, 15000), "EUR 15,000")
        self.assertEqual(market.fees(us), (0.0, 0.0))
        self.assertEqual(market.fees(idx), (0.15, 0.25))
        self.assertEqual(market.fees(idx, {"buy_fee_pct": 0.1, "sell_fee_pct": 0.0}), (0.1, 0.0))
        with self.assertRaises(ValueError):
            market.fees(idx, {"buy_fee_pct": -0.1})

    def test_no_second_dst_implementation_in_skills(self):
        skills_dir = os.path.join(ROOT, "skills")
        found = []
        for base, _, files in os.walk(skills_dir):
            for f in files:
                if not f.endswith(".py"):
                    continue
                path = os.path.join(base, f)
                with open(path, encoding="utf-8") as fh:
                    src = fh.read()
                if "def eastern_offset(" in src:
                    found.append(os.path.relpath(path, ROOT))
                    self.assertIn("market.utc_offset(", src, path)
                    self.assertNotIn("def _nth_sunday(", src, path)
        self.assertGreaterEqual(len(found), 9)

    def test_tsla_parity_between_old_usd_and_new_currency_neutral_config(self):
        plan_path = os.path.join(FIX, "trader-budget", "plan-tsla.json")
        old_cfg = {
            "market": "us",
            "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75,
            "max_order_usd": 4000, "min_order_usd": 5,
            "max_loss_per_trade_usd": 50, "max_daily_loss_usd": 150,
            "max_trades_per_day": 3, "max_orders_per_day": 10,
            "min_reward_risk": 1.0, "require_stop": True,
            "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55",
            "fractional": False, "broker": "alpaca", "paper": True, "blocked": [],
            "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
        }
        new_cfg = {
            "market": "us",
            "budget": 5000, "cash_buffer_pct": 10, "max_position_pct": 75,
            "max_order": 4000, "min_order": 5,
            "max_loss_per_trade": 50, "max_daily_loss": 150,
            "max_trades_per_day": 3, "max_orders_per_day": 10,
            "min_reward_risk": 1.0, "require_stop": True,
            "no_entries_before": "09:45", "no_entries_after": "15:30", "flat_by": "15:55",
            "fractional": False, "broker": "alpaca", "paper": True, "blocked": [],
            "allow_options": False, "allow_margin": False, "allow_short": False, "pdt_guard": False,
        }
        with tempfile.TemporaryDirectory() as d:
            none = os.path.join(d, "none")
            outputs = {}
            for tag, cfg_data in (("old", old_cfg), ("new", new_cfg)):
                cfg_p = os.path.join(d, tag + "-cfg.json")
                ord_p = os.path.join(d, "orders.json")
                rsk_p = os.path.join(d, "risk.json")
                with open(cfg_p, "w", encoding="utf-8") as fh:
                    json.dump(cfg_data, fh)
                with redirect_stdout(io.StringIO()):
                    rc1 = size.main(["--plan", plan_path, "--config", cfg_p, "--portfolio", none,
                                     "--now", "2026-10-19 10:15", "--write", ord_p])
                    rc2 = check.main(["--orders", ord_p, "--config", cfg_p, "--portfolio", none,
                                      "--prices", none, "--state", none, "--now", "2026-10-19 10:15", "--out", rsk_p])
                self.assertEqual(rc1, 0)
                self.assertEqual(rc2, 0)
                with open(ord_p, "rb") as fh:
                    orders_bytes = fh.read()
                with open(rsk_p, "rb") as fh:
                    risk_bytes = fh.read()
                outputs[tag] = (orders_bytes, risk_bytes)
            self.assertEqual(outputs["old"][0], outputs["new"][0])
            self.assertEqual(outputs["old"][1], outputs["new"][1])

    def test_new_key_wins_over_usd_alias_with_notice(self):
        merged, notices = market.merge_config(
            {"max_loss_per_trade": 40, "max_loss_per_trade_usd": 80},
            {"max_loss_per_trade": 50},
        )
        self.assertEqual(merged["max_loss_per_trade"], 40)
        self.assertNotIn("max_loss_per_trade_usd", merged)
        self.assertEqual(len(notices), 1)
        self.assertIn("max_loss_per_trade", notices[0])
        self.assertIn("max_loss_per_trade_usd", notices[0])

        with open(os.path.join(FIX, "trader-budget", "plan-tsla.json"), encoding="utf-8") as fh:
            plan = json.load(fh)
        s = size.size_trade(plan, {"market": "us", "budget": 5000, "max_loss_per_trade": 40, "max_loss_per_trade_usd": 80},
                            today="2026-10-19")
        self.assertEqual(s["qty"], 6)
        self.assertEqual(len(s["notices"]), 1)

        with open(os.path.join(FIX, "trader-risk", "orders-tsla.json"), encoding="utf-8") as fh:
            order = json.load(fh)["orders"][0]
        res = check.check([order], {"market": "us", "budget": 5000, "max_loss_per_trade": 40, "max_loss_per_trade_usd": 80},
                          now=check.parse_now("2026-10-19 10:15"))
        self.assertEqual(res["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any("max_loss_per_trade" in w for w in res["warnings"]))


if __name__ == "__main__":
    unittest.main()
