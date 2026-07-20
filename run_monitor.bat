@echo off
cd /d "D:\study\kite"
set PYTHONIOENCODING=utf-8
python kite\live_monitor\monitor.py >> data\monitor_startup.log 2>&1
