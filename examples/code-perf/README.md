# Example: Code Performance Optimization

Maximize Python JSON parsing throughput with Open Researcher — from baseline ~5,000 ops/sec to ~50,000+ ops/sec through pure code optimization.

## Prerequisites

- Python 3.10+
- No additional dependencies (stdlib only)
- CPU is sufficient
- One AI agent installed: `claude` (Claude Code), `codex`, `aider`, or `opencode`

## Quick Start

```bash
# 1. Create project directory with a JSON parser + benchmark
mkdir code-perf && cd code-perf

# Write a baseline recursive descent JSON parser (parser.py) and
# a benchmark script (bench.py) that:
#   - Parses a set of JSON test strings
#   - Measures ops/sec (parse operations per second)
#   - Prints ops_per_sec at the end

# 2. Initialize Open Researcher
pip install open-researcher
open-researcher init --tag code-perf

# 3. Launch autonomous research
open-researcher run --agent claude-code

# Or run headless with a specific goal
open-researcher run --mode headless \
  --goal "Maximize JSON parsing throughput (ops/sec) by optimizing the Python parser implementation with better algorithms, data structures, caching, and code-level optimizations" \
  --max-experiments 20
```

## What the Agent Will Try

- Algorithm optimization (recursive descent vs iterative, state machines)
- Data structure replacements (dict vs OrderedDict, list pre-allocation)
- String processing optimization (avoid repeated slicing, use memoryview)
- Caching strategies (memoization for repeated structures)
- Python-specific tricks (\_\_slots\_\_, local variable access, reduce function calls)
- Regex vs hand-written tokenization
- Memory allocation reduction
- Branch prediction-friendly code patterns

## Metrics

- **Primary:** `ops_per_sec` (higher is better) — JSON parse operations per second
- **Evaluation:** Run benchmark with test JSON strings, measure throughput
- **Typical baseline:** ~5,000 ops/sec (naive recursive descent parser)
- **Typical best after ~15 experiments:** ~50,000+ ops/sec
