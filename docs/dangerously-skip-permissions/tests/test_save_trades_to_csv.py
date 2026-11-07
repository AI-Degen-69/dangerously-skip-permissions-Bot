import csv
import datetime
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
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def raise_for_status(self):
        if self.error is not None:
            raise self.error

    def json(self):
        return self.payload


class SaveTradesToCsvTests(unittest.TestCase):
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
            records = SCRIPT.fetch_24h_activity(now=now)

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
            with patch.object(SCRIPT, "OUTPUT_CSV", str(output_path)):
                SCRIPT.save_to_csv([])

            with output_path.open(encoding="utf-8", newline="") as output_file:
                reader = csv.reader(output_file)
                header = next(reader)
                rows = list(reader)

        self.assertIn("Type", header)
        self.assertEqual(rows, [])

    def test_propagates_http_errors(self):
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse(error=requests.HTTPError("service unavailable")),
        ):
            with self.assertRaises(requests.HTTPError):
                SCRIPT.fetch_24h_activity(
                    now=datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)
                )

    def test_rejects_invalid_response_shapes(self):
        with patch.object(
            SCRIPT.requests,
            "get",
            return_value=FakeResponse({"data": [], "pagination": {}}),
        ):
            with self.assertRaisesRegex(ValueError, "missing next_cursor"):
                SCRIPT.fetch_24h_activity(
                    now=datetime.datetime(2026, 11, 7, tzinfo=datetime.timezone.utc)
                )


if __name__ == "__main__":
    unittest.main()
