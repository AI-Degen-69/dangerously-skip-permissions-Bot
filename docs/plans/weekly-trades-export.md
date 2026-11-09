# Weekly Trades Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task with checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Polymarket CSV exporter fetch seven rolling days by default and flush page-by-page progress to the terminal.

**Architecture:** Generalize the existing activity fetcher to accept only one- or seven-day windows while preserving its pagination, filtering, and tail-cutting flow. Keep CLI orchestration in `main()`, derive output filenames from the chosen date range, and emit progress from the shared pagination loop so both durations report consistently.

**Tech Stack:** Python 3, `requests`, standard-library `argparse` and `unittest`; no new dependencies.

## Global Constraints

- The default export covers seven rolling days ending at the parsed target date/time.
- Add `--days` with supported values `1` and `7`, defaulting to `7`.
- Preserve custom `--output` behavior.
- After processing each API response page, print and flush a progress line with the page number, number of API records received on that page, and cumulative API records received.
- Do not display a percentage or total page count because the API does not provide a reliable total.
- API and response-validation errors remain explicit; they must not be converted into a successful partial export.
- This change does not add arbitrary duration values, parallel fetching, a progress-bar dependency, or changes to the CSV columns and serialization.

---

## File Structure

- `docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py`: Owns CLI options, fetch-window bounds, pagination progress, output naming, and CSV writing.
- `docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py`: Exercises request bounds, filenames, pagination, output, and immediate progress flushing.
- `docs/specs/weekly-trades-export.md`: Approved behavior contract; implementation must remain consistent with it.

The change is a single subsystem in two source/test files. Keep the existing layout; do not extract modules or add dependencies.

### Task 1: Generalize the Fetch Window and Default Filename

**Files:**
- Modify: `docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py`
- Test: `docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py`

**Interfaces:**
- Produce `fetch_activity(user_address: str | None = None, now: datetime.datetime | str | None = None, snap_to_window: bool = True, cut_tails: bool = True, verify_remote: bool = False, window_days: int = 7) -> list[dict]`.
- Produce `default_output_filename(display_name: str, target_dt: datetime.datetime, window_days: int, date_only: bool) -> str`.
- The CLI accepts only `--days 1` or `--days 7`, defaulting to `7`.

- [x] **Step 1: Add failing range and filename tests**

Add these methods to `SaveTradesToCsvTests`. The test uses an explicit UTC target with snapping disabled so the asserted duration is independent of window alignment:

```python
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
```

- [x] **Step 2: Run the focused new tests and confirm they fail**

Run:

```powershell
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_fetches_requested_window_lengths
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_fetches_seven_days_ending_after_requested_date
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_rejects_unsupported_window_length
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_default_output_filename_includes_week_range
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_default_output_filename_keeps_single_day_shape
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_default_output_filename_uses_target_utc_date_for_timestamp
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_main_preserves_custom_output_and_defaults_to_week
```

Expected: each command fails because `fetch_activity` and/or its filename
helper have not been introduced.

- [x] **Step 3: Generalize the existing fetcher**

Rename `fetch_24h_activity` to `fetch_activity`, add `window_days` at the end of its parameters, and replace the fixed duration and status text with:

```python
if window_days not in (1, 7):
    raise ValueError("window_days must be 1 or 7")

start_ts = end_ts - window_days * 24 * 60 * 60

print(
    f"Fetching activity for {user_address} backward from "
    f"{datetime.datetime.fromtimestamp(end_ts, tz=UTC).isoformat()} "
    f"to {datetime.datetime.fromtimestamp(start_ts, tz=UTC).isoformat()} "
    f"({window_days}-day window)..."
)
```

Preserve the current cursor handling, validation, record filtering, tail cutting, and record cleanup. Update all test references from `SCRIPT.fetch_24h_activity(...)` to `SCRIPT.fetch_activity(...)`; when a test specifically asserts the old one-day behavior, pass `window_days=1`.

- [x] **Step 4: Add window-aware filename generation**

Replace `default_output_filename` with:

```python
def default_output_filename(
    display_name: str,
    target_dt: datetime.datetime,
    window_days: int,
    date_only: bool,
) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", display_name).lower()
    target_date = target_dt.date()
    if date_only:
        target_date -= datetime.timedelta(days=1)

    if window_days == 1:
        return f"{safe_name}_{target_date:%Y-%m-%d}.csv"

    start_date = (
        target_date - datetime.timedelta(days=window_days - 1)
        if date_only
        else (target_dt - datetime.timedelta(days=window_days)).date()
    )
    return (
        f"{safe_name}_{start_date:%Y-%m-%d}_to_"
        f"{target_date:%Y-%m-%d}.csv"
    )
```

In `main()`, add the duration argument:

```python
parser.add_argument(
    "--days",
    type=int,
    choices=(1, 7),
    default=7,
    help="Number of days to fetch (1 or 7; default: 7)",
)
```

Replace the parser description with:

```python
parser = argparse.ArgumentParser(
    description="Save Polymarket activity to CSV."
)
```

Use this help text for the existing date argument:

```python
help=(
    "Target date/time ending the fetch window. A date-only value fetches "
    "that full UTC date and preceding days; default: now"
)
```

When selecting the default output name, determine `date_only` from the
already-validated input:

```python
normalized_date_input = date_input.strip()
date_only = (
    normalized_date_input.lower() != "now"
    and "T" not in normalized_date_input
    and len(normalized_date_input.split()) == 1
)
output_file = default_output_filename(
    display_name,
    target_dt,
    window_days=args.days,
    date_only=date_only,
)
```

Keep the existing `if args.output` branch before this code so an explicit
output path still takes precedence. Call
`fetch_activity(..., window_days=args.days)`. Change the empty-result message to:

```python
print(f"No account activity found within the {args.days}-day window.")
```

- [x] **Step 5: Run the focused suite**

Run:

```powershell
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py
```

Expected: all tests pass, including the existing date parsing, cursor, response-validation, tail-cutting, and CSV-writing coverage.

- [x] **Step 6: Verify CLI help and whitespace**

Run:

```powershell
python docs\dangerously-skip-permissions\scripts\save-trades-to-csv.py --help
git diff --check
```

Expected: help lists `--days {1,7}` with default `7`, and `git diff --check` reports no whitespace errors.

- [x] **Step 7: Commit the independently tested window change**

Stage only the two task files and commit:

```powershell
git add -- docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py
git diff --cached --stat
git commit -m "feat: export one or seven days of Polymarket activity" -m "Make weekly exports the default while retaining a one-day option and date-range filenames." -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Stream Per-Page Fetch Progress

**Files:**
- Modify: `docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py`
- Test: `docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py`

**Interfaces:**
- `fetch_activity(...)` prints one flushed progress line after processing each valid API response page.
- Each line reports the one-based page number, API record count on that page, and cumulative API record count received so far.

- [x] **Step 1: Add a failing multi-page progress test**

Add `import io` to the test imports and add the following test. It asserts the visible lines and that each page explicitly flushes the stream:

```python
    def test_streams_progress_for_each_activity_page(self):
        page_one = {
            "data": [{"timestamp": 1794074400}],
            "pagination": {"next_cursor": "next-page"},
        }
        page_two = {
            "data": [{"timestamp": 1794074399}, {"timestamp": 1794074398}],
            "pagination": {"next_cursor": None},
        }

        class FlushTrackingStream(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flush_count = 0

            def flush(self):
                self.flush_count += 1
                super().flush()

        stream = FlushTrackingStream()
        target = datetime.datetime(2026, 11, 7, 18, 0, tzinfo=datetime.timezone.utc)

        with patch("sys.stdout", stream), patch.object(
            SCRIPT.requests,
            "get",
            side_effect=[FakeResponse(page_one), FakeResponse(page_two)],
        ):
            SCRIPT.fetch_activity(
                now=target,
                window_days=7,
                snap_to_window=False,
                cut_tails=False,
            )

        output = stream.getvalue()
        self.assertIn("Page 1: 1 records; 1 total", output)
        self.assertIn("Page 2: 2 records; 3 total", output)
        self.assertEqual(stream.flush_count, 2)
```

- [x] **Step 2: Run the progress test and confirm it fails**

Run:

```powershell
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_streams_progress_for_each_activity_page
```

Expected: FAIL because the fetcher does not yet print page-level progress.

- [x] **Step 3: Print and flush progress inside the pagination loop**

Initialize counters immediately before the loop:

```python
page_number = 0
fetched_count = 0
```

After all records in a validated `page` have been processed, and before reading `next_cursor`, add:

```python
page_number += 1
fetched_count += len(page)
print(
    f"Page {page_number}: {len(page)} records; "
    f"{fetched_count} total",
    flush=True,
)
```

This reports raw API records received (including any filtered by local timestamp checks), does not invent a total page count, and flushes before the next request.

- [x] **Step 4: Run the progress test and the complete focused suite**

Run:

```powershell
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py SaveTradesToCsvTests.test_streams_progress_for_each_activity_page
python docs\dangerously-skip-permissions\tests\test_save_trades_to_csv.py
git diff --check
```

Expected: the progress test passes with two flushes, the full exporter suite passes, and there are no whitespace errors.

- [x] **Step 5: Commit the streaming progress change**

Stage only the script and its test file and commit:

```powershell
git add -- docs/dangerously-skip-permissions/scripts/save-trades-to-csv.py docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py
git diff --cached --stat
git commit -m "feat: stream Polymarket export page progress" -m "Flush per-page fetched and cumulative counts so long weekly exports remain visible in the terminal." -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
