import unittest
from bot import constants as C
from bot.executor import evaluate_microstructure_ladder
from bot.fill_model import bucket_for_price, confirm_maker_buy, label_taker_fill, match_maker_print
from bot.ws import LiveBookStreamer


def _mk_streamer():
    return LiveBookStreamer('up_1', 'down_1')


class PrintModelTests(unittest.TestCase):
    def test_print_at_limit_confirms(self):
        prints = [{'price': 0.20, 'size': 10.0, 'side': 'SELL', 'ts': 100.0}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=99.0)
        self.assertEqual(r.status, 'confirmed')
        self.assertEqual(r.filled_shares, 10.0)

    def test_print_through_limit_confirms(self):
        prints = [{'price': 0.18, 'size': 33.0, 'side': 'SELL', 'ts': 101.0}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'confirmed')

    def test_cumulative_shortfall_partial(self):
        prints = [
            {'price': 0.20, 'size': 4.0, 'side': 'SELL', 'ts': 101.0},
            {'price': 0.19, 'size': 3.0, 'side': 'SELL', 'ts': 102.0},
        ]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'partial')
        self.assertAlmostEqual(r.filled_shares, 7.0)

    def test_no_print_unconfirmed(self):
        r = confirm_maker_buy(0.20, 10.0, [], decision_ts=100.0)
        self.assertEqual(r.status, 'unconfirmed')
        self.assertEqual(r.filled_shares, 0.0)

    def test_print_above_limit_ignored(self):
        prints = [{'price': 0.22, 'size': 50.0, 'side': 'SELL', 'ts': 101.0}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'unconfirmed')

    def test_taker_side_print_does_not_confirm_resting_buy(self):
        prints = [{'price': 0.20, 'size': 50.0, 'side': 'BUY', 'ts': 101.0}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'unconfirmed')

    def test_print_before_decision_does_not_confirm(self):
        prints = [{'price': 0.20, 'size': 50.0, 'side': 'SELL', 'ts': 99.0}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'unconfirmed')

    def test_old_raw_timestamp_does_not_confirm(self):
        prints = [{'price': 0.20, 'size': 50.0, 'side': 'SELL', 'timestamp': '99000'}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'unconfirmed')

    def test_missing_timestamp_does_not_confirm(self):
        prints = [{'price': 0.20, 'size': 50.0, 'side': 'SELL'}]
        r = confirm_maker_buy(0.20, 10.0, prints, decision_ts=100.0)
        self.assertEqual(r.status, 'unconfirmed')

    def test_taker_labelled_unverified(self):
        r = label_taker_fill(10.0)
        self.assertEqual(r.status, 'unverified-taker')
        self.assertEqual(r.filled_shares, 10.0)

    def test_price_buckets(self):
        self.assertEqual(bucket_for_price(0.10), '7-15c')
        self.assertEqual(bucket_for_price(0.20), '16-38c')
        self.assertEqual(bucket_for_price(0.42), '39-45c')
        self.assertEqual(bucket_for_price(0.60), 'other')


class DepthCapTests(unittest.TestCase):
    def _quotes(self):
        return {'Up': {'bid': 0.20, 'ask': 0.21}, 'Down': {'bid': 0.79, 'ask': 0.80}}

    def _inv(self):
        return {'Up': {'shares': 0.0, 'cost': 0.0}, 'Down': {'shares': 0.0, 'cost': 0.0}}

    def test_depth_cap_on_caps_maker(self):
        dec = evaluate_microstructure_ladder(
            quotes=self._quotes(), inv=self._inv(), fill_idx=2, minute=1,
            strategy_id='dangerously-skip-permissions-v2.4',
            min_fill=0.07, max_fill=0.45, default_clip=33.0, max_clip=45.0,
            benchmark_pair_cost=0.965, max_pair_cost=0.985, max_share_lead=45.0,
            max_depth_shares=100.0, resting_size={'Up': 12.0, 'Down': 100.0},
        )
        if dec.action == 'fill' and dec.role == 'MAKER':
            self.assertLessEqual(dec.shares, 12.0)
        else:
            dec2 = evaluate_microstructure_ladder(
                quotes={'Up': {'bid': 0.20, 'ask': 0.21}}, inv=self._inv(), fill_idx=2, minute=1,
                strategy_id='dangerously-skip-permissions-v2.4',
                min_fill=0.07, max_fill=0.45, default_clip=33.0, max_clip=45.0,
                benchmark_pair_cost=0.965, max_pair_cost=0.985, max_share_lead=45.0,
                max_depth_shares=100.0, resting_size=12.0,
            )
            self.assertEqual(dec2.action, 'fill')
            self.assertEqual(dec2.role, 'MAKER')
            self.assertEqual(dec2.shares, 12.0)

    def test_depth_cap_off_reproduces_today(self):
        base = evaluate_microstructure_ladder(
            quotes=self._quotes(), inv=self._inv(), fill_idx=2, minute=1,
            strategy_id='dangerously-skip-permissions-v2.4',
            min_fill=0.07, max_fill=0.45, default_clip=33.0, max_clip=45.0,
            benchmark_pair_cost=0.965, max_pair_cost=0.985, max_share_lead=45.0,
        )
        capped = evaluate_microstructure_ladder(
            quotes=self._quotes(), inv=self._inv(), fill_idx=2, minute=1,
            strategy_id='dangerously-skip-permissions-v2.4',
            min_fill=0.07, max_fill=0.45, default_clip=33.0, max_clip=45.0,
            benchmark_pair_cost=0.965, max_pair_cost=0.985, max_share_lead=45.0,
            max_depth_shares=0.0, resting_size={'Up': 1.0, 'Down': 1.0},
        )
        self.assertEqual((base.action, base.outcome, base.price, base.shares), (capped.action, capped.outcome, capped.price, capped.shares))

    def test_taker_unaffected_by_depth_cap(self):
        quotes = {'Up': {'bid': 0.20, 'ask': 0.30}, 'Down': {'bid': 0.79, 'ask': 0.80}}
        dec = evaluate_microstructure_ladder(
            quotes=quotes, inv=self._inv(), fill_idx=2, minute=1,
            strategy_id='dangerously-skip-permissions-v2.4',
            min_fill=0.07, max_fill=0.45, default_clip=33.0, max_clip=45.0,
            benchmark_pair_cost=0.965, max_pair_cost=0.985, max_share_lead=45.0,
            max_depth_shares=100.0, resting_size={'Up': 1.0, 'Down': 100.0},
        )
        if dec.action == 'fill' and dec.role == 'TAKER':
            self.assertGreater(dec.shares, 1.0)


class WsPrintTests(unittest.TestCase):
    def test_last_trade_price_stored_and_depth(self):
        s = _mk_streamer()
        try:
            s.process_payload([{'asset_id': 'up_1', 'bids': [{'price': '0.20', 'size': '15'}], 'asks': [{'price': '0.22', 'size': '20'}]}])
            s.process_payload({'event_type': 'last_trade_price', 'asset_id': 'up_1', 'price': '0.20', 'size': '7', 'side': 'SELL', 'timestamp': '1750428146322', 'fee_rate_bps': '0', 'market': '0xabc'})
            self.assertEqual(s.print_count, 1)
            prints = s.get_recent_prints()
            self.assertEqual(len(prints), 1)
            self.assertAlmostEqual(prints[0]['price'], 0.20)
            self.assertEqual(prints[0]['side'], 'SELL')
            d = s.depth('up_1', levels=5)
            self.assertTrue(len(d['bids']) >= 1)
            self.assertTrue(len(d['asks']) >= 1)
        finally:
            s.stop()

    def test_quote_path_unchanged_when_flag_off(self):
        s = _mk_streamer()
        try:
            self.assertFalse(s.enable_trade_prints)
            before = s.tick_count
            s.process_payload([{'asset_id': 'up_1', 'bids': [{'price': '0.20', 'size': '10'}], 'asks': [{'price': '0.21', 'size': '10'}]}])
            self.assertEqual(s.tick_count, before + 1)
            self.assertEqual(s.ticks[-1].event_type, 'snapshot')
        finally:
            s.stop()

    def test_unknown_asset_print_ignored(self):
        s = _mk_streamer()
        try:
            s.process_payload({'event_type': 'last_trade_price', 'asset_id': 'nope', 'price': '0.20', 'size': '5', 'side': 'SELL', 'timestamp': '1'})
            self.assertEqual(s.print_count, 0)
        finally:
            s.stop()


class MakerPrintMatchTests(unittest.TestCase):
    """The resting bid the live loop only fills when someone sells into it."""

    def _order(self, **kw):
        base = {"side": "Up", "price": 0.42, "shares_left": 10.0, "queue_ahead": 0.0}
        base.update(kw)
        return base

    def _print(self, **kw):
        base = {"outcome": "Up", "side": "SELL", "price": 0.42, "size": 10.0}
        base.update(kw)
        return base

    def test_a_sell_at_the_limit_fills_the_order(self):
        order = self._order()
        hit = match_maker_print(order, self._print())
        self.assertEqual(hit["fills"], 10.0)
        self.assertEqual(order["shares_left"], 0.0)

    def test_a_buy_print_never_fills_a_resting_bid(self):
        self.assertIsNone(match_maker_print(self._order(), self._print(side="BUY")))
        self.assertIsNone(match_maker_print(self._order(), self._print(side="")))

    def test_a_sell_above_the_limit_does_not_fill(self):
        self.assertIsNone(match_maker_print(self._order(price=0.42), self._print(price=0.43)))

    def test_the_queue_is_paid_before_the_order(self):
        order = self._order(queue_ahead=25.0)
        self.assertIsNone(match_maker_print(order, self._print(size=20)))
        self.assertEqual(order["queue_ahead"], 5.0)
        hit = match_maker_print(order, self._print(size=15))
        self.assertEqual(hit["fills"], 10.0)
        self.assertEqual(hit["queueAhead"], 5.0)

    def test_a_large_print_fills_partially(self):
        order = self._order(shares_left=10.0, queue_ahead=12.0)
        hit = match_maker_print(order, self._print(size=15))
        self.assertEqual(hit["fills"], 3.0)
        self.assertEqual(hit["queueAhead"], 12.0)
        self.assertEqual(order["shares_left"], 7.0)

    def test_another_outcome_is_not_my_fill(self):
        self.assertIsNone(match_maker_print(self._order(), self._print(outcome="Down")))

    def test_no_size_no_fill(self):
        self.assertIsNone(match_maker_print(self._order(), self._print(size=0)))


class SetupCopyTests(unittest.TestCase):
    def test_depth_mention_only_when_on(self):
        base = dict(C.STRATEGY_SETUPS['dangerously-skip-permissions-v2.4'])
        base['entry'] = dict(base['entry'])
        base['entry']['maxDepthShares'] = 0.0
        _, desc_off, hl_off = C.describe_setup(base)
        self.assertNotIn('depth', desc_off.lower())
        self.assertEqual(hl_off.get('depthCap'), 'Off')
        base['entry']['maxDepthShares'] = 12.0
        _, desc_on, hl_on = C.describe_setup(base)
        self.assertIn('depth', desc_on.lower())
        self.assertEqual(hl_on.get('depthCap'), '12 sh')


if __name__ == '__main__':
    unittest.main()
