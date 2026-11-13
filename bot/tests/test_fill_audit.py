"""Unit tests for the fill auditor (bot/fill_audit.py)."""

import unittest

from bot.fill_audit import audit_window, role_of

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


def _print(outcome="Down", price=0.42, size=50.0, side="SELL", offset=20.0):
    return {
        "ts": START + offset,
        "slug_outcome": outcome,
        "price": price,
        "size": size,
        "side": side,
    }


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


if __name__ == "__main__":
    unittest.main()
