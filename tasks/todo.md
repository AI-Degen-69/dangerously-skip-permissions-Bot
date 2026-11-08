# Implementation Checklist - Issue #6

- [x] Task 1: Active REST Fallback Poller & Tick Condition in `bot/ws.py`
  - [x] Add `rest_poll_interval` and `_tick_cond` to `LiveBookStreamer`
  - [x] Implement `wait_for_tick(timeout)`
  - [x] Implement `_fallback_worker` and `_poll_rest_fallback`
  - [x] Start/stop fallback poller thread safely in `start()` / `stop()`
  - [x] Notify `_tick_cond` on WS snapshot/deltas and REST polls
- [x] Task 2: Dynamic Event-Driven Execution Loop in `bot/live_paper.py`
  - [x] Remove blocking 5-second sleeps on missing prices/dust/M1-M3 filters
  - [x] Remove pacing calculation sleep (`left / remaining`)
  - [x] Add dynamic fill gating: minimum execution spacing (>=0.5s) & tick-increment checks
  - [x] Integrate `streamer.wait_for_tick(0.25)` in the decision loop
- [x] Task 3: Unit & Integration Tests in `bot/tests/`
  - [x] Test active REST fallback background worker cadence & ticks in `bot/tests/test_ws.py`
  - [x] Test `wait_for_tick` wakeups in `bot/tests/test_ws.py`
  - [x] Test non-blocking responsive loop and anti-runaway guard in `bot/tests/test_live_paper.py`
  - [x] Full regression verification across entire suite (`python -m unittest discover -s bot/tests`)
