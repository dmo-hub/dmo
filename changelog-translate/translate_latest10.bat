@echo off
chcp 65001 >nul
rem Translate the 10 latest changelog updates to Thai via Claude Code CLI.
rem Usage: translate_latest10.bat [path-to-changelog.txt]
rem        (no argument = auto-detect changelog .txt in this folder)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0translate_latest10.ps1" %*
pause
