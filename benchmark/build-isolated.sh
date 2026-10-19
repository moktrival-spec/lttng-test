#!/usr/bin/env bash
set -euo pipefail
BASE=$(cd "$(dirname "$0")/.." && pwd)
DEPS="$BASE/deps/usr"
export LD_LIBRARY_PATH="$DEPS/lib/x86_64-linux-gnu"
cd "$BASE/benchmark"
g++ -std=c++17 -O2 -Wall -Wextra -Werror -pthread \
 -I. -isystem spdlog-1.15.3/include -isystem "$DEPS/include/x86_64-linux-gnu" -isystem "$DEPS/include" \
 bench.cpp bench-tp.cpp -L"$DEPS/lib/x86_64-linux-gnu" -llttng-ust -ldl -o bench
