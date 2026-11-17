#!/bin/bash
# 默认跑 10 分钟。8 小时实机：bash scripts/soak_8h.sh 28800
set -euo pipefail
cd "$(dirname "$0")/.."
DURATION="${1:-600}"
python3 scripts/soak_8h.py --duration "$DURATION" --interval 1
