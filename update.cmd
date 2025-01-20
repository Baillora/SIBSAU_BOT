@echo off

where /Q curl || (
    echo Updating only supported on Windows 10 and later
    pause
    exit /b
)

echo Downloading latest SIBSAU BOT

REM This is a special GitHub link that points to the latest release. We always name our releases the same.
curl -# -O -L https://github.com/Baillora/SIBSAU_BOT/releases/latest/download/sibsau/bot.py

if errorlevel 1 (
    echo There was some error trying to download
    pause
    exit /b
)

echo Latest SIBSAU BOT is downloaded!
pause
