@echo off
set "ERR=0"
python -m unittest discover -s tests
if errorlevel 1 set "ERR=1"
if "%ERR%"=="0" (
  python -m compileall -q .
  if errorlevel 1 set "ERR=1"
)
if "%ERR%"=="0" (
  echo PASS
) else (
  echo FAIL
)
cmd /c exit %ERR%
if /i not "%~1"=="nopause" pause
