import argparse
import random
from time import perf_counter

from utils.alias import Alias
import utils.speed as speed


SAMPLE_RESULT = {
    "speed": 12.34,
    "delay": 120,
    "resolution": "1920x1080",
    "ipv_type": "ipv4",
    "url": "http://example.com/stream",
    "origin": "subscribe",
}


def _measure(label, func, iterations: int) -> float:
    start = perf_counter()
    for _ in range(iterations):
        func()
    elapsed = perf_counter() - start
    print(f"{label}: {elapsed:.6f}s ({iterations / elapsed:.1f} ops/s)")
    return elapsed


def benchmark_alias(iterations: int) -> None:
    alias = Alias()
    names = list(alias.alias_to_primary.keys()) or ["CCTV-1", "CCTV1", "央视频道"]
    if not names:
        names = ["CCTV-1"]

    sample_names = [names[i % len(names)] for i in range(max(10, min(iterations, len(names) * 4)))]
    random.shuffle(sample_names)

    # cold-ish pass: first access primes the cache
    for name in sample_names:
        alias.get_primary(name)

    _measure("alias_hot", lambda: [alias.get_primary(name) for name in sample_names], iterations=max(1, iterations // len(sample_names)))


def benchmark_speed_cache(iterations: int) -> None:
    speed.clear_cache()
    keys = [f"host-{i}.example.com" for i in range(max(16, min(256, iterations // 2)))]
    for key in keys:
        speed.cache[key] = [dict(SAMPLE_RESULT)]

    sample_keys = [keys[i % len(keys)] for i in range(max(10, min(iterations, len(keys) * 4)))]
    random.shuffle(sample_keys)

    def lookup_all():
        for key in sample_keys:
            speed.get_speed_result(key)

    _measure("speed_cache_hot", lookup_all, iterations=max(1, iterations // len(sample_keys)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the hottest IPTV-API cache paths.")
    parser.add_argument("--iterations", type=int, default=5000, help="Total loop iterations to approximate.")
    args = parser.parse_args()

    print("[benchmark] hotspot cache timings")
    benchmark_alias(args.iterations)
    benchmark_speed_cache(args.iterations)


if __name__ == "__main__":
    main()
