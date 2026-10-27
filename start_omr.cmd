@echo off
pushd "%~dp0"
powershell -NoProfile -File ".\tools\start_omr_app.ps1"
popd
pause
