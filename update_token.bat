@echo off
echo ============================================
echo   Zerodha Token Updater
echo ============================================
echo.
echo Paste your new enctoken below and press Enter:
echo.
set /p TOKEN="Enctoken: "
echo %TOKEN%> "%~dp0enctoken.txt"
echo.
echo Token saved to enctoken.txt
echo.
echo Testing connection...
python "%~dp0daily_collector.py" --stats
pause
