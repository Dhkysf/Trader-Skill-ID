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
entry = load("trader-entry", "entry")
timemachine = load("trader-timemachine", "timemachine")
alerts = load("trader-alerts", "alerts")
ticket = load("trader-broker", "ticket")


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
        self.assertEqual(market.money(usd, 50), "$50.00")
        self.assertEqual(market.money(usd, 1250), "$1,250.00")
        self.assertEqual(market.money(usd, 46.88), "$46.88")
        self.assertEqual(market.money(usd, 0), "$0.00")
        self.assertEqual(market.money(usd, -0.001), "$0.00")
        idx = market.load("idx")
        self.assertEqual(market.money(idx, 15000), "Rp 15.000")
        self.assertEqual(market.money(idx, 9875000), "Rp 9.875.000")
        self.assertEqual(market.money(idx, 64218.75), "Rp 64.219")
        self.assertEqual(market.money(idx, 0), "Rp 0")
        self.assertEqual(market.money(idx, -0.001), "Rp 0")
        self.assertEqual(market.money({"currency": "EUR"}, 15000), "EUR 15,000.00")
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

    def test_base_symbol(self):
        idx = market.load("idx")
        self.assertEqual(market.base_symbol(idx, "bbca.jk"), "BBCA")
        self.assertEqual(market.base_symbol(idx, " BBCA.JK "), "BBCA")
        self.assertEqual(market.base_symbol(idx, "BBCA"), "BBCA")
        self.assertEqual(market.base_symbol(idx, ".JK"), ".JK")
        self.assertEqual(market.base_symbol(idx, None), "")
        self.assertEqual(market.base_symbol({"yahoo_suffix": ""}, "BRK.B"), "BRK.B")


class PrecisionTest(unittest.TestCase):
    def _use_fx_profile(self):
        mods = [market]
        if "market" in sys.modules and sys.modules["market"] is not market:
            mods.append(sys.modules["market"])
        prof_dir = os.path.join(FIX, "profiles")
        for m in mods:
            orig_dir = m.MARKETS_DIR
            orig_cache = dict(m._CACHE)
            m.MARKETS_DIR = prof_dir
            self.addCleanup(setattr, m, "MARKETS_DIR", orig_dir)
            self.addCleanup(lambda mod=m, snap=orig_cache: (mod._CACHE.clear(), mod._CACHE.update(snap)))
        return market.load("fx-test")

    def _fx_cfg(self):
        return {
            "market": "fx-test",
            "budget": 200000,
            "max_loss_per_trade": 500,
            "max_position_pct": 100,
            "cash_buffer_pct": 0,
            "min_reward_risk": 1.5,
            "min_order": 1,
        }

    def _fx_plan(self):
        return {
            "symbol": "EURUSD",
            "side": "buy",
            "market": "fx-test",
            "date": "2026-11-23",
            "setup": "orb",
            "entry": 1.0850,
            "stop": 1.0820,
            "target": 1.0910,
        }

    def test_fx_size_and_risk_pass(self):
        self._use_fx_profile()
        cfg = self._fx_cfg()
        plan = self._fx_plan()
        s = size.size_trade(plan, cfg, today="2026-11-23")
        self.assertGreater(s["qty"], 0)
        self.assertEqual(s["reward_risk"], 2.0)
        self.assertEqual(s["risk_per_share"], 0.003)
        order = size.bracket_order(s)
        self.assertIsNotNone(order)
        res = check.check([order], cfg, today="2026-11-23")
        self.assertEqual(res["results"][0]["verdict"], "PASS", res["results"][0]["reasons"])
        self.assertEqual(res["results"][0]["entry_ref"], 1.085)
        self.assertEqual(res["results"][0]["reward_risk"], 2.0)

    def test_fx_ticket_format_and_parse_yes(self):
        fx = self._use_fx_profile()
        cfg = self._fx_cfg()
        s = size.size_trade(self._fx_plan(), cfg, today="2026-11-23")
        order = size.bracket_order(s)
        text = ticket.plain(order, p=fx, cfg=cfg)
        self.assertIn("1.08500", text)
        self.assertIn("1.08200", text)
        self.assertIn("1.09100", text)
        self.assertIn("$", text)
        ok_yes, _ = ticket.parse_yes("yes 1.085", order, p=fx, cfg=cfg)
        self.assertTrue(ok_yes)
        ok_bad, _ = ticket.parse_yes("yes 1.084", order, p=fx, cfg=cfg)
        self.assertFalse(ok_bad)

    def test_price_vs_money_formatters(self):
        fx = self._use_fx_profile()
        idx = market.load("idx")
        self.assertEqual(market.price(fx, 1.0), "1.00000")
        self.assertEqual(market.price(fx, 1.085), "1.08500")
        self.assertEqual(market.price(idx, 9875), "Rp 9.875")
        self.assertEqual(market.money(fx, 10000), "$10,000.00")
        self.assertEqual(market.money(fx, 31.2), "$31.20")
        self.assertEqual(market.money(idx, 9875000), "Rp 9.875.000")

    def test_fx_entry_and_timemachine_precision(self):
        fx = self._use_fx_profile()
        self.assertEqual(entry.r2(1.0850, 5), 1.085)
        raw_plan = dict(self._fx_plan(), entry_time="00:30")
        norm = timemachine.normalize_plan(raw_plan, p=fx)
        self.assertEqual(norm["risk_per_share"], 0.003)
        pool = [[] if i == 0 else [(1.0, 1.0005, 0.9995, 1.0001)] for i in range(10)]
        sim = timemachine.simulate(pool, 1.0850, 1.0820, 1.0910, 1, 9, replays=20, seed=19, price_decimals=5)
        self.assertGreater(sim["median_close"], 1.0)
        self.assertNotEqual(sim["median_close"], round(sim["median_close"], 2))
        self.assertEqual(len(str(sim["sample_paths"][0][1]).split(".")[1]) <= 5, True)

    def test_fx_profile_cleanup_no_leak(self):
        self.assertNotIn("fx-test", market.available())


class CapabilitiesTest(unittest.TestCase):
    def _use_fx_profile(self):
        mods = [market]
        if "market" in sys.modules and sys.modules["market"] is not market:
            mods.append(sys.modules["market"])
        prof_dir = os.path.join(FIX, "profiles")
        for m in mods:
            orig_dir = m.MARKETS_DIR
            orig_cache = dict(m._CACHE)
            m.MARKETS_DIR = prof_dir
            self.addCleanup(setattr, m, "MARKETS_DIR", orig_dir)
            self.addCleanup(lambda mod=m, snap=orig_cache: (mod._CACHE.clear(), mod._CACHE.update(snap)))
        return market.load("fx-test")

    def test_idx_short_and_margin_still_blocked_with_old_reasons(self):
        cfg = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}
        now = check.parse_now("2026-11-23 10:15", p=market.load("idx"))
        buy_ord = {
            "symbol": "BBCA", "side": "buy", "qty": "300", "type": "limit",
            "limit_price": "9875", "time_in_force": "day", "market": "idx",
            "stop_loss_stop_price": "9700", "take_profit_limit_price": "10225",
        }
        sell_ord = dict(buy_ord, side="sell")
        res_sh = check.check([sell_ord], dict(cfg, allow_short=True), now=now)
        self.assertEqual(res_sh["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any("short selling is not supported on IDX" in r for r in res_sh["results"][0]["reasons"]))

        res_sh_off = check.check([sell_ord], cfg, now=now)
        self.assertEqual(res_sh_off["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any("short selling is off" in r for r in res_sh_off["results"][0]["reasons"]))

        res_mg = check.check([buy_ord], dict(cfg, budget=1000000, allow_margin=True), now=now)
        self.assertEqual(res_mg["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any("margin orders are not allowed on IDX" in r for r in res_mg["results"][0]["reasons"]))

    def test_idx_symbol_pattern_blocks_warrant_and_allows_jk_suffix(self):
        cfg = {"market": "idx", "budget": 10000000, "max_loss_per_trade": 100000}
        now = check.parse_now("2026-11-23 10:15", p=market.load("idx"))
        warrant = {
            "symbol": "BUKA-W", "side": "buy", "qty": "100", "type": "limit",
            "limit_price": "100", "time_in_force": "day", "market": "idx",
            "stop_loss_stop_price": "90", "take_profit_limit_price": "120",
        }
        res_w = check.check([warrant], cfg, now=now)
        self.assertEqual(res_w["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(
            "only ordinary shares (4-letter codes); warrants and rights (-W, -R) are not supported" in r
            for r in res_w["results"][0]["reasons"]
        ))

        jk_ord = {
            "symbol": "bbca.jk", "side": "buy", "qty": "300", "type": "limit",
            "limit_price": "9875", "time_in_force": "day", "market": "idx",
            "stop_loss_stop_price": "9700", "take_profit_limit_price": "10225",
        }
        res_jk = check.check([jk_ord], cfg, now=now)
        self.assertEqual(res_jk["results"][0]["verdict"], "PASS", res_jk["results"][0]["reasons"])

    def test_fx_short_eurusd_passes_and_swaps_fees(self):
        self._use_fx_profile()
        cfg = {
            "market": "fx-test",
            "budget": 200000,
            "max_loss_per_trade": 2000,
            "max_position_pct": 100,
            "cash_buffer_pct": 0,
            "min_reward_risk": 1.5,
            "min_order": 1,
            "buy_fee_pct": 0.1,
            "sell_fee_pct": 0.5,
        }
        sell_ord = {
            "symbol": "EURUSD", "side": "sell", "qty": "100000", "type": "limit",
            "limit_price": "1.0850", "time_in_force": "day", "market": "fx-test",
            "stop_loss_stop_price": "1.0880", "take_profit_limit_price": "1.0790",
        }
        res_off = check.check([sell_ord], cfg, today="2026-11-23")
        self.assertEqual(res_off["results"][0]["verdict"], "BLOCK")
        self.assertTrue(any(r.startswith("short:") for r in res_off["results"][0]["reasons"]))

        res_on = check.check([sell_ord], dict(cfg, allow_short=True), today="2026-11-23")
        r = res_on["results"][0]
        self.assertEqual(r["verdict"], "PASS", r["reasons"])
        # Swapped fees for short: entry 1.0850 * sell_fee (0.5%) + stop 1.0880 * buy_fee (0.1%)
        self.assertEqual(r["max_loss"], 951.3)

        sell_x = dict(sell_ord, symbol="EURUSD=X")
        res_x = check.check([sell_x], dict(cfg, allow_short=True), today="2026-11-23")
        self.assertEqual(res_x["results"][0]["verdict"], "PASS", res_x["results"][0]["reasons"])

    def test_alerts_three_sessions_and_ticket_lot_default(self):
        p3 = {
            "id": "three", "display_name": "THREE", "utc_offset_std": 0, "utc_offset_dst": 0,
            "sessions": {"mon": [["08:00", "10:00"], ["11:00", "13:00"], ["14:00", "16:00"]]},
            "holidays": {}, "currency": "USD", "price_decimals": 2,
        }
        st1 = alerts.market_status(datetime.datetime(2026, 11, 23, 10, 30), p=p3)
        self.assertFalse(st1["open"])
        self.assertEqual(st1["status"], "session break")
        st2 = alerts.market_status(datetime.datetime(2026, 11, 23, 15, 0), p=p3)
        self.assertTrue(st2["open"])
        self.assertEqual(st2["status"], "session 3")

        ord10 = {"symbol": "EURUSD", "side": "buy", "qty": "10", "type": "limit",
                 "limit_price": "1.08", "stop_loss_stop_price": "1.07"}
        txt = ticket.plain(ord10, p=p3, cfg={})
        self.assertIn("10 shares", txt)
        self.assertNotIn("lots", txt)

    def test_overnight_and_24h_sessions(self):
        overnight = {
            "id": "night", "display_name": "NIGHT", "utc_offset_std": 0, "utc_offset_dst": 0,
            "sessions": {"mon": [["22:00", "06:00"]]}, "holidays": {},
        }
        mon = datetime.date(2026, 11, 23)
        self.assertEqual(
            market.session_windows(overnight, mon),
            [(datetime.datetime(2026, 11, 23, 22, 0), datetime.datetime(2026, 11, 24, 6, 0))],
        )
        self.assertTrue(market.in_session(overnight, datetime.datetime(2026, 11, 23, 23, 30)))
        self.assertTrue(market.in_session(overnight, datetime.datetime(2026, 11, 24, 5, 0)))
        self.assertFalse(market.in_session(overnight, datetime.datetime(2026, 11, 24, 6, 0)))
        self.assertFalse(market.in_session(overnight, datetime.datetime(2026, 11, 23, 21, 59)))
        self.assertFalse(market.in_session(overnight, datetime.datetime(2026, 11, 24, 12, 0)))

        self.assertTrue(alerts.market_status(datetime.datetime(2026, 11, 23, 23, 30), p=overnight)["open"])
        self.assertTrue(alerts.market_status(datetime.datetime(2026, 11, 24, 5, 0), p=overnight)["open"])
        self.assertFalse(alerts.market_status(datetime.datetime(2026, 11, 24, 12, 0), p=overnight)["open"])

        fx = self._use_fx_profile()
        self.assertTrue(market.in_session(fx, datetime.datetime(2026, 11, 23, 0, 0)))
        self.assertTrue(market.in_session(fx, datetime.datetime(2026, 11, 23, 12, 0)))
        self.assertTrue(market.in_session(fx, datetime.datetime(2026, 11, 23, 23, 59)))


if __name__ == "__main__":
    unittest.main()
