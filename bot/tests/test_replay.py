"""Replay harness tests: the matcher, the clock, the dust skip, determinism."""
import json
import unittest

from bot import executor as E
from bot.executor import compute_fill_usd
from bot.fill_model import match_maker_print
from bot.replay import hump_shares, simulate_window, spearman


def _entry(**over):
    e = {"startAfterOpenSec": 4, "stopBeforeCloseSec": 75,
         "clipSharesDefault": 10.0, "maxShares": 45.0,
         "minFillPrice": 0.07, "maxFillPrice": 0.55,
         "targetPairCost": 0.965, "maxPairCost": 0.985,
         "maxShareLead": 46.0, "maxUnhedgedUsd": 6.0,
         "dipCurve": {"lo": 0.07, "hi": 0.45, "sharesLo": 33.0, "sharesHi": 8.0},
         "rescuePairCostMax": 0.995, "rescueCeilingPrice": 0.985,
         "minSpacingMoveSec": 0.5, "minSpacingStaticSec": 2.5,
         "includeTakerFee": True, "wholeLadderClips": True}
    e.update(over)
    return e


def _book(ts, outcome, bid, bid_sz=100.0, ask=None):
    ask = bid + 0.01 if ask is None else ask
    other = "Down" if outcome == "Up" else "Up"
    _ = other
    return (ts, outcome, [[bid, bid_sz]], [[ask, 100.0]])


class MatcherTests(unittest.TestCase):
    def test_resting_bid_fills_only_on_sell_at_or_below_after_queue(self):
        order = {"side": "Up", "price": 0.20, "shares_left": 10.0, "queue_ahead": 5.0}
        # BUY print never fills a resting bid.
        self.assertIsNone(match_maker_print(dict(order), {"outcome": "Up", "side": "BUY",
                                                          "price": 0.20, "size": 50.0}))
        # SELL above the limit never fills.
        self.assertIsNone(match_maker_print(dict(order), {"outcome": "Up", "side": "SELL",
                                                          "price": 0.21, "size": 50.0}))
        # SELL at the limit first consumes the queue, then the order.
        o = dict(order)
        hit = match_maker_print(o, {"outcome": "Up", "side": "SELL", "price": 0.20, "size": 8.0})
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit["fills"], 3.0)
        self.assertAlmostEqual(o["queue_ahead"], 0.0)
        self.assertAlmostEqual(o["shares_left"], 7.0)
        # Wrong outcome never fills.
        self.assertIsNone(match_maker_print(dict(order), {"outcome": "Down", "side": "SELL",
                                                          "price": 0.20, "size": 50.0}))

    def test_taker_fee_math(self):
        usd, fee = compute_fill_usd(10.0, 0.50, role="TAKER", include_fee=True)
        self.assertAlmostEqual(fee, 10 * 0.07 * 0.5 * 0.5, places=4)
        self.assertAlmostEqual(usd, round(10 * (0.50 + 0.07 * 0.25), 2))
        usd_m, fee_m = compute_fill_usd(10.0, 0.50, role="MAKER")
        self.assertEqual(fee_m, 0.0)
        self.assertEqual(usd_m, 5.0)


class MultiLevelTests(unittest.TestCase):
    def test_print_size_spent_across_rungs(self):
        # Two rungs, one 10-share SELL print against a 2-share queue: the
        # print can fill at most 8 shares total, not 8 per rung.
        slot = 5_000_000
        book = [_book(slot + t, "Up", 0.20, bid_sz=2.0) for t in range(0, 290, 3)]
        prints = [(slot + 100, "Up", 0.20, 10.0, "SELL", "a")]
        two = simulate_window(slot, "Up", book, prints,
                              "dangerously-skip-permissions-v2.6", _entry(), levels=2,
                              spacing=0.02)
        filled = sum(f["shares"] for f in two["fills"])
        self.assertGreater(filled, 0.0)
        self.assertLessEqual(filled, 10.0)


class QueueFlowTests(unittest.TestCase):
    def test_snapshot_queue_net_of_intervening_flow(self):
        # Snapshot shows 100 ahead, but 95 shares of SELL flow print between
        # the snapshot and the placement: the fresh queue is ~5, so a
        # 10-share print behind a 6-share order fills it.
        slot = 6_000_000
        book = ([_book(slot + 4, "Up", 0.20, bid_sz=100.0)] +
                [_book(slot + 8, "Up", 0.20, bid_sz=100.0)])
        prints = [(slot + 6, "Up", 0.20, 95.0, "SELL", "a"),
                  (slot + 10, "Up", 0.20, 12.0, "SELL", "a")]
        res = simulate_window(slot, "Up", book, prints,
                              "dangerously-skip-permissions-v2.6", _entry(), levels=1)
        self.assertGreater(sum(f["shares"] for f in res["fills"]), 0.0)


class ClockTests(unittest.TestCase):
    def test_no_fills_before_open_or_after_stop(self):
        slot = 1_000_000
        # Book invites a dip at 20c the whole window; prints only outside it.
        book = [_book(slot + t, "Up" if i % 2 == 0 else "Down", 0.20)
                for i, t in enumerate(range(0, 300, 5))]
        prints = [(slot - 50, "Up", 0.20, 500.0, "SELL", "a"),   # before open
                  (slot + 299, "Up", 0.20, 500.0, "SELL", "a")]  # after sweep end
        res = simulate_window(slot, "Up", book, prints,
                              "dangerously-skip-permissions-v2.6", _entry())
        for f in res["fills"]:
            self.assertGreaterEqual(f["ts"], slot + 4)
            self.assertLess(f["ts"], slot + 300 - 12)

    def test_sweep_books_deficit_as_taker(self):
        slot = 2_000_000
        # Fill an Up dip early, then leave Down offered only in the sweep.
        book = ([_book(slot + 10, "Up", 0.20)] +
                [_book(slot + 240, "Down", 0.30)] * 3)
        prints = [(slot + 11, "Up", 0.20, 500.0, "SELL", "a")]
        res = simulate_window(slot, "Down", book, prints,
                              "dangerously-skip-permissions-v2.6", _entry())
        self.assertGreaterEqual(res["n_fills"], 1)
        # The sweep leg crosses (taker) since no bid rested through the sweep.
        roles = {f["role"] for f in res["fills"]}
        self.assertIn("TAKER", roles)


class DustTests(unittest.TestCase):
    def test_dust_bid_skipped_not_taken(self):
        # 49c4b73 regression: bid below minFillPrice must not become a taker fill.
        slot = 3_000_000
        book = [_book(slot + 10, "Up", 0.05, ask=0.07)]
        res = simulate_window(slot, "Up", book, [],
                              "dangerously-skip-permissions-v2.6", _entry())
        self.assertEqual(res["n_fills"], 0)
        self.assertEqual(res["n_taker"], 0)


class DeterminismTests(unittest.TestCase):
    def test_same_input_byte_identical_output(self):
        slot = 4_000_000
        book = [_book(slot + t, "Up" if i % 2 == 0 else "Down", 0.20 + (i % 5) * 0.01)
                for i, t in enumerate(range(0, 290, 3))]
        prints = [(slot + t, "Up" if i % 2 == 0 else "Down", 0.20, 40.0, "SELL", "a")
                  for i, t in enumerate(range(5, 290, 7))]
        kw = dict(slot=slot, winner="Up", book_rows=book, prints=prints,
                  strategy_id="dangerously-skip-permissions-v2.6", entry=_entry())
        a = simulate_window(**kw)
        b = simulate_window(**kw)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_hump_curve_shape(self):
        self.assertEqual(hump_shares(0.08, 45.0), 30.0)
        self.assertAlmostEqual(hump_shares(0.45, 60.0), 48.7)
        self.assertEqual(hump_shares(0.80, 45.0), 30.0)
        self.assertGreater(hump_shares(0.45, 60.0), hump_shares(0.10, 60.0))

    def test_spearman_sanity(self):
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [1, 2, 3, 4]), 1.0)
        self.assertAlmostEqual(spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)
        self.assertIsNone(spearman([1, 1], [2, 1]))


def _v27base(**over):
    e = dict(min_fill=0.07, max_fill=0.48, max_share_lead=100.0,
             max_unhedged_usd=45.0, target_pair_cost=0.960,
             max_pair_cost=0.985, leg1_max_price=0.48,
             leg2_max_price=0.75, elapsed_sec=10.0,
             dip_curve="hump", max_clip=25.0, taker_dip_max=0.45)
    e.update(over)
    return e


def _quotes(up_bid, up_ask, dn_bid, dn_ask):
    return {"Up": {"bid": up_bid, "ask": up_ask},
            "Down": {"bid": dn_bid, "ask": dn_ask}}


class TakerDipTests(unittest.TestCase):
    def test_taker_dip_fires_without_hedge_guard(self):
        # No H1/H2 guards: opposite ask 0.81 does not stop a fresh taker dip.
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
        d = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.40, 0.41, 0.80, 0.81), inv=inv, fill_idx=0,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base())
        self.assertEqual(d.role, "TAKER")
        self.assertEqual(d.sub_reason, "taker-dip-entry")

    def test_taker_dip_respects_threshold(self):
        # best_ask above takerDipEntryMax falls through to the maker path.
        inv = {"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}}
        d = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.40, 0.50, 0.80, 0.81), inv=inv, fill_idx=0,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base())
        self.assertEqual(d.role, "MAKER")


def _deficit_inv(lead_shares=25.0, lead_avg=0.40):
    return {"Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": float(lead_shares), "cost": float(lead_shares) * lead_avg}}


class TakerHedgeLockTests(unittest.TestCase):
    def test_off_by_default_rests_maker(self):
        # No knob: deficit hedge rests at the bid (legacy patient pair).
        d = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.29, 0.31, 0.40, 0.41), inv=_deficit_inv(), fill_idx=1,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base())
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "hedge-equalizer")

    def test_profitable_hedge_crosses_taker(self):
        # Down holds 25 sh @ 40c; Up ask 31c + fee ~1.3c -> pair ~72.3c <= 0.92.
        d = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.29, 0.31, 0.40, 0.41), inv=_deficit_inv(), fill_idx=1,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base(taker_hedge_max_pair_cost=0.92))
        self.assertEqual(d.role, "TAKER")
        self.assertEqual(d.sub_reason, "taker-hedge-lock")
        self.assertLessEqual(d.projected_pair_cost, 0.92)

    def test_unprofitable_hedge_stays_maker(self):
        # Same book, cap 0.70: 72.3c pair does not lock -> rests at bid.
        d = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.29, 0.31, 0.40, 0.41), inv=_deficit_inv(), fill_idx=1,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base(taker_hedge_max_pair_cost=0.70))
        self.assertEqual(d.role, "MAKER")
        self.assertEqual(d.sub_reason, "hedge-equalizer")

    def test_hedge_clip_uncaps_deficit(self):
        # 75-share deficit: default snaps to 25 sh, hedgeMaxClip=50 takes 50.
        inv = _deficit_inv(lead_shares=75.0)
        d25 = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.29, 0.31, 0.40, 0.41), inv=dict(inv), fill_idx=1,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base(taker_hedge_max_pair_cost=0.92))
        self.assertEqual(d25.shares, 25.0)
        d50 = E.evaluate_microstructure_ladder(
            quotes=_quotes(0.29, 0.31, 0.40, 0.41), inv=dict(inv), fill_idx=1,
            minute=0, strategy_id="dangerously-skip-permissions-v2.7",
            **_v27base(taker_hedge_max_pair_cost=0.92, hedge_max_clip=50.0))
        self.assertEqual(d50.shares, 50.0)
        self.assertEqual(d50.role, "TAKER")


if __name__ == "__main__":
    unittest.main()
