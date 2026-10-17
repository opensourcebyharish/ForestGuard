"""Command-line runner for deterministic ForestGuard demonstration data."""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass

from simulator.client import ApiError, ForestGuardClient
from simulator.scenarios import SCENARIOS, SensorGenerator


@dataclass(frozen=True)
class Options:
    api_url: str
    stations: int
    interval: float
    scenario: str
    seed: int | None
    duration: float | None
    station_prefix: str


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    if parsed > 100:
        raise argparse.ArgumentTypeError("must not exceed 100")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send clearly simulated sensor data to ForestGuard.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--stations", type=positive_int, default=1)
    parser.add_argument("--interval", type=positive_float, default=5.0)
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--duration", type=positive_float, help="Run time in seconds; omit to run until Ctrl+C.")
    parser.add_argument("--station-prefix", default="FG-SIM")
    return parser


def parse_options(argv: list[str] | None = None) -> Options:
    args = build_parser().parse_args(argv)
    if not args.api_url.startswith(("http://", "https://")):
        raise ValueError("--api-url must start with http:// or https://")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,57}", args.station_prefix):
        raise ValueError("--station-prefix must be a valid station ID prefix (up to 58 characters)")
    return Options(**vars(args))


def run(options: Options, client: ForestGuardClient | None = None) -> int:
    api = client or ForestGuardClient(options.api_url)
    generators = []
    for index in range(1, options.stations + 1):
        node_id = f"{options.station_prefix}-{index:03d}"
        # Separate per-station streams remain reproducible if station count changes.
        seed = None if options.seed is None else options.seed + index
        latitude = 37.75 + index * 0.001
        longitude = -119.59 - index * 0.001
        api.ensure_station(node_id, f"Simulated station {index:03d}", latitude, longitude)
        generators.append(SensorGenerator(node_id, seed, latitude, longitude))

    print(f"SIMULATED DATA ONLY | scenario={options.scenario} | stations={options.stations}")
    started = time.monotonic()
    sent = failed = 0
    try:
        while options.duration is None or time.monotonic() - started < options.duration:
            for generator in generators:
                try:
                    api.send_reading(generator.reading(options.scenario))
                    sent += 1
                    print(f"sent simulated reading: {generator.node_id}")
                except ApiError as error:
                    failed += 1
                    print(f"failed {generator.node_id}: {error}", file=sys.stderr)
            remaining = options.interval - (time.monotonic() - started) % options.interval
            if options.duration is not None:
                remaining = min(remaining, max(0.0, options.duration - (time.monotonic() - started)))
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("\nStopping simulator...")
    print(f"Simulator stopped. Simulated readings sent: {sent}; failures: {failed}.")
    return 1 if failed and not sent else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.api_url.startswith(("http://", "https://")):
        parser.error("--api-url must start with http:// or https://")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,57}", args.station_prefix):
        parser.error("--station-prefix must be a valid station ID prefix (up to 58 characters)")
    options = Options(**vars(args))
    try:
        return run(options)
    except ApiError as error:
        print(f"Simulator could not initialize: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
