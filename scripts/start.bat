@echo off
REM Windows 启动脚本。管理页构建需要已安装 Node.js。
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
  echo 需要 Python 3.11+
  exit /b 1
)

if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -U pip
python -m pip install -e ".[dev]"

where npm >nul 2>nul
if errorlevel 1 (
  echo 未找到 npm，只启动 API。安装 Node.js 后重新运行可构建页面。
) else (
  call npm install
  call npm run build
)

if not exist data mkdir data
python -m src.main
