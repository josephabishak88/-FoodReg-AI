@echo off
cd /d "%~dp0"
python regulatory_update_engine.py
if errorlevel 1 (
  echo.
  echo Regulatory update monitor finished with an error.
  pause
  exit /b 1
)
echo.
echo Regulatory source check complete.
pause
