@echo off

echo ======================================================
echo [*] Starting Stock Split Daily Collector and GDrive Sync
echo ======================================================

set PYTHONPATH=src
uv run main.py --days 7

echo ======================================================
echo [SUCCESS] Daily workflow completed successfully.
echo ======================================================
pause
