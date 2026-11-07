import csv
import datetime
import time

import requests


BASE_URL = "https://data-api.polymarket.com/v2/activity"
USER_ADDRESS = "0xc53375ff94e96100f2b30a4b5775db35218d69a9"
OUTPUT_CSV = "dangerously-skip-permissions_24h_trades.csv"
PAGE_LIMIT = 100
REQUEST_DELAY_SECONDS = 0.2
REQUEST_TIMEOUT_SECONDS = 30
UTC = datetime.timezone.utc

CSV_FIELDS = [
    "Proxy_Wallet",
    "Timestamp_UTC",
    "Type",
    "Market",
    "Outcome",
    "Side",
    "Price",
    "Shares",
    "USD_Amount",
    "Condition_ID",
    "Token_ID",
    "Transaction_Hash",
    "Market_Slug",
    "Event_Slug",
]


def fetch_24h_activity(now=None):
    if now is None:
        now = datetime.datetime.now(UTC)
    elif now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    else:
        now = now.astimezone(UTC)

    end_ts = int(now.timestamp())
    start_ts = end_ts - 24 * 60 * 60
    print(
        "Fetching account activity from "
        f"{datetime.datetime.fromtimestamp(start_ts, tz=UTC).isoformat()} "
        f"to {datetime.datetime.fromtimestamp(end_ts, tz=UTC).isoformat()}..."
    )

    records = []
    cursor = None
    seen_cursors = set()

    while True:
        params = {
            "user": USER_ADDRESS,
            "start": start_ts,
            "end": end_ts,
            "limit": PAGE_LIMIT,
        }
        if cursor is not None:
            params["cursor"] = cursor

        response = requests.get(
            BASE_URL,
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Polymarket activity response must be a JSON object")

        page = payload.get("data")
        pagination = payload.get("pagination")
        if not isinstance(page, list) or not isinstance(pagination, dict):
            raise ValueError(
                "Polymarket activity response must contain data and pagination"
            )
        if "next_cursor" not in pagination:
            raise ValueError(
                "Polymarket activity pagination is missing next_cursor"
            )

        for activity in page:
            if not isinstance(activity, dict):
                raise ValueError("Polymarket activity records must be JSON objects")

            timestamp = activity.get("timestamp")
            if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                raise ValueError("Polymarket activity timestamp must be numeric")
            if timestamp < start_ts or timestamp > end_ts:
                continue

            records.append(
                {
                    "Proxy_Wallet": activity.get("proxy_wallet"),
                    "Timestamp_UTC": datetime.datetime.fromtimestamp(
                        timestamp, tz=UTC
                    ).isoformat(),
                    "Type": activity.get("type"),
                    "Market": activity.get("title"),
                    "Outcome": activity.get("outcome"),
                    "Side": activity.get("side"),
                    "Price": activity.get("price"),
                    "Shares": activity.get("size"),
                    "USD_Amount": activity.get("usdc_size"),
                    "Condition_ID": activity.get("condition_id"),
                    "Token_ID": activity.get("token_id"),
                    "Transaction_Hash": activity.get("transaction_hash"),
                    "Market_Slug": activity.get("slug"),
                    "Event_Slug": activity.get("event_slug"),
                }
            )

        next_cursor = pagination["next_cursor"]
        if next_cursor is None:
            break
        if not isinstance(next_cursor, str) or not next_cursor:
            raise ValueError("Polymarket next_cursor must be a non-empty string or null")
        if next_cursor in seen_cursors:
            raise ValueError("Polymarket returned a repeated activity cursor")

        seen_cursors.add(next_cursor)
        cursor = next_cursor
        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"Retrieved {len(records)} activity records.")
    return records


def save_to_csv(records):
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(records)

    print(f"Successfully saved {len(records)} activity records to '{OUTPUT_CSV}'.")


if __name__ == "__main__":
    activity = fetch_24h_activity()
    if not activity:
        print("No account activity found within the 24-hour window.")
    save_to_csv(activity)
