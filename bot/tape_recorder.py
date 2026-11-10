from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot import constants as C
from bot.ws import LiveBookStreamer

DEFAULT_MAX_MB = 20.0
HEARTBEAT_S = 30.0


def estimate_mb_per_hour(bytes_written: int, elapsed_s: float) -> float:
    if elapsed_s <= 0:
        return 0.0
    return bytes_written / (1024 * 1024) / (elapsed_s / 3600.0)


def dir_size_bytes(d: Path) -> int:
    total = 0
    try:
        for p in d.glob('*.jsonl'):
            try:
                total += p.stat().st_size
            except Exception:
                pass
    except Exception:
        pass
    return total


def resolve_out_dir(run_id: str | None, out_dir: str | None) -> Path:
    if out_dir:
        return Path(out_dir)
    base = Path('bot/runs') / (run_id or 'tape-manual')
    return base / 'tape'


def run_recorder(up_token_id: str, down_token_id: str, out_dir: Path, max_mb: float = DEFAULT_MAX_MB, duration_s: float = 0.0, stale_s: float = 120.0) -> int:
    try:
        stale_limit = float(getattr(C, 'HEARTBEAT_STALE_S', 120.0))
    except Exception:
        stale_limit = 120.0
    try:
        stale_limit = float(stale_s or stale_limit)
    except Exception:
        pass
    out_dir.mkdir(parents=True, exist_ok=True)
    streamer = LiveBookStreamer(up_token_id, down_token_id, enable_trade_prints=True, tape_dir=out_dir)
    streamer.start()
    start = time.time()
    last_beat = 0.0
    last_frame_ts = time.time()
    last_counts = (0, 0)
    try:
        while True:
            time.sleep(1.0)
            now = time.time()
            elapsed = now - start
            tc = streamer.tick_count + streamer.print_count
            if tc != last_counts[0] + last_counts[1] if isinstance(last_counts, tuple) else True:
                last_frame_ts = now
            last_counts = (streamer.tick_count, streamer.print_count)
            if streamer.tick_count > 0 or streamer.print_count > 0:
                last_frame_ts = now
            used_mb = dir_size_bytes(out_dir) / (1024 * 1024)
            if used_mb >= max_mb:
                print(f'stopping: tape budget reached ({used_mb:.2f} MB >= {max_mb:.1f} MB)')
                return 0
            if duration_s and elapsed >= duration_s:
                mbph = estimate_mb_per_hour(dir_size_bytes(out_dir), elapsed)
                print(f'done: prints={streamer.print_count} ticks={streamer.tick_count} mb_per_hour={mbph:.2f}')
                return 0
            if now - last_beat >= HEARTBEAT_S:
                last_beat = now
                mbph = estimate_mb_per_hour(dir_size_bytes(out_dir), elapsed)
                print(f'heartbeat prints={streamer.print_count} ticks={streamer.tick_count} mb={used_mb:.3f} mb_per_hour={mbph:.3f}', flush=True)
            if now - last_frame_ts > stale_limit:
                print(f'stale: no frames for {now - last_frame_ts:.0f}s, exiting non-zero')
                return 2
    except KeyboardInterrupt:
        print('interrupted')
        return 0
    finally:
        try:
            streamer.stop()
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description='Sidecar tape recorder: prints + top-5 book')
    ap.add_argument('--up', default='')
    ap.add_argument('--down', default='')
    ap.add_argument('--slug', default='')
    ap.add_argument('--slot', type=int, default=0)
    ap.add_argument('--out-dir', default='')
    ap.add_argument('--run-id', default='')
    ap.add_argument('--max-mb', type=float, default=DEFAULT_MAX_MB)
    ap.add_argument('--duration', type=float, default=0.0)
    ap.add_argument('--stale-s', type=float, default=120.0)
    args = ap.parse_args()
    up = args.up
    down = args.down
    if (not up or not down) and (args.slug or args.slot):
        from polymarket import PublicClient
        from bot.discovery import current_slot, get_window
        slot = args.slot or current_slot()
        slug = args.slug or f'btc-updown-5m-{slot}'
        c = PublicClient()
        spec = get_window(c, slug)
        up = spec.up_token_id
        down = spec.down_token_id
        print(f'target {slug}')
    if not up or not down:
        print('need --up/--down or --slug/--slot', file=sys.stderr)
        sys.exit(2)
    out = resolve_out_dir(args.run_id, args.out_dir or None)
    print(f'writing tape to {out}')
    sys.exit(run_recorder(up, down, out, max_mb=args.max_mb, duration_s=args.duration, stale_s=args.stale_s))


if __name__ == '__main__':
    main()
