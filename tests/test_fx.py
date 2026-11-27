import argparse
import datetime
from decimal import Decimal
import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest

from _load import ROOT, load

market = load("trader-core", "market")
scan = load("trader-scanner", "scan")
entry = load("trader-entry", "entry")
exit_mod = load("trader-exit", "exit")
alerts = load("trader-alerts", "alerts")

FX_DIR = os.path.join(ROOT, "tests", "fixtures", "fx")
EURUSD_GZ = os.path.join(FX_DIR, "EURUSD=X-5m-60d-2026-11-27.json.gz")
USDJPY_GZ = os.path.join(FX_DIR, "USDJPY=X-5m-60d-2026-11-27.json.gz")
USDIDR_GZ = os.path.join(FX_DIR, "USDIDR=X-5m-60d-2026-11-27.json.gz")


class FxProfileTest(unittest.TestCase):
    def setUp(self):
        self.fx = market.load("fx")
        self.idx = market.load("idx")
        self.cfg = {"market": "fx", "allow_short": True, "allow_margin": True}

    def test_london_dst_in_ny_time(self):
        # Winter: both std -> London 08:00 UTC = 03:00 ET
        self.assertEqual(market.orb_session_open(self.fx, "london", datetime.date(2026, 1, 15)),
                         datetime.datetime(2026, 1, 15, 3, 0))
        # Summer: both DST -> London 08:00 BST (07:00 UTC) = 03:00 ET
        self.assertEqual(market.orb_session_open(self.fx, "london", datetime.date(2026, 7, 15)),
                         datetime.datetime(2026, 7, 15, 3, 0))
        # March gap week: US switched (2nd Sun Mar 8), UK not yet (last Sun Mar 29) -> 04:00 ET
        self.assertEqual(market.orb_session_open(self.fx, "london", datetime.date(2026, 3, 18)),
                         datetime.datetime(2026, 3, 18, 4, 0))

    def test_24_5_market_status(self):
        sun_closed = market.local_to_utc(self.fx, datetime.datetime(2026, 11, 22, 16, 59))
        st_sc = alerts.market_status(sun_closed, p=self.fx)
        self.assertFalse(st_sc["open"])
        self.assertEqual(st_sc["next_open"], "2026-11-22 17:00")

        sun_open = market.local_to_utc(self.fx, datetime.datetime(2026, 11, 22, 17, 0))
        self.assertTrue(alerts.market_status(sun_open, p=self.fx)["open"])

        fri_open = market.local_to_utc(self.fx, datetime.datetime(2026, 11, 27, 16, 59))
        self.assertTrue(alerts.market_status(fri_open, p=self.fx)["open"])

        fri_closed = market.local_to_utc(self.fx, datetime.datetime(2026, 11, 27, 17, 0))
        st_fc = alerts.market_status(fri_closed, p=self.fx)
        self.assertFalse(st_fc["open"])
        self.assertEqual(st_fc["next_open"], "2026-11-29 17:00")

    def test_calendar_note_disabled(self):
        self.assertIsNone(market.calendar_note(self.fx, "2026-12-25"))
        self.assertIsNone(market.calendar_note(self.fx, "2030-01-01"))

    def test_pair_helpers_require_symbol_loudly(self):
        for fn, args in (
            (market.price, (self.fx, 1.12345)),
            (market.price_tol, (self.fx,)),
            (market.round_tick, (self.fx, 1.12345)),
            (market.pip_size, (self.fx,)),
            (market.price_decimals, (self.fx,)),
            (market.tick_size, (self.fx, 1.12345)),
        ):
            with self.assertRaises(ValueError):
                fn(*args)

    def test_jpy_and_usdidr_precision(self):
        with gzip.open(USDIDR_GZ, "rt", encoding="utf-8") as fh:
            meta = json.load(fh)["chart"]["result"][0]["meta"]
        self.assertEqual(market.price_decimals(self.fx, "USDIDR"), meta["priceHint"])
        self.assertEqual(market.price(self.fx, 15850.5, symbol="USDIDR"), "15,850.5000")
        self.assertEqual(market.price(self.fx, 155.23, symbol="USDJPY=X"), "155.230")

        # exit.py plan on USDJPY=X -> 3 decimals
        a = argparse.Namespace(
            from_path=None, symbol="USDJPY=X", entry=155.23, or_high=155.50, or_low=155.10,
            or_minutes=15, setup="orb", date="2026-11-26", time="04:00 AM", entry_bar=4,
            interval="5m", side="sell", stop="or-high", target="2R", flat_by=None,
            prev_close=None, config=None, offline=None, now="2026-11-26 04:05",
        )
        with unittest.mock.patch.object(exit_mod, "read_config", return_value=self.cfg):
            plan, _ = exit_mod.build_plan(a, market.local_to_utc(self.fx, datetime.datetime(2026, 11, 26, 4, 5)))
        lines = "\n".join(exit_mod.describe(plan, p=self.fx))
        self.assertIn("155.230", lines)
        self.assertIn("pips", lines)

        # alerts.py evaluate on USDJPY=X -> 3 decimals
        st = alerts.market_status(market.local_to_utc(self.fx, datetime.datetime(2026, 11, 26, 4, 5)), p=self.fx)
        rings, _ = alerts.evaluate(
            [{"id": "jpy-t", "symbol": "USDJPY=X", "type": "above", "price": 155.20}],
            {"USDJPY": {"price": 155.23}}, st, {}, datetime.datetime(2026, 11, 26, 9, 5), p=self.fx,
        )
        self.assertEqual(len(rings), 1)
        self.assertIn("155.230", rings[0]["message"])

    def test_unsupported_pair_refused_everywhere(self):
        with self.assertRaises(scan.ScanError) as ctx1:
            scan.read_symbols(argparse.Namespace(symbols="EURGBP", watchlist=None, universe=None, limit=None), p=self.fx)
        self.assertIn("EURGBP is not a supported pair yet", str(ctx1.exception))

        ch = {"symbol": "EURGBP", "bars": [], "data_time": None}
        with self.assertRaises(entry.EntryError) as ctx2:
            entry.evaluate(ch, datetime.datetime(2026, 11, 26, 9, 0), cfg=self.cfg, p=self.fx)
        self.assertIn("EURGBP is not a supported pair yet", str(ctx2.exception))

        a = argparse.Namespace(
            from_path=None, symbol="EURGBP", entry=0.85, or_high=0.86, or_low=0.84,
            or_minutes=15, setup="orb", date="2026-11-26", time="04:00 AM", entry_bar=4,
            interval="5m", side="sell", stop="or-high", target="2R", flat_by=None,
            prev_close=None, config=None, offline=None, now="2026-11-26 04:05",
        )
        with unittest.mock.patch.object(exit_mod, "read_config", return_value=self.cfg):
            with self.assertRaises(exit_mod.PlanError) as ctx3:
                exit_mod.build_plan(a, datetime.datetime(2026, 11, 26, 4, 5))
        self.assertIn("EURGBP is not a supported pair yet", str(ctx3.exception))

        with self.assertRaises(alerts.AlertError) as ctx4:
            alerts.get_quotes(["EURGBP"], offline=FX_DIR, p=self.fx)
        self.assertIn("EURGBP is not a supported pair yet", str(ctx4.exception))

    def test_eurusd_short_orb_trigger_and_exit_plan_in_pips(self):
        ch = entry.get_chart("EURUSD=X", "5m", offline=EURUSD_GZ, p=self.fx)
        now_utc = market.local_to_utc(self.fx, datetime.datetime(2026, 11, 26, 4, 0))
        res = entry.evaluate(ch, now_utc, setup="orb", or_minutes=15, cfg=self.cfg, p=self.fx,
                             side="sell", session_name="london")
        self.assertEqual(res["status"], "triggered")
        self.assertEqual(res["side"], "sell")
        self.assertLess(res["trigger"]["price"], res["opening_range"]["low"])

        doc = entry.entry_doc(res, now_utc)
        c = exit_mod.compute(doc["price"], "or_high", None, "r", Decimal("2"),
                             or_high=doc["opening_range"]["high"], or_low=doc["opening_range"]["low"],
                             p=self.fx, side="sell", symbol="EURUSD")
        self.assertGreater(c["stop"], c["entry"])
        self.assertLess(c["target"], c["entry"])
        pip = market.pip_size(self.fx, "EURUSD")
        self.assertGreater(float(c["risk"] / pip), 0.0)
        flat_by, _ = exit_mod.resolve_flat_by(datetime.date(2026, 11, 26), None, self.cfg,
                                              datetime.time(3, 20), p=self.fx)
        self.assertEqual(flat_by, "16:45")

    def test_idx_short_still_refused(self):
        with self.assertRaises(entry.EntryError) as ctx1:
            entry._opts(argparse.Namespace(side="sell", setup="orb", level=None, min_volume_x=None,
                                           or_minutes=15, interval="5m", session=None), {"market": "idx"})
        self.assertIn("v2 plans longs only", str(ctx1.exception))

        with self.assertRaises(exit_mod.PlanError) as ctx2:
            exit_mod.gather(argparse.Namespace(symbol="BBCA", from_path=None, side="sell", entry=9800,
                                               or_high=9900, or_low=9700, or_minutes=15, setup="orb",
                                               date="2026-11-23", time="09:35 AM", entry_bar=6, interval="5m"),
                            p=self.idx, cfg={"market": "idx"})
        self.assertIn("v2 plans longs only", str(ctx2.exception))


class FxCliTest(unittest.TestCase):
    def _run_cli(self, skill, script, args, cfg):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "trader"), exist_ok=True)
            with open(os.path.join(d, "trader", "config.json"), "w", encoding="utf-8") as fh:
                json.dump(cfg, fh)
            cmd = [sys.executable, os.path.join(ROOT, "skills", skill, script)] + args
            return subprocess.run(cmd, cwd=d, capture_output=True, text=True)

    def test_exit_cli_fx_sell_plan(self):
        r = self._run_cli(
            "trader-exit", "exit.py",
            ["plan", "--symbol", "EURUSD", "--side", "sell", "--entry", "1.09745",
             "--stop", "price:1.09830", "--target", "2R", "--date", "2026-11-26",
             "--now", "2026-11-26 03:25"],
            {"market": "fx", "allow_short": True},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EURUSD short", r.stdout)
        self.assertIn("1.09745", r.stdout)
        self.assertIn("1.09830", r.stdout)
        self.assertIn("8.5 pips", r.stdout)
        self.assertIn("17.0 pips", r.stdout)

    def test_exit_cli_fx_example_config(self):
        with open(os.path.join(ROOT, "skills", "trader-budget", "config.fx.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        r = self._run_cli(
            "trader-exit", "exit.py",
            ["plan", "--symbol", "EURUSD", "--side", "sell", "--entry", "1.09745",
             "--stop", "price:1.09830", "--target", "2R", "--date", "2026-11-26",
             "--now", "2026-11-26 03:25"],
            cfg,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("EURUSD short", r.stdout)

    def test_entry_cli_fx_sell_check(self):
        r = self._run_cli(
            "trader-entry", "entry.py",
            ["check", "EURUSD", "--side", "sell", "--session", "london",
             "--offline", EURUSD_GZ, "--now", "2026-11-26 05:00"],
            {"market": "fx", "allow_short": True},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue("TRIGGERED" in r.stdout or "WAITING" in r.stdout, r.stdout)

    def test_idx_cli_sell_still_refused(self):
        r = self._run_cli(
            "trader-exit", "exit.py",
            ["plan", "--symbol", "BBCA", "--side", "sell", "--entry", "9800",
             "--stop", "price:9900", "--date", "2026-11-26", "--now", "2026-11-26 10:00"],
            {"market": "idx", "allow_short": True},
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("v2 plans longs only", r.stderr)

    def test_null_time_limits_everywhere(self):
        ch = entry.get_chart("EURUSD=X", "5m", offline=EURUSD_GZ, p=market.load("fx"))
        res = entry.evaluate(
            ch, market.local_to_utc(market.load("fx"), datetime.datetime(2026, 11, 26, 4, 0)),
            setup="orb", or_minutes=15,
            cfg={"market": "fx", "allow_short": True, "no_entries_before": None, "no_entries_after": None},
            side="sell", session_name="london",
        )
        self.assertEqual(res["status"], "triggered")
        self.assertIsNone(res["no_entries_before"])
        self.assertIsNone(res["no_entries_after"])

        flat_by, note = exit_mod.resolve_flat_by(
            datetime.date(2026, 11, 26), None, {"market": "fx", "flat_by": None},
            datetime.time(3, 20), p=market.load("fx"),
        )
        self.assertIsNone(flat_by)
        self.assertEqual(note, "")

        rules = alerts.rules_from_plan(
            {"symbol": "EURUSD", "market": "fx", "side": "sell", "stop": 1.09830, "target": 1.09575, "flat_by": None},
            p=market.load("fx"),
        )
        self.assertEqual([x["type"] for x in rules], ["above", "below"])

        check_mod = load("trader-risk", "check")
        reasons, warns = check_mod.window_check(
            datetime.datetime(2026, 11, 26, 3, 25),
            {"market": "fx", "no_entries_before": None, "no_entries_after": "16:30"},
        )
        self.assertEqual((reasons, warns), ([], []))

    def test_scanner_cli_fx_short_wording(self):
        r = self._run_cli(
            "trader-scanner", "scan.py",
            ["orb", "--session", "london", "--offline", FX_DIR, "--now", "2026-11-26 05:00"],
            {"market": "fx", "allow_short": True},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("closed below the range low", r.stdout)
        self.assertIn("under", r.stdout)
        self.assertIn("short", r.stdout)
        self.assertNotIn("closed above their opening-range high", r.stdout)
        self.assertNotIn("% over", r.stdout)


if __name__ == "__main__":
    unittest.main()
