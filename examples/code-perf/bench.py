#!/usr/bin/env python3
"""Benchmark for the JSON parser.

Measures parse operations per second on a fixed set of test strings.
Prints ``ops_per_sec <value>`` for Open Researcher to capture.
"""

import json
import time

from parser import parse

# ---------------------------------------------------------------------------
# Test data — a mix of small/medium JSON payloads
# ---------------------------------------------------------------------------
TEST_STRINGS = [
    '{"name": "Alice", "age": 30, "active": true}',
    '[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]',
    '{"nested": {"a": {"b": {"c": 42}}}}',
    '"hello world"',
    '123456',
    'true',
    'null',
    '{"list": [1, "two", 3.0, null, false, {"key": "value"}]}',
    '[{"id": 1, "name": "x"}, {"id": 2, "name": "y"}, {"id": 3, "name": "z"}]',
    '{"escape": "line1\\nline2\\ttab", "unicode": "\\u0041\\u0042\\u0043"}',
    '{"empty_obj": {}, "empty_arr": [], "zero": 0, "neg": -1.5e10}',
    json.dumps({f"key_{i}": i * 0.1 for i in range(50)}),
    json.dumps([{"id": i, "val": f"item_{i}", "flag": i % 2 == 0} for i in range(20)]),
]

# Verify correctness first
for s in TEST_STRINGS:
    expected = json.loads(s)
    actual = parse(s)
    assert actual == expected, f"Mismatch for input: {s!r}"

# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------
WARMUP_SECONDS = 0.5
BENCH_SECONDS = 3.0


def run_benchmark() -> float:
    # Warmup
    deadline = time.perf_counter() + WARMUP_SECONDS
    while time.perf_counter() < deadline:
        for s in TEST_STRINGS:
            parse(s)

    # Timed
    ops = 0
    start = time.perf_counter()
    deadline = start + BENCH_SECONDS
    while time.perf_counter() < deadline:
        for s in TEST_STRINGS:
            parse(s)
            ops += 1

    elapsed = time.perf_counter() - start
    return ops / elapsed


if __name__ == "__main__":
    throughput = run_benchmark()
    print(f"ops_per_sec {throughput:.0f}")
