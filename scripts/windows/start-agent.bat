@echo off
rem Double-click to start the Autofill Agent. Close the window (or press Ctrl+C) to stop it.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-agent.ps1"
if errorlevel 1 pause
