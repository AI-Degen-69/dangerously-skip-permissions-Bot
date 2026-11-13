"""Unit tests for the fill auditor (bot/fill_audit.py)."""

import unittest

from bot.fill_audit import attainable_indexes, audit_window, role_of

START = 1794536700.0  # a real btc-updown-5m slot epoch


def _fill(outcome="Down", price=0.42, shares=10.0, role="MAKER", offset=10.0, **detail):
    return {
        "ts": int((START + offset) * 1000),
        "outcome": outcome,
        "price": price,
        "shares": shares,
        "usd": round(shares * price, 2),
        "reason": "maker-dip-ladder",
        "detail": {"role": role, **detail},
    }


def _print(outcome="Down", price=0.42, size=50.0, side="SELL", offset=20.0, market=None):
    row = {
        "ts": START + offset,
        "slug_outcome": outcome,
        "price": price,
        "size": size,
        "side": side,
    }
    if market is not None:
        row["market"] = market
    return row


class RoleTest(unittest.TestCase):

    def test_recorded_role_wins(self):
        self.assertEqual(role_of(_fill(role="TAKER")), "TAKER")

    def test_fee_decides_without_a_role(self):
        fill = _fill()
        fill["detail"] = {"feeUsd": 0.05}
        self.assertEqual(role_of(fill), "TAKER")

    def test_legacy_equalizer_reason_is_taker(self):
        fill = _fill()
        fill["detail"] = {}
        fill["reason"] = "hedge-equalizer"
        self.assertEqual(role_of(fill), "TAKER")


class AttainableIndexesTest(unittest.TestCase):
    """The per-fill verdict the desk stamps while the window is still trading."""

    def test_the_most_aggressive_fill_takes_the_print(self):
        fills = [_fill(shares=10, price=0.42), _fill(shares=10, price=0.40, offset=6)]
        got = attainable_indexes(fills, [_print(size=10, price=0.40)])
        self.assertEqual(got, {0: True, 1: False})

    def test_a_taker_always_counts(self):
        got = attainable_indexes([_fill(role="TAKER")], [_print(size=1, side="BUY")])
        self.assertEqual(got, {0: True})

    def test_queue_ahead_blocks_the_fill(self):
        got = attainable_indexes([_fill(queueAhead=20)], [_print(size=20)])
        self.assertEqual(got, {0: False})

    def test_no_prints_means_not_judged(self):
        self.assertIsNone(attainable_indexes([_fill()], []))


class EngineMatchesAuditTest(unittest.TestCase):
    """The fill engine and the audit must agree: the engine books what the
    audit would have credited, or the desk's two numbers drift apart again."""

    def test_a_fill_the_engine_booked_is_attainable(self):
        from bot.fill_model import match_maker_print

        order = {"side": "Down", "price": 0.42, "shares_left": 10.0, "queue_ahead": 5.0}
        hit = match_maker_print(order, {"outcome": "Down", "side": "SELL", "price": 0.42, "size": 12.0})
        self.assertEqual(hit["fills"], 7.0)
        fill = {
            "ts": int((START + 10) * 1000), "outcome": "Down", "price": 0.42,
            "shares": 7.0, "usd": 2.94,
            "detail": {"role": "MAKER", "queueAhead": hit["queueAhead"]},
        }
        tape = [{"ts": START + 10, "slug_outcome": "Down", "price": 0.42, "size": 12.0, "side": "SELL"}]
        got = audit_window([fill], tape, START, "Down")
        self.assertEqual(got["attainableFills"], 1)
        self.assertEqual(got["phantomFills"], 0)


class AuditWindowTest(unittest.TestCase):

    def test_sell_flow_fills_the_clip(self):
        got = audit_window([_fill()], [_print(size=20)], START, "Down")
        self.assertEqual(got["makerFills"], 1)
        self.assertEqual(got["attainableFills"], 1)
        self.assertEqual(got["phantomFills"], 0)
        self.assertEqual(got["attainableCostUsd"], 4.2)
        self.assertEqual(got["attainablePayoutUsd"], 10.0)
        self.assertEqual(got["attainableNetUsd"], 5.8)

    def test_a_buy_print_cannot_fill_a_resting_bid(self):
        got = audit_window([_fill()], [_print(size=500, side="BUY")], START, "Down")
        self.assertEqual(got["attainableFills"], 0)
        self.assertEqual(got["phantomFills"], 1)
        self.assertEqual(got["attainableNetUsd"], 0.0)

    def test_prints_before_the_fill_do_not_count(self):
        got = audit_window([_fill()], [_print(size=500, offset=5)], START, "Down")
        self.assertEqual(got["attainableFills"], 0)

    def test_selling_above_the_limit_does_not_count(self):
        got = audit_window([_fill(price=0.42)], [_print(price=0.43)], START, "Down")
        self.assertEqual(got["attainableFills"], 0)

    def test_print_for_the_other_outcome_does_not_count(self):
        got = audit_window([_fill(outcome="Down")], [_print(outcome="Up")], START, "Down")
        self.assertEqual(got["attainableFills"], 0)

    def test_queue_ahead_eats_the_flow(self):
        got = audit_window([_fill(queueAhead=20)], [_print(size=20)], START, "Down")
        self.assertEqual(got["attainableFills"], 0)
        self.assertEqual(got["phantomFills"], 1)
        self.assertEqual(got["queueKnown"], 1)

    def test_flow_beyond_the_queue_fills(self):
        got = audit_window([_fill(queueAhead=5)], [_print(size=20)], START, "Down")
        self.assertEqual(got["attainableFills"], 1)
        self.assertEqual(got["queueKnown"], 1)

    def test_taker_fills_need_no_queue(self):
        got = audit_window(
            [_fill(role="TAKER"), _fill(outcome="Up", price=0.5)],
            [_print(size=1)],
            START,
            "Down",
        )
        self.assertEqual(got["makerFills"], 1)
        self.assertEqual(got["attainableFills"], 0)
        # Taker leg: 10 shares at 0.42 cost, paying $10 because Down won.
        self.assertEqual(got["attainableCostUsd"], 4.2)
        self.assertEqual(got["attainablePayoutUsd"], 10.0)

    def test_losing_side_pays_nothing(self):
        got = audit_window([_fill(outcome="Down")], [_print(size=20)], START, "Up")
        self.assertEqual(got["attainableCostUsd"], 4.2)
        self.assertEqual(got["attainablePayoutUsd"], 0.0)
        self.assertEqual(got["attainableNetUsd"], -4.2)

    def test_shares_add_up(self):
        got = audit_window([_fill(), _fill(offset=30, queueAhead=99)], [_print(size=20)], START, "Down")
        self.assertEqual(got["assumedShares"], 20.0)
        self.assertEqual(got["attainableShares"], 10.0)

    def test_no_prints_leaves_the_window_unjudged(self):
        self.assertIsNone(audit_window([_fill()], [], START, "Down"))
        # A print from a neighbouring window is not evidence about this one.
        self.assertIsNone(audit_window([_fill()], [_print(offset=-10)], START, "Down"))

    def test_one_print_cannot_fill_two_orders(self):
        got = audit_window(
            [_fill(shares=10, offset=5), _fill(shares=10, offset=6)],
            [_print(size=10)],
            START,
            "Down",
        )
        self.assertEqual(got["makerFills"], 2)
        self.assertEqual(got["attainableFills"], 1)
        self.assertEqual(got["phantomFills"], 1)

    def test_the_most_aggressive_fill_gets_the_flow(self):
        got = audit_window(
            [_fill(shares=10, price=0.40, offset=5), _fill(shares=10, price=0.42, offset=6)],
            [_print(size=10, price=0.40)],
            START,
            "Down",
        )
        self.assertEqual(got["attainableFills"], 1)
        # The 0.42 bid is the one the taker hits, so its cost is what survives.
        self.assertEqual(got["attainableCostUsd"], 4.2)

    def test_queue_ahead_is_spent_before_the_fill(self):
        got = audit_window(
            [_fill(shares=10, queueAhead=5, offset=5), _fill(shares=10, queueAhead=5, offset=6)],
            [_print(size=20)],
            START,
            "Down",
        )
        self.assertEqual(got["attainableFills"], 1)

    def test_prints_from_another_market_are_not_this_window(self):
        got = audit_window([_fill()], [_print(size=500, market="0xother")], START, "Down", "0xmine")
        self.assertIsNone(got)

    def test_older_windows_infer_their_market_from_the_tape(self):
        # The next market's recorder starts before this one ends; its SELLs at
        # the same outcome name must not read as flow for this window.
        prints = [
            _print(size=1, market="0xmine", offset=1),
            _print(size=500, market="0xother", offset=295),
        ]
        got = audit_window([_fill()], prints, START, "Down")
        self.assertEqual(got["attainableFills"], 0)
        self.assertEqual(got["phantomFills"], 1)


if __name__ == "__main__":
    unittest.main()
