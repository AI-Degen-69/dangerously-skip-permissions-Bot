import csv
import datetime
import io
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import requests


SCRIPT_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "scripts"
    / "save-trades-to-csv.py"
)
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "save_trades_to_csv", SCRIPT_PATH
)
SCRIPT = importlib.util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = SCRIPT
SCRIPT_SPEC.loader.exec_module(SCRIPT)


class FakeResponse:
    def __init__(self, payload=None, error=None, status_code=200, text=""):
        self.payload = payload
        self.error = error
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


class SaveTradesToCsvTests(unittest.TestCase):
    def test_streams_progress_for_each_activity_page(self):
        page_one = {
            "data": [{"timestamp": 1794074400}],
            "pagination": {"next_cursor": "next-page"},
        }
        page_two = {
            "data": [{"timestamp": 1794074399}, {"timestamp": 1794074398}],
            "pagination": {"next_cursor": None},
        }

        events = []

        class FlushTrackingStream(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flush_count = 0

            def flush(self):
                self.flush_count += 1
                events.append(("flush", len(events)))
                super().flush()

        stream = FlushTrackingStream()
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)

        def mock_get(*args, **kwargs):
            events.append(("get", len(events)))
            get_count = len([e for e in events if e[0] == "get"])
            return FakeResponse(page_one if get_count == 1 else page_two)

        with patch("sys.stdout", stream), patch.object(
            SCRIPT.requests,
            "get",
            side_effect=mock_get,
        ):
            SCRIPT.fetch_activity(
                now=target,
                window_days=7,
                snap_to_window=False,
                cut_tails=False,
            )

        progress_lines = [
            line for line in stream.getvalue().splitlines() if line.startswith("Page ")
        ]
        self.assertEqual(
            progress_lines,
            ["Page 1: 1 records; 1 total", "Page 2: 2 records; 3 total"],
        )
        self.assertEqual(stream.flush_count, 2)
        # Verify that page 1 was flushed before page 2 was requested
        self.assertEqual([e[0] for e in events], ["get", "flush", "get", "flush"])

    def test_fetches_all_activity_pages_with_fixed_24_hour_bounds(self):
        now = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)
        first_page = {
            "data": [
                {
                    "proxy_wallet": SCRIPT.USER_ADDRESS.lower(),
                    "timestamp": int(now.timestamp()),
                    "type": "TRADE",
                    "title": "Market A",
                    "outcome": "Up",
                    "side": "BUY",
                    "price": 0.25,
                    "size": 4,
                    "usdc_size": 1,
                    "condition_id": "condition-a",
                    "token_id": "token-a",
                    "transaction_hash": "tx-a",
                    "slug": "market-a",
                    "event_slug": "event-a",
                }
            ],
            "pagination": {"next_cursor": "next-page"},
        }
        second_page = {
            "data": [
                {
                    "proxy_wallet": SCRIPT.USER_ADDRESS.lower(),
                    "timestamp": int(now.timestamp()) - 1,
                    "type": "REDEEM",
                    "title": "Market B",
                    "outcome": "Down",
                    "side": "",
                    "price": 0,
                    "size": 2,
                    "usdc_size": 2,
                    "condition_id": "condition-b",
                    "token_id": "token-b",
                    "transaction_hash": "tx-b",
                    "slug": "market-b",
                    "event_slug": "event-b",
                }
            ],
            "pagination": {"next_cursor": None},
        }

        with patch.object(
            SCRIPT.requests,
            "get",
            side_effect=[FakeResponse(first_page), FakeResponse(second_page)],
        ) as get:
            records = SCRIPT.fetch_activity(now=now, window_days=1)

        self.assertEqual([record["Type"] for record in records], ["TRADE", "REDEEM"])
        self.assertEqual(get.call_count, 2)
        first_params = get.call_args_list[0].kwargs["params"]
        second_params = get.call_args_list[1].kwargs["params"]
        self.assertEqual(get.call_args_list[0].args[0], SCRIPT.BASE_URL)
        self.assertEqual(first_params["user"], SCRIPT.USER_ADDRESS)
        self.assertEqual(first_params["end"], int(now.timestamp()))
        self.assertEqual(first_params["end"] - first_params["start"], 86_400)
        self.assertNotIn("cursor", first_params)
        self.assertEqual(second_params["cursor"], "next-page")
        self.assertEqual(second_params["start"], first_params["start"])
        self.assertEqual(second_params["end"], first_params["end"])

    def test_writes_header_for_empty_activity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = pathlib.Path(temp_dir) / "empty.csv"
            SCRIPT.save_to_csv([], str(output_path))

            with output_path.open(encoding="utf-8", newline="") as output_file:
                reader = csv.reader(output_file)
                header = next(reader)
                rows = list(reader)

        self.assertIn("Type", header)
        self.assertEqual(rows, [])

    def test_default_output_filename_uses_username_and_trade_date(self):
        target_dt = datetime.datetime(2026, 11, 7, 0, 0, tzinfo=datetime.timezone.utc)

        filename = SCRIPT.default_output_filename(
            "Test User", target_dt, window_days=1, date_only=True
        )

        self.assertEqual(filename, "test_user_2026-11-06.csv")

    def test_fetches_requested_window_lengths(self):
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)
        page = {"data": [], "pagination": {"next_cursor": None}}

        for window_days in (1, 7):
            with self.subTest(window_days=window_days):
                with patch.object(
                    SCRIPT.requests, "get", return_value=FakeResponse(page)
                ) as get:
                    SCRIPT.fetch_activity(
                        now=target,
                        window_days=window_days,
                        snap_to_window=False,
                        cut_tails=False,
                    )

                params = get.call_args.kwargs["params"]
                self.assertEqual(params["end"], int(target.timestamp()))
                self.assertEqual(
                    params["end"] - params["start"],
                    window_days * 24 * 60 * 60,
                )

    def test_fetches_seven_days_ending_after_requested_date(self):
        page = {"data": [], "pagination": {"next_cursor": None}}

        with patch.object(
            SCRIPT.requests, "get", return_value=FakeResponse(page)
        ) as get:
            SCRIPT.fetch_activity(
                now="06/11/2026",
                window_days=7,
                snap_to_window=False,
                cut_tails=False,
            )

        params = get.call_args.kwargs["params"]
        expected_end = int(
            datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc).timestamp()
        )
        self.assertEqual(params["end"], expected_end)
        self.assertEqual(params["end"] - params["start"], 7 * 24 * 60 * 60)

    def test_rejects_unsupported_window_length(self):
        with self.assertRaisesRegex(ValueError, "window_days must be 1 or 7"):
            SCRIPT.fetch_activity(window_days=2)

    def test_default_output_filename_includes_week_range(self):
        target = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)

        filename = SCRIPT.default_output_filename(
            "Test User", target, window_days=7, date_only=True
        )

        self.assertEqual(filename, "test_user_2026-10-31_to_2026-11-06.csv")

    def test_default_output_filename_keeps_single_day_shape(self):
        target = datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)

        filename = SCRIPT.default_output_filename(
            "Test User", target, window_days=1, date_only=True
        )

        self.assertEqual(filename, "test_user_2026-11-06.csv")

    def test_default_output_filename_uses_target_utc_date_for_timestamp(self):
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)

        filename = SCRIPT.default_output_filename(
            "Test User", target, window_days=7, date_only=False
        )

        self.assertEqual(filename, "test_user_2026-10-31_to_2026-11-07.csv")

    def test_main_preserves_custom_output_and_defaults_to_week(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = str(pathlib.Path(temp_dir) / "custom.csv")
            with (
                patch.object(
                    SCRIPT,
                    "resolve_user_address",
                    return_value=(SCRIPT.USER_ADDRESS, "Test User"),
                ),
                patch.object(SCRIPT, "fetch_activity", return_value=[]) as fetch,
                patch.object(SCRIPT, "save_to_csv") as save,
                patch(
                    "sys.argv",
                    [
                        str(SCRIPT_PATH),
                        "--user",
                        "Test User",
                        "--date",
                        "06/11/2026",
                        "--output",
                        output_path,
                    ],
                ),
            ):
                SCRIPT.main()

        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["window_days"], 7)
        save.assert_called_once_with([], output_path=output_path)

    def test_propagates_http_errors(self):
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse(error=requests.HTTPError("service unavailable")),
        ):
            with self.assertRaises(requests.HTTPError):
                SCRIPT.fetch_activity(
                    now=datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)
                )

    def test_rejects_invalid_response_shapes(self):
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse({"data": [], "pagination": {}}),
        ):
            with self.assertRaisesRegex(ValueError, "missing next_cursor"):
                SCRIPT.fetch_activity(
                    now=datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)
                )

    def test_clean_user_input(self):
        self.assertEqual(SCRIPT.clean_user_input("tokor"), "tokor")
        self.assertEqual(SCRIPT.clean_user_input("@tokor"), "tokor")
        self.assertEqual(SCRIPT.clean_user_input("https://polymarket.com/@tokor"), "tokor")
        self.assertEqual(SCRIPT.clean_user_input("https://polymarket.com/tokor"), "tokor")
        self.assertEqual(
            SCRIPT.clean_user_input("0xa19cbababc312f9df185e49d7004c249ed1ade6b"),
            "0xa19cbababc312f9df185e49d7004c249ed1ade6b",
        )

    def test_resolve_user_address_from_evm_address(self):
        addr = "0xa19cbababc312f9df185e49d7004c249ed1ade6b"
        profile_json = {"name": "Tokor", "proxyWallet": addr}
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse(profile_json, status_code=200),
        ):
            resolved, name = SCRIPT.resolve_user_address(addr)

        self.assertEqual(resolved, addr.lower())
        self.assertEqual(name, "Tokor")

    def test_resolve_user_address_from_username(self):
        html_payload = r'{"state":{"data":{"proxyWallet":"0xa19cbababc312f9df185e49d7004c249ed1ade6b","name":"Tokor"}}}'
        profile_json = {"name": "Tokor", "proxyWallet": "0xa19cbababc312f9df185e49d7004c249ed1ade6b"}
        with patch.object(
            SCRIPT.requests,
            "get",
            side_effect=[
                FakeResponse(status_code=200, text=html_payload),
                FakeResponse(profile_json, status_code=200),
            ],
        ):
            resolved, name = SCRIPT.resolve_user_address("tokor")

        self.assertEqual(resolved, "0xa19cbababc312f9df185e49d7004c249ed1ade6b")
        self.assertEqual(name, "Tokor")

    def test_get_window_meta(self):
        slot, dur = SCRIPT.get_window_meta("btc-updown-5m-1794068700")
        self.assertEqual(slot, 1794068700)
        self.assertEqual(dur, 300)

        slot15, dur15 = SCRIPT.get_window_meta("eth-updown-15m-1794068700")
        self.assertEqual(slot15, 1794068700)
        self.assertEqual(dur15, 900)

        self.assertIsNone(SCRIPT.get_window_meta("will-solana-reach-120"))

    def test_cut_tail_markets(self):
        # 3 windows:
        # 1. Oldest: slot 1000, dur 300 (ends 1300), but start_ts is 1100 -> partially pulled!
        # 2. Middle: slot 1300, dur 300 (ends 1600) -> completely enclosed!
        # 3. Newest: slot 1600, dur 300 (ends 1900), but end_ts is 1700 -> not completed!
        records = [
            {
                "Event_Slug": "btc-updown-5m-1000",
                "Timestamp_UTC": "2026-11-07T00:19:00+00:00",
                "timestamp": 1140,
                "Type": "TRADE",
            },
            {
                "Event_Slug": "btc-updown-5m-1300",
                "Timestamp_UTC": "2026-11-07T00:22:00+00:00",
                "timestamp": 1320,
                "Type": "TRADE",
            },
            {
                "Event_Slug": "btc-updown-5m-1600",
                "Timestamp_UTC": "2026-11-07T00:27:00+00:00",
                "timestamp": 1620,
                "Type": "TRADE",
            },
        ]
        start_ts = 1100
        end_ts = 1700
        cleaned, removed = SCRIPT.cut_tail_markets(
            records, start_ts=start_ts, end_ts=end_ts, now_ts=1700
        )
        self.assertEqual(len(removed), 2)
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["Event_Slug"], "btc-updown-5m-1300")

    def test_fetch_activity_snapping_to_window(self):
        # Unaligned now (e.g. 18:02:45 UTC) should snap down to 18:00:00 (multiple of 300)
        unaligned_now = datetime.datetime(2026, 11, 7, 18, 2, 45, tzinfo=datetime.timezone.utc)
        expected_end = int(datetime.datetime(2026, 11, 7, 18, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
        page = {
            "data": [],
            "pagination": {"next_cursor": None},
        }
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse(page),
        ) as get:
            SCRIPT.fetch_activity(
                now=unaligned_now, snap_to_window=True, window_days=1
            )

        params = get.call_args_list[0].kwargs["params"]
        self.assertEqual(params["end"], expected_end)
        self.assertEqual(params["end"] - params["start"], 86_400)

    def test_parse_date_input_date_only(self):
        now = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=datetime.timezone.utc)

        # 06/11 (DD/MM) -> starts from 07/11, 00:00 to get whole 24 hours of 06/11
        dt1 = SCRIPT.parse_date_input("06/11", now=now)
        self.assertEqual(dt1, datetime.datetime(2026, 11, 7, 0, 0, tzinfo=datetime.timezone.utc))

        # 06/11/2026 -> 07/11/2026 00:00
        dt2 = SCRIPT.parse_date_input("06/11/2026", now=now)
        self.assertEqual(dt2, datetime.datetime(2026, 11, 7, 0, 0, tzinfo=datetime.timezone.utc))

        # 2026-11-06 -> 2026-11-07 00:00
        dt3 = SCRIPT.parse_date_input("2026-11-06", now=now)
        self.assertEqual(dt3, datetime.datetime(2026, 11, 7, 0, 0, tzinfo=datetime.timezone.utc))

        # Default / now
        dt_now = SCRIPT.parse_date_input("now", now=now)
        self.assertEqual(dt_now, now)
        dt_none = SCRIPT.parse_date_input(None, now=now)
        self.assertEqual(dt_none, now)

    def test_parse_date_input_with_time(self):
        now = datetime.datetime(2026, 11, 8, 12, 0, tzinfo=datetime.timezone.utc)
        dt = SCRIPT.parse_date_input("06/11/2026 15:30", now=now)
        self.assertEqual(dt, datetime.datetime(2026, 11, 6, 15, 30, tzinfo=datetime.timezone.utc))

    def test_parse_date_input_invalid_format(self):
        with self.assertRaises(ValueError):
            SCRIPT.parse_date_input("invalid-date-string")

    def test_fetch_activity_with_date_string(self):
        page = {
            "data": [],
            "pagination": {"next_cursor": None},
        }
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse(page),
        ) as get:
            SCRIPT.fetch_activity(now="06/11", window_days=1)

        params = get.call_args_list[0].kwargs["params"]
        # 06/11 -> end_ts should be 2026-11-07 00:00:00 UTC
        expected_end = int(datetime.datetime(2026, 11, 7, 0, 0, tzinfo=datetime.timezone.utc).timestamp())
        self.assertEqual(params["end"], expected_end)
        self.assertEqual(params["end"] - params["start"], 86_400)


if __name__ == "__main__":
    unittest.main()
