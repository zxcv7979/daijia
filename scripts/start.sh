#!/usr/bin/env bash
# macOS / Linux 开发启动。Windows 用 scripts/start.bat。
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"

if command -v npm >/dev/null 2>&1; then
  npm install
  npm run build
else
  echo "未找到 npm，只启动 API。安装 Node.js 后重新运行可构建管理页和特效页。"
fi

mkdir -p data
exec python -m src.main
