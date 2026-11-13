import unittest

from bot.executor import evaluate_microstructure_ladder, select_ladder_clip


class TestDspV22ConfidenceSizing(unittest.TestCase):
    def test_preflight_gate_no_longer_blocks_a_lone_leg(self):
        """A leg at 44c with the opposite ask at 57c is allowed to rest.

        The removed gate demanded the hedge exist in the same tick, which is the
        timing the ledger measures as a loss. The hedge is placed as a bid once
        this leg fills, not assumed.
        """
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.44, "ask": 0.45},
            "Down": {"bid": 0.56, "ask": 0.57},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.price, 0.44)
        self.assertEqual(dec.role, "MAKER")

    def test_atomic_arb_heavy_sizing(self):
        """Atomic Arb: when the hedge really is there (0.45 bid + 0.51 ask + fee < 0.985), size heavy (60 sh)."""
        inv = {
            "Up": {"shares": 0.0, "cost": 0.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.45, "ask": 0.46},
            "Down": {"bid": 0.50, "ask": 0.51},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.shares, 60.0)

    def test_hedge_rests_at_the_bid_instead_of_crossing(self):
        """A 30-share Down deficit rests a bid at 0.28, not a taker buy at the 0.30 ask.

        Ledger: a second leg taken at a 0-5s lag paired at -0.2c; the same pair
        closed at a 31-120s lag paired at +1.6c to +2.7c. Waiting is the edge.
        """
        inv = {
            "Up": {"shares": 30.0, "cost": 3.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.68, "ask": 0.70},
            "Down": {"bid": 0.28, "ask": 0.30},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=1,
            minute=1,
            strategy_id="dangerously-skip-permissions-v2.6",
            min_fill=0.07,
            max_fill=0.55,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.role, "MAKER")
        self.assertEqual(dec.price, 0.28)

    def test_sweep_crosses_the_ask_to_close_the_pair(self):
        """In the sweep the pair has to close, so the same deficit crosses at 0.30."""
        inv = {
            "Up": {"shares": 30.0, "cost": 3.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.68, "ask": 0.70},
            "Down": {"bid": 0.28, "ask": 0.30},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=1,
            minute=3,
            strategy_id="dangerously-skip-permissions-v2.6",
            min_fill=0.07,
            max_fill=0.55,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
            in_sweep_phase=True,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.role, "TAKER")
        self.assertEqual(dec.price, 0.30)

    def test_deficit_hedging_snaps_to_deficit(self):
        """When deficit is 30 sh, equalizer snaps directly to 30 sh."""
        inv = {
            "Up": {"shares": 30.0, "cost": 10.0},
            "Down": {"shares": 0.0, "cost": 0.0},
        }
        quotes = {
            "Up": {"bid": 0.35, "ask": 0.36},
            "Down": {"bid": 0.62, "ask": 0.63},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv=inv,
            fill_idx=1,
            minute=1,
            strategy_id="dangerously-skip-permissions-v2.2",
            min_fill=0.07,
            max_fill=0.88,
            max_pair_cost=0.985,
            rescue_max_pair_cost=0.995,
            max_clip=60.0,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Down")
        self.assertEqual(dec.shares, 30.0)


    def test_at_the_money_entry_is_allowed(self):
        """A 0.49 bid with a 0.51 ask opens the straddle leg; the hedge is placed after.

        The ledger's first fill is ~50c within 13s of the open, so a 0.45 entry
        ceiling was excluding the only price the wallet actually trades.
        """
        quotes = {
            "Up": {"bid": 0.49, "ask": 0.50},
            "Down": {"bid": 0.50, "ask": 0.51},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv={"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}},
            fill_idx=0,
            minute=0,
            strategy_id="dangerously-skip-permissions-v2.6",
            min_fill=0.07,
            max_fill=0.55,
            max_pair_cost=0.985,
        )
        self.assertEqual(dec.action, "fill")
        self.assertEqual(dec.outcome, "Up")
        self.assertEqual(dec.price, 0.49)
        self.assertEqual(dec.role, "MAKER")

    def test_a_bid_below_the_floor_is_dust_not_a_taker_fill_at_the_ask(self):
        """Up 0.05/0.07: the ask is inside the band, but the bid is dust.

        Falling back to the ask booked a TAKER fill at 0.07 on a 0.05 bid, with
        the taker fee eating 6% of the clip, and the dust skip never ran.
        """
        quotes = {
            "Up": {"bid": 0.05, "ask": 0.07},
            "Down": {"bid": 0.93, "ask": 0.95},
        }
        dec = evaluate_microstructure_ladder(
            quotes=quotes,
            inv={"Up": {"shares": 0.0, "cost": 0.0}, "Down": {"shares": 0.0, "cost": 0.0}},
            fill_idx=0,
            minute=3,
            strategy_id="dangerously-skip-permissions-v2.6",
            min_fill=0.07,
            max_fill=0.55,
            max_pair_cost=0.985,
        )
        self.assertEqual(dec.action, "skip")
        self.assertIsNone(dec.price)


if __name__ == "__main__":
    unittest.main()
