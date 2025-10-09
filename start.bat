@echo off
chcp 65001 >nul
title Telegram Bot + Web Panel

:restart
cls
echo ==========================================
echo   Запуск Telegram Bot + Web Panel
echo ==========================================
echo.
py main.py

if errorlevel 42 (
    echo.
    echo ♻️ Перезапуск по команде...
    timeout /t 2 /nobreak >nul
    goto restart
)

if errorlevel 1 (
    echo.
    echo ❌ Ошибка выполнения
    pause
    exit /b 1
)

echo.
echo ✅ Работа завершена штатно
pause