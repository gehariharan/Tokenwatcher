@echo off
setlocal
pushd "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Virtual env not found. Run install.bat first.
    popd
    exit /b 1
)

.venv\Scripts\python.exe -m tokenwatcher %*
popd
