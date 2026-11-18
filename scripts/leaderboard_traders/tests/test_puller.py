import csv
import datetime
import io
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

import requests

from scripts.leaderboard_traders import puller as SCRIPT


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


def make_record(timestamp, **overrides):
    record = {field: "" for field in SCRIPT.CSV_FIELDS}
    record["Timestamp_UTC"] = timestamp
    record["Type"] = "TRADE"
    record.update(overrides)
    return record


class SaveTradesToCsvTests(unittest.TestCase):
    def test_progress_streams_before_the_next_page_request(self):
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

        text = stream.getvalue()
        self.assertIn("Checking 2026-11-07 back to 2026-10-31 for fills", text)
        self.assertIn("--- 2026-11-07 ", text)
        self.assertIn("1 fills so far", text)
        self.assertIn("2026-11-07 | 3 fills in 0 market windows", text)
        self.assertIn("Fetched 3 fills on 1 days", text)
        self.assertNotIn("page", text.lower())
        self.assertNotIn("in range", text)

        # Progress was flushed before the next request
        kinds = [e[0] for e in events]
        first_get = kinds.index("get")
        second_get = kinds.index("get", first_get + 1)
        self.assertIn("flush", kinds[first_get:second_get])

    def test_each_day_gets_a_summary_and_a_separator(self):
        day_one = 1794074400  # 2026-11-07 18:00 UTC
        responses = [
            {
                "data": [{"timestamp": day_one, "slug": "btc-updown-5m-1794074100"}],
                "pagination": {"next_cursor": "next"},
            },
            {
                "data": [{"timestamp": day_one - 86_400, "slug": "btc-updown-5m-1793987700"}],
                "pagination": {"next_cursor": None},
            },
        ]
        stream = io.StringIO()
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)

        with patch("sys.stdout", stream), patch.object(
            SCRIPT.requests, "get", side_effect=[FakeResponse(r) for r in responses]
        ):
            SCRIPT.fetch_activity(
                now=target, window_days=7, snap_to_window=False, cut_tails=False
            )

        text = stream.getvalue()
        self.assertIn("--- 2026-11-07 ", text)
        self.assertIn("--- 2026-11-06 ", text)
        self.assertIn("2026-11-07 | 1 fills in 1 market windows", text)
        self.assertIn("2026-11-06 | 1 fills in 1 market windows", text)
        self.assertEqual(text.count("-" * 70), 2)
        self.assertIn("Fetched 2 fills on 2 days", text)

    def test_terminal_progress_rewrites_one_line(self):
        stream = io.StringIO()
        stream.isatty = lambda: True  # behave like a terminal
        page = {
            "data": [
                {"timestamp": 1794074400, "slug": "btc-updown-5m-1794074100"}
            ],
            "pagination": {"next_cursor": None},
        }
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)

        with patch("sys.stdout", stream), patch.object(
            SCRIPT.requests, "get", side_effect=[FakeResponse(page)]
        ):
            SCRIPT.fetch_activity(
                now=target, window_days=7, snap_to_window=False, cut_tails=False
            )

        value = stream.getvalue()
        self.assertIn("market window 17:55 (5m)", value)
        self.assertIn("1 fills so far", value)
        self.assertIn("--- 2026-11-07 ", value)
        self.assertIn("2026-11-07 | 1 fills in 1 market windows", value)
        self.assertIn("\r", value)
        self.assertNotIn("page", value.lower())

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

        self.assertEqual(header, SCRIPT.CSV_FIELDS)
        self.assertNotIn("Proxy_Wallet", header)
        self.assertNotIn("Transaction_Hash", header)
        self.assertNotIn("Event_Slug", header)
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
                patch.object(SCRIPT, "RAW_ROOT", temp_dir),
                patch.object(SCRIPT, "DOCS_ROOT", temp_dir),
                patch(
                    "sys.argv",
                    [
                        "puller",
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

    def test_main_default_output_lands_in_ledgers_raw(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    SCRIPT,
                    "resolve_user_address",
                    return_value=(SCRIPT.USER_ADDRESS, "Test User"),
                ),
                patch.object(SCRIPT, "fetch_activity", return_value=[]),
                patch.object(SCRIPT, "save_to_csv") as save,
                patch.object(SCRIPT, "RAW_ROOT", temp_dir),
                patch.object(SCRIPT, "DOCS_ROOT", temp_dir),
                patch(
                    "sys.argv",
                    [
                        "puller",
                        "--user",
                        "Test User",
                        "--date",
                        "06/11/2026",
                    ],
                ),
            ):
                SCRIPT.main()

            account = pathlib.Path(temp_dir) / "test_user"
            for sub in ("raw", "reports", "analysis"):
                self.assertTrue((account / sub).is_dir(), sub)

            save.assert_called_once_with(
                [],
                output_path=os.path.join(
                    temp_dir,
                    "test_user",
                    "raw",
                    "test_user_2026-10-31_to_2026-11-06.csv",
                ),
            )

    def test_short_account_tag_keeps_the_file_name_short(self):
        self.assertEqual(
            SCRIPT.short_account_tag("dangerously-skip-permissions"),
            "dangerously",
        )
        self.assertEqual(SCRIPT.short_account_tag("Test User"), "test_user")
        self.assertEqual(
            SCRIPT.short_account_tag(
                "0xe5e1072b676d83ba78d1a20460fd4d072b85badc"
            ),
            "0xe",
        )

    def test_max_output_filename_uses_pull_stats(self):
        records = [
            make_record("2026-11-08T21:00:00+00:00", Market_Slug="w1"),
            make_record("2026-11-09T21:00:00+00:00", Market_Slug="w2"),
        ]
        name = SCRIPT.max_output_filename("dangerously-skip-permissions", records)

        self.assertEqual(name, "dangerously_2-windows_2-days.csv")

    def test_fetch_max_activity_crawls_until_empty_windows(self):
        newest = make_record("2026-11-08T00:00:00+00:00", Market="m-1")
        older = make_record("2026-11-01T00:00:00+00:00", Market="m-2")
        windows = [[newest], [older], [], [], [], []]
        start = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)

        with patch.object(SCRIPT, "fetch_activity", side_effect=windows) as fetch:
            records, interrupted = SCRIPT.fetch_max_activity(
                SCRIPT.USER_ADDRESS, now=start
            )

        self.assertFalse(interrupted)
        self.assertEqual(
            [record["Market"] for record in records], ["m-1", "m-2"]
        )
        self.assertEqual(fetch.call_count, 2 + SCRIPT.MAX_EMPTY_WINDOWS)
        self.assertTrue(fetch.call_args_list[0].kwargs["cut_tails"])
        self.assertFalse(fetch.call_args_list[1].kwargs["cut_tails"])
        self.assertEqual(
            fetch.call_args_list[1].kwargs["now"],
            datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc),
        )

    def test_fetch_max_activity_dedupes_window_boundary_rows(self):
        row = make_record("2026-11-01T00:00:00+00:00")
        windows = [[row], [row], [], [], [], []]
        start = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)

        with patch.object(SCRIPT, "fetch_activity", side_effect=windows):
            records, interrupted = SCRIPT.fetch_max_activity(
                SCRIPT.USER_ADDRESS, now=start
            )

        self.assertFalse(interrupted)
        self.assertEqual(len(records), 1)

    def test_fetch_max_activity_keeps_identical_fills_inside_one_window(self):
        # Two real fills can share every CSV column; only the dropped hash told
        # them apart, so the merge must count rows, not set them.
        fill = make_record("2026-11-01T00:00:00+00:00", Market="m-1")
        windows = [[fill, dict(fill)], [], [], [], []]
        start = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)

        with patch.object(SCRIPT, "fetch_activity", side_effect=windows):
            records, interrupted = SCRIPT.fetch_max_activity(
                SCRIPT.USER_ADDRESS, now=start
            )

        self.assertFalse(interrupted)
        self.assertEqual(len(records), 2)

    def test_fetch_activity_fills_partial_collector(self):
        payload = {
            "data": [{"timestamp": 1794074400, "slug": "w1", "usdc_size": 10}],
            "pagination": {"next_cursor": None},
        }
        partial: list[dict] = []
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)

        with patch.object(SCRIPT.requests, "get", return_value=FakeResponse(payload)):
            records = SCRIPT.fetch_activity(
                now=target, window_days=7, snap_to_window=False,
                cut_tails=False, partial=partial,
            )

        self.assertEqual(records, partial)
        self.assertEqual(len(partial), 1)
        self.assertNotIn("timestamp", partial[0])

    def test_fetch_max_activity_keeps_rows_from_an_interrupted_window(self):
        row = make_record("2026-11-13T12:00:00+00:00", Market_Slug="w1")
        start = datetime.datetime(2026, 11, 16, tzinfo=datetime.timezone.utc)

        def fetch(*args, **kwargs):
            kwargs["partial"].append(row)
            raise KeyboardInterrupt()

        with patch.object(SCRIPT, "fetch_activity", side_effect=fetch):
            records, interrupted = SCRIPT.fetch_max_activity(
                SCRIPT.USER_ADDRESS, now=start
            )

        self.assertTrue(interrupted)
        self.assertEqual([r["Market_Slug"] for r in records], ["w1"])

    def test_interrupted_checkpoint_flags_partial_data(self):
        stream = io.StringIO()
        row = make_record("2026-11-13T12:00:00+00:00", Market_Slug="w1")

        with patch("sys.stdout", stream):
            SCRIPT.print_checkpoint([row], "out.csv", True)

        self.assertIn("Note: the interrupted day is partial", stream.getvalue())

    def test_fetch_max_activity_keeps_records_when_interrupted(self):
        row = make_record("2026-11-08T00:00:00+00:00")
        start = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)

        with patch.object(
            SCRIPT, "fetch_activity", side_effect=[[row], KeyboardInterrupt()]
        ):
            records, interrupted = SCRIPT.fetch_max_activity(
                SCRIPT.USER_ADDRESS, now=start
            )

        self.assertTrue(interrupted)
        self.assertEqual(len(records), 1)

    def test_fetch_max_activity_autosaves_every_five_windows(self):
        windows = [
            [make_record(f"2026-11-0{day}T00:00:00+00:00", Market=f"m-{day}")]
            for day in range(1, 6)
        ] + [[], [], [], []]
        start = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)

        with tempfile.TemporaryDirectory() as temp_dir:
            partial = os.path.join(temp_dir, "acct_2026-11-08_partial.csv")
            with patch.object(SCRIPT, "fetch_activity", side_effect=windows):
                records, _ = SCRIPT.fetch_max_activity(
                    SCRIPT.USER_ADDRESS, now=start, autosave_path=partial
                )

            with open(partial, encoding="utf-8", newline="") as handle:
                saved = list(csv.DictReader(handle))

        self.assertEqual(len(records), 5)
        self.assertEqual(
            [row["Market"] for row in saved], [f"m-{day}" for day in range(1, 6)]
        )

    def test_fetch_max_activity_survives_a_failed_autosave(self):
        windows = [[make_record("2026-11-01T00:00:00+00:00")]] * 5 + [[], [], [], []]
        start = datetime.datetime(2026, 11, 8, tzinfo=datetime.timezone.utc)

        with patch.object(SCRIPT, "fetch_activity", side_effect=windows), patch.object(
            SCRIPT, "save_to_csv", side_effect=OSError("disk full")
        ):
            records, interrupted = SCRIPT.fetch_max_activity(
                SCRIPT.USER_ADDRESS, now=start, autosave_path="ignored.csv"
            )

        self.assertFalse(interrupted)
        self.assertEqual(len(records), 1)

    def test_crawl_eta_reports_time_left(self):
        start_ts = 1_000_000_000
        target = start_ts - 100 * 86_400  # 100 days of history
        reached = start_ts - 25 * 86_400  # a quarter of it, in one minute

        eta = SCRIPT._crawl_eta(start_ts, target, reached, 60.0)

        self.assertEqual(eta, "~3m00s left")

    def test_crawl_eta_is_omitted_without_a_known_start(self):
        start_ts = 1_000_000_000
        reached = start_ts - 86_400

        self.assertEqual(SCRIPT._crawl_eta(start_ts, None, reached, 10.0), "")
        self.assertEqual(SCRIPT._crawl_eta(start_ts, start_ts, reached, 10.0), "")

    def test_probe_oldest_activity_reads_the_first_fill(self):
        payload = {"data": [{"timestamp": 1_600_000_000}], "pagination": {}}

        with patch.object(
            SCRIPT.requests, "get", return_value=FakeResponse(payload)
        ) as get:
            oldest = SCRIPT.probe_oldest_activity(SCRIPT.USER_ADDRESS)

        self.assertEqual(oldest, 1_600_000_000)
        self.assertEqual(get.call_args.kwargs["params"]["sortDirection"], "ASC")

    def test_probe_oldest_activity_returns_none_when_the_request_fails(self):
        with patch.object(SCRIPT.requests, "get", side_effect=OSError("offline")):
            self.assertIsNone(SCRIPT.probe_oldest_activity(SCRIPT.USER_ADDRESS))

    def test_pull_stats_count_distinct_windows_and_days(self):
        rows = [
            make_record("2026-11-08T00:00:00+00:00", Market_Slug="w1"),
            make_record("2026-11-08T01:00:00+00:00", Market_Slug="w1"),
            make_record("2026-11-09T00:00:00+00:00", Condition_ID="cid2"),
            make_record("2026-11-09T01:00:00+00:00", Market_Slug="w3"),
        ]

        self.assertEqual(SCRIPT.pull_stats(rows), (3, 2))
        self.assertEqual(
            SCRIPT.max_output_filename("Test User", rows),
            "test_user_3-windows_2-days.csv",
        )
        self.assertEqual(
            SCRIPT.max_output_filename("Test User", []),
            "test_user_0-windows_0-days.csv",
        )

    def test_main_max_names_the_file_after_pull_stats(self):
        rows = [
            make_record("2026-11-08T00:00:00+00:00", Market_Slug="btc-updown-5m-1"),
            make_record("2026-11-08T01:00:00+00:00", Market_Slug="btc-updown-5m-1"),
            make_record("2026-07-17T00:00:00+00:00", Market_Slug="btc-updown-5m-2"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(
                    SCRIPT,
                    "resolve_user_address",
                    return_value=(SCRIPT.USER_ADDRESS, "Test User"),
                ),
                patch.object(
                    SCRIPT, "fetch_max_activity", return_value=(rows, False)
                ),
                patch.object(SCRIPT, "probe_oldest_activity", return_value=None),
                patch.object(SCRIPT, "save_to_csv") as save,
                patch.object(SCRIPT, "RAW_ROOT", temp_dir),
                patch.object(SCRIPT, "DOCS_ROOT", temp_dir),
                patch(
                    "sys.argv",
                    ["puller", "--user", "Test User", "--date", "max"],
                ),
            ):
                SCRIPT.main()

            self.assertTrue((pathlib.Path(temp_dir) / "test_user" / "raw").is_dir())

            save.assert_called_once_with(
                rows,
                output_path=os.path.join(
                    temp_dir,
                    "test_user",
                    "raw",
                    "test_user_2-windows_2-days.csv",
                ),
            )

    def test_main_max_removes_the_partial_after_a_successful_save(self):
        rows = [make_record("2026-11-08T00:00:00+00:00")]
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as temp_dir:
            partial = (
                pathlib.Path(temp_dir)
                / "test_user"
                / "raw"
                / f"test_user_{today}_partial.csv"
            )
            partial.parent.mkdir(parents=True)
            partial.write_text("stale", encoding="utf-8")
            with (
                patch.object(
                    SCRIPT,
                    "resolve_user_address",
                    return_value=(SCRIPT.USER_ADDRESS, "Test User"),
                ),
                patch.object(
                    SCRIPT, "fetch_max_activity", return_value=(rows, False)
                ),
                patch.object(SCRIPT, "probe_oldest_activity", return_value=None),
                patch.object(SCRIPT, "save_to_csv"),
                patch.object(SCRIPT, "RAW_ROOT", temp_dir),
                patch.object(SCRIPT, "DOCS_ROOT", temp_dir),
                patch(
                    "sys.argv",
                    ["puller", "--user", "Test User", "--date", "max"],
                ),
            ):
                SCRIPT.main()

            self.assertFalse(partial.exists())

    def test_date_prompt_offers_max_and_runs_full_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("builtins.input", return_value="max") as prompt,
                patch.object(
                    SCRIPT,
                    "resolve_user_address",
                    return_value=(SCRIPT.USER_ADDRESS, "Test User"),
                ),
                patch.object(SCRIPT, "probe_oldest_activity", return_value=None),
                patch.object(
                    SCRIPT, "fetch_max_activity", return_value=([], False)
                ) as fetch_max,
                patch.object(SCRIPT, "save_to_csv"),
                patch.object(SCRIPT, "RAW_ROOT", temp_dir),
                patch.object(SCRIPT, "DOCS_ROOT", temp_dir),
                patch("sys.argv", ["puller", "--user", "Test User"]),
            ):
                SCRIPT.main()

            self.assertEqual(prompt.call_count, 2)  # date, then checkpoint
            self.assertIn("max", prompt.call_args_list[0].args[0])
            self.assertIn("cancel", prompt.call_args_list[0].args[0])
            fetch_max.assert_called_once()

    def test_date_prompt_cancel_exits_without_pulling(self):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", return_value="cancel"),
            patch.object(
                SCRIPT,
                "resolve_user_address",
                return_value=(SCRIPT.USER_ADDRESS, "Test User"),
            ),
            patch.object(SCRIPT, "fetch_activity") as fetch,
            patch.object(SCRIPT, "fetch_max_activity") as fetch_max,
            patch("sys.argv", ["puller", "--user", "Test User"]),
        ):
            with self.assertRaises(SystemExit) as stopped:
                SCRIPT.main()

        self.assertEqual(stopped.exception.code, 0)
        fetch.assert_not_called()
        fetch_max.assert_not_called()

    def test_ctrl_c_at_date_prompt_cancels(self):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("builtins.input", side_effect=KeyboardInterrupt),
            patch.object(
                SCRIPT,
                "resolve_user_address",
                return_value=(SCRIPT.USER_ADDRESS, "Test User"),
            ),
            patch.object(SCRIPT, "fetch_activity") as fetch,
            patch("sys.argv", ["puller", "--user", "Test User"]),
        ):
            with self.assertRaises(SystemExit) as stopped:
                SCRIPT.main()

        self.assertEqual(stopped.exception.code, 0)
        fetch.assert_not_called()

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
                "Market_Slug": "btc-updown-5m-1000",
                "Timestamp_UTC": "2026-11-07T00:19:00+00:00",
                "timestamp": 1140,
                "Type": "TRADE",
            },
            {
                "Market_Slug": "btc-updown-5m-1300",
                "Timestamp_UTC": "2026-11-07T00:22:00+00:00",
                "timestamp": 1320,
                "Type": "TRADE",
            },
            {
                "Market_Slug": "btc-updown-5m-1600",
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
        self.assertEqual(cleaned[0]["Market_Slug"], "btc-updown-5m-1300")

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
