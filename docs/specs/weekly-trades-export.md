# Weekly Polymarket Trades Export

## Goal

Extend `save-trades-to-csv.py` to export a full week by default and report fetch
progress in the terminal as API pages arrive.

## Behavior

- The default export covers seven rolling days ending at the parsed target
  date/time. A date-only target represents the full requested UTC date and the
  six preceding days; an exact timestamp or `now` is the window's end boundary.
- Add `--days` with supported values `1` and `7`, defaulting to `7`. A one-day
  export retains the existing 24-hour behavior.
- Reuse the existing pagination, record validation, and tail-market handling
  for both window sizes. Preserve custom `--output` behavior.
- Default weekly filenames use the sanitized display name and covered UTC date
  range: `<username>_<start-date>_to_<end-date>.csv`. For a date-only target,
  the end date is the requested date; for an exact timestamp or `now`, it is
  the UTC calendar date of the target. The start date is the UTC calendar date
  at the beginning of the window. One-day exports use
  `<username>_<target-date>.csv`, where a date-only target uses the requested
  date and a timestamp or `now` uses the target's UTC calendar date.

## Progress and errors

After processing each API response page, print and flush a progress line with
the page number, number of API records received on that page, and cumulative
API records received. Do not display a percentage or total page count because
the API does not provide a reliable total. API and response-validation errors
remain explicit; they must not be converted into a successful partial export.

## Verification

Update the focused Python tests to verify:

- one-day and seven-day request boundaries, including date-only and timestamp
  targets;
- default filenames for both durations and sanitized usernames;
- per-page progress contents and flushing while pagination continues;
- preservation of pagination, tail handling, and explicit output-path behavior.

Run `docs/dangerously-skip-permissions/tests/test_save_trades_to_csv.py`.

## Scope

This change does not add arbitrary duration values, parallel fetching, a
progress-bar dependency, or changes to the CSV columns and serialization.
