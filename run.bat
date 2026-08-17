@echo off
cd /d "%~dp0"
python pressure_monitor.py
if errorlevel 1 pause
